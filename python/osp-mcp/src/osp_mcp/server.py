"""``osp-mcp``: an MCP server (stdio) that lets an AI agent draft surveys (task AI1).

    osp-mcp              serve over stdio (what an MCP client such as Claude launches)
    osp-mcp tools        print the tools and their descriptions, then exit (no database)

A thin shell: every tool is one call into :class:`osp_mcp.drafting.Drafting`, which
dispatches app commands on ``osp_app.Builder`` by id. Settings come from the environment,
the same way ``osp-cli`` reads them; there is no sign-in here (plan P): whoever launches the
server says which researcher it acts as, as a host would.

==================  ============================================  ====================
variable            meaning                                       default
==================  ============================================  ====================
OSP_DATABASE_URL    SQLAlchemy URL (the osp-api database)         required
OSP_STORE_KEYS      the store's encryption keyring                required
OSP_MCP_USER        the researcher's host user id                 required
OSP_MCP_LAB         the lab (tenant) id the drafts belong to      required
OSP_MCP_ROLE        owner, editor or viewer                       ``editor``
OSP_MCP_NAME        display name for the audit log                none
OSP_MCP_BUILDER_URL where the builder opens a survey, ``{id}``    ``http://localhost:5173/surveys/{id}``
==================  ============================================  ====================

Guardrails (drafting.py): draft only (no publish, delete, export or results), ops validated
by osp-ops, no participant data. ``check_guardrails()`` runs when this module is imported.
"""

from __future__ import annotations

import functools
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from osp_app import AppServices, InvalidIdentity, build_services, make_identity
from osp_app.identity import check_role, check_tenant_id, check_user_id
from osp_store import DatabaseUrlError, Keyring, Store, StoreError, create_engine, migrate
from osp_store.crypto import ENV_KEYS

from .drafting import DEFAULT_BUILDER_URL, Drafting, DraftingError, check_guardrails
from .recipes import PageSpec, QuestionSpec

check_guardrails()

SERVER_NAME = "open-survey-platform"
ROLES = ("owner", "editor", "viewer")

INSTRUCTIONS = """\
Draft surveys for Open Survey Platform. Workflow: create_survey (or list_surveys), then
build it with add_block / add_page / add_question / add_choice / set_property /
set_condition (or any op via apply_ops; list_ops and describe_op explain them), then
validate and preview, and give the researcher the builderUrl to review it.

Rules: this server only drafts. It cannot publish, delete, export, or read participant
responses; the researcher publishes from the builder after reviewing the draft. Every edit is
validated against the survey model and is undoable (undo with the transactionId). Ids are
variable names (letters, digits, _): choose short meaningful ones (age, consent_q1).
Condition text: `age >= 18`, `coffee == 1 and answered(cups)`, `contains(symptoms, "2")`
(multi only), `if(answered(age), age < 40, false)`. Codes compare as text (1 == "1").
"""


class ConfigError(Exception):
    """Bad or missing settings: printed, exit code 2."""


@dataclass(frozen=True)
class Settings:
    database_url: str
    user_id: str
    lab_id: str
    role: str = "editor"
    display_name: str | None = None
    builder_url: str = DEFAULT_BUILDER_URL

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ

        def need(name: str) -> str:
            value = (env.get(name) or "").strip()
            if not value:
                raise ConfigError(f"{name} must be set")
            return value

        db = need("OSP_DATABASE_URL")
        if not env.get(ENV_KEYS):
            raise ConfigError(f"{ENV_KEYS} must be set (the same keyring as osp-api)")
        role = (env.get("OSP_MCP_ROLE") or "editor").strip().lower()
        try:
            user = check_user_id(need("OSP_MCP_USER"))
            lab = check_tenant_id(need("OSP_MCP_LAB"))
            check_role(role)
        except InvalidIdentity as exc:
            raise ConfigError(str(exc)) from exc
        name = (env.get("OSP_MCP_NAME") or "").strip() or None
        template = (env.get("OSP_MCP_BUILDER_URL") or "").strip() or DEFAULT_BUILDER_URL
        if "{id}" not in template:
            raise ConfigError("OSP_MCP_BUILDER_URL must contain {id}")
        return cls(db, user, lab, role, name, template)


def open_services(settings: Settings, environ: Mapping[str, str] | None = None) -> AppServices:
    env = os.environ if environ is None else environ
    try:
        keyring = Keyring.from_env(env)
        engine = create_engine(settings.database_url)
    except DatabaseUrlError as exc:
        raise ConfigError(f"OSP_DATABASE_URL: {exc}") from exc
    except StoreError as exc:
        raise ConfigError(str(exc)) from exc
    migrate(engine)
    return build_services(Store(engine, keyring))


def drafting_for(settings: Settings, services: AppServices) -> Drafting:
    """The :class:`Drafting` for the configured researcher (lab created on first sight,
    as osp-api does with ``OSP_AUTO_CREATE_LABS=on``)."""
    try:
        identity = make_identity(
            settings.user_id, {settings.lab_id: settings.role}, settings.display_name
        )
    except InvalidIdentity as exc:
        raise ConfigError(str(exc)) from exc
    actor = services.admit(identity)
    return Drafting(services.builder, actor, settings.builder_url)


# -- the MCP server ----------------------------------------------------------------------


def _guard(fn):  # a tool body: DraftingError -> ToolError (is_error, readable text)
    @functools.wraps(fn)  # `__wrapped__` keeps the real signature for the tool schema
    def run(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except DraftingError as exc:
            raise ToolError(exc.render()) from exc

    return run


_READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
_EDIT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)


def build_server(drafting: Drafting) -> MCPServer:
    """Register the drafting tools over ``drafting``. Pure wiring."""
    server = MCPServer(SERVER_NAME, instructions=INSTRUCTIONS, version="0.1")
    d = drafting

    def tool(fn, annotations: ToolAnnotations) -> None:
        server.add_tool(_guard(fn), annotations=annotations)

    # -- surveys ------------------------------------------------------------------------

    def list_surveys() -> list[dict[str, Any]]:
        """The researcher's surveys (id, title, lab, created, builder link). Drafts and
        published surveys alike; this server edits drafts only (get_survey says how many
        versions a survey has published)."""
        return d.list_surveys()

    def create_survey(title: str, survey: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create a new draft survey. With just a title it starts with one block, one page
        and a note; `survey` may be a whole osp-survey/0.1 document instead (validated:
        a structurally invalid one is refused with diagnostics). Returns the surveyId to
        use in every other tool, the revision, the builderUrl and an outline."""
        return d.create_survey(title, survey)

    def get_survey(survey_id: str, full: bool = False) -> dict[str, Any]:
        """A survey's outline: every block, page, question (id, type, label, required,
        choices), choice list, variable and flow node, plus problem counts. `full: true`
        adds the whole survey JSON."""
        return d.get_survey(survey_id, full)

    # -- ops ----------------------------------------------------------------------------

    def list_ops(area: str | None = None) -> list[dict[str, Any]]:
        """Every edit op (id, label, area, one-line summary) for apply_ops. Areas: survey,
        metadata, blocks, pages, questions, choices, choiceLists, conditions, flow,
        variables, matrixRows, themes."""
        return d.list_ops(area)

    def describe_op(op_id: str) -> dict[str, Any]:
        """One op's full description and the JSON Schema of its params."""
        return d.describe_op(op_id)

    def apply_ops(
        survey_id: str, ops: list[dict[str, Any]], base_revision: int | None = None
    ) -> dict[str, Any]:
        """Apply a list of ops `[{op, params}, …]` as one transaction: all or nothing,
        validated by the survey model, undoable with the returned transactionId. Omit
        base_revision to edit the latest draft. Returns the new revision, any warnings and
        the outline after the edit."""
        return d.apply_ops(survey_id, ops, base_revision)

    def add_block(
        survey_id: str,
        block_id: str,
        title: str | None = None,
        pages: list[PageSpec] | None = None,
        in_flow: bool = True,
        flow_index: int | None = None,
    ) -> dict[str, Any]:
        """Add a block (a named run of pages) and place it in the flow (at the end, or at
        flow_index). `pages` gives its pages and their questions in one step; without it
        the block gets one page with one text question to replace. `title` is a label for
        the researcher only."""
        return d.add_block(survey_id, block_id, title, pages, in_flow, flow_index)

    def add_page(
        survey_id: str, block: str, page: PageSpec, index: int | None = None
    ) -> dict[str, Any]:
        """Add a page with its questions to a block (at the end, or at `index`).
        Participants see one page at a time."""
        return d.add_page(survey_id, block, page, index)

    def add_question(
        survey_id: str, page: str, question: QuestionSpec, index: int | None = None
    ) -> dict[str, Any]:
        """Add one question (or note) to a page, with its choices, rows, required flag,
        help text and showIf condition in one step."""
        return d.add_question(survey_id, page, question, index)

    def add_choice(
        survey_id: str,
        owner: str,
        label: str | dict[str, str],
        value: int | str | None = None,
        index: int | None = None,
    ) -> dict[str, Any]:
        """Add an option to a single/multi/matrix question (or a shared choice list).
        `value` is the code stored in the data (default: the next integer)."""
        return d.add_choice(survey_id, owner, label, value, index)

    def set_property(
        survey_id: str, target: str, property: str, value: Any = None, unset: bool = False
    ) -> dict[str, Any]:
        """Set one field of a question, page, block, choice list, variable, flow node,
        `/metadata` (title, description, languages) or `/settings` (backNavigation,
        saveMode, retention, …). `unset: true` removes it. The survey model validates the
        value; describe_op('set_property') and the diagnostics name the editable fields."""
        return d.set_property(survey_id, target, property, value, unset)

    def set_condition(
        survey_id: str, target: str, condition: str | None, field: str | None = None
    ) -> dict[str, Any]:
        """Set a condition from text: a question's or page's showIf (default) or a
        question's constraint, a branch node's if, a quota's when, a computed variable's
        expr. `null` clears it. Syntax: `age >= 18 and answered(q1)`, `q2 == 3 or q2 == 4`,
        `contains(q3, "2")` (multi only), `not q4 == "yes"`. A constraint may refer to its
        own question: `cups <= 20`."""
        return d.set_condition(survey_id, target, condition, field)

    def undo(survey_id: str, transaction_id: str) -> dict[str, Any]:
        """Undo a transaction by its id (from an edit's result or history); undoing an
        undo (`u:…`) redoes it."""
        return d.undo(survey_id, transaction_id)

    def history(survey_id: str) -> list[dict[str, Any]]:
        """The survey's edit history: transactions with their ops and revisions."""
        return d.history(survey_id)

    # -- checks -------------------------------------------------------------------------

    def validate(survey_id: str) -> dict[str, Any]:
        """Validate the draft: every error and warning with a JSON pointer, and the
        publish checks (retention policy, consent page) the builder will ask for."""
        return d.validate(survey_id)

    def preview(survey_id: str) -> dict[str, Any]:
        """Compile the draft into the runtime plan participants would run (nothing is
        published or stored) and return the builder link where the researcher can open
        Preview."""
        return d.preview(survey_id)

    for fn in (list_surveys, get_survey, list_ops, describe_op, history, validate, preview):
        tool(fn, _READ)
    for fn in (
        create_survey,
        apply_ops,
        add_block,
        add_page,
        add_question,
        add_choice,
        set_property,
        set_condition,
        undo,
    ):
        tool(fn, _EDIT)
    return server


def tool_listing(server: MCPServer) -> list[dict[str, str]]:
    import anyio

    tools = anyio.run(server.list_tools)
    return [{"name": t.name, "description": (t.description or "").strip()} for t in tools]


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["tools"]:
        from osp_app.auth import Actor

        server = build_server(Drafting(builder=None, actor=Actor("nobody")))  # type: ignore[arg-type]
        print(json.dumps(tool_listing(server), indent=2))
        return 0
    if args:
        print("usage: osp-mcp [tools]", file=sys.stderr)
        return 2
    try:
        settings = Settings.from_env()
        services = open_services(settings)
        drafting = drafting_for(settings, services)
    except ConfigError as exc:
        print(f"osp-mcp: {exc}", file=sys.stderr)
        return 2
    except StoreError as exc:
        print(f"osp-mcp: store: {exc}", file=sys.stderr)
        return 2
    build_server(drafting).run(transport="stdio")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
