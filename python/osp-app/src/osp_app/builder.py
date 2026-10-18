"""Builder application services: surveys, drafts, ops, undo/redo, publish, export.

Every public method is an app command (``commands.COMMANDS``) and checks ``can()``
before touching data. Locating a survey only searches tenants where the actor may
read surveys, so a survey in another tenant is ``NotFoundError`` (never a hint that
it exists); a permitted reader without the needed action gets ``Forbidden``.

Edit flow (builder-design §4): load draft -> ``osp_ops.apply_transaction`` ->
persist the new revision and one op_log row per op (with its inverse) under one
transaction id -> return ``{revision, patch, diagnostics}``. Undo applies the logged
inverses as a new transaction (id ``u:<hex>``); redo is the undo of an undo (``r:<hex>``).

Publish (runtime-design §3): validate -> compile the runtime plan (``osp_runtime.plan``)
for the body with ``version`` set to the new version number -> freeze the version (body,
plan checksum, runtime config and the XLSForm export as an artefact) -> register the
publication under the survey's public slug, so ``GET /api/s/{slug}/plan/{checksum}``
serves the plan and ``POST /api/s/{slug}/sessions`` starts on it.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Any

from osp_instruments import lookup as bundled_instrument
from osp_ops import Draft as OpsDraft
from osp_ops import Invocation, apply_transaction
from osp_ops.registry import TEXT_CODES
from osp_runtime import InvalidPayload, RuntimeConfig, SessionService
from osp_runtime.config import SAVE_MODES
from osp_runtime.plan import (
    ENGINE_VERSION,
    PLAN_VERSION,
    compile_survey,
    embed_theme,
    runtime_config,
)
from osp_spec import SPEC_VERSION, Diagnostic, parse, publish_diagnostics
from osp_spec.bank import with_instruments
from osp_store import (
    Conflict,
    Draft,
    NotFound,
    OpLogEntry,
    OpRecord,
    RetentionPolicy,
    RevisionConflict,
    Store,
    Survey,
    TenantContext,
)
from osp_targets import (
    ExportDiagnostic,
    export_lss,
    export_qsf,
    export_surveyjs,
    export_xlsform,
)

from .auth.permissions import Action, Actor, Resource, ResourceKind, can
from .commands import command, dispatch
from .errors import (
    ConflictError,
    Forbidden,
    InvalidRequest,
    NotFoundError,
    Rejected,
    RevisionConflictError,
)
from .publish_theme import resolve_theme
from .runtime_repo import StoreParticipantRepo

UNDO_PREFIX = "u:"
REDO_PREFIX = "r:"
_CLIENT_TXN = re.compile(r"^[A-Za-z0-9_-]{1,36}$")
_MAX_TITLE = 500


# -- results --------------------------------------------------------------------------


@dataclass(frozen=True)
class SurveyView:
    survey: Survey
    draft: Draft
    published_versions: int = 0  # how many versions have been published (0: never)


@dataclass(frozen=True)
class EditResult:
    revision: int
    patch: list[dict[str, Any]]
    diagnostics: list[Diagnostic]
    transaction_id: str | None  # None: nothing changed, nothing logged
    replayed: bool = False


@dataclass(frozen=True)
class HistoryEntry:
    transaction_id: str
    kind: str  # edit | undo | redo
    revision: int
    ops: list[str]
    actor: str
    at: datetime


@dataclass(frozen=True)
class PublishResult:
    version_id: str
    number: int
    checksum: str
    published_at: datetime
    revision: int
    diagnostics: list[Diagnostic]
    slug: str  # the survey's public slug: /s/<slug>
    plan_checksum: str
    runtime_plan: Any  # the compiled plan (osp_runtime.plan), as served to participants
    runtime_config: Any  # osp_runtime.RuntimeConfig JSON (assignments, quotas, save mode)


@dataclass(frozen=True)
class ExportResult:
    content: bytes
    filename: str
    diagnostics: list[ExportDiagnostic] = field(default_factory=list)


# -- helpers --------------------------------------------------------------------------


def default_survey(title: str) -> dict[str, Any]:
    """The smallest structurally valid survey: one block, one page, one note."""
    return {
        "specVersion": SPEC_VERSION,
        "id": "survey",
        "metadata": {"title": {"en": title}, "languages": ["en"], "defaultLanguage": "en"},
        "blocks": [
            {
                "id": "b1",
                "pages": [
                    {"id": "p1", "items": [{"id": "intro", "type": "note", "label": {"en": ""}}]}
                ],
            }
        ],
        "flow": [{"type": "block", "id": "n1", "block": "b1"}],
    }


def title_of(body: Any) -> str | None:
    try:
        meta = body["metadata"]
        title = meta["title"]
        if isinstance(title, str):
            text = title
        else:
            text = title.get(meta.get("defaultLanguage")) or next(iter(title.values()), "")
        text = str(text).strip()[:_MAX_TITLE]
        return text or None
    except Exception:
        return None


def xlsform_artefact(body: Any) -> bytes:
    """The XLSForm export kept with a version (``versions.xform``); empty if it can't be
    built. An artefact only: participants run the runtime plan, never this."""
    try:
        content, _ = export_xlsform(body)
    except Exception:  # an export bug must not block publishing
        return b""
    return content or b""


def _retention_policy(body: Any) -> RetentionPolicy:
    """The store policy for the survey's `settings.retention` (validated before this)."""
    r = body["settings"]["retention"]
    if r["kind"] == "days-after-close":
        return RetentionPolicy.days_after_close(r["days"])
    if r["kind"] == "after-date":
        until = datetime.combine(date.fromisoformat(r["until"]), time.min, tzinfo=UTC)
        return RetentionPolicy.after_date(until)
    return RetentionPolicy.none()  # "indefinite": kept until the researcher deletes it


RETENTION_REQUIRED = "publish.retention_required"
HOOKS_CHANGED = "survey.hooks_changed"
"""Audit action for a transaction that changes the survey's hook manifest (custom code,
runtime-design §7a "adding one is an audited op"): whatever op did it (`set_hooks`, a JSON
patch, a whole-document replace, an undo). The detail names the code by checksum, never
by content, and holds no participant data."""


def _hooks_summary(hooks: Any) -> dict[str, Any] | None:
    if not isinstance(hooks, dict):
        return None
    source = hooks.get("source")
    raw = (source if isinstance(source, str) else "").encode("utf-8", "surrogatepass")
    handlers = hooks.get("handlers")
    redirects = hooks.get("redirects")
    parent = hooks.get("parent")
    return {
        "sourceChecksum": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "sourceBytes": len(raw),
        "events": sorted(str(k) for k in handlers) if isinstance(handlers, dict) else [],
        "redirects": sorted(str(k) for k in redirects) if isinstance(redirects, dict) else [],
        "parentOrigin": parent.get("origin") if isinstance(parent, dict) else None,
    }


def _hooks_change(
    before: Any, after: Any, txn_id: str, ops: Sequence[Invocation]
) -> dict[str, Any] | None:
    """The audit detail when a transaction changed `hooks`, else None."""
    old = before.get("hooks") if isinstance(before, dict) else None
    new = after.get("hooks") if isinstance(after, dict) else None
    if old == new:
        return None
    return {
        "transaction": txn_id,
        "kind": _kind(txn_id),
        "ops": [o.op for o in ops],
        "before": _hooks_summary(old),
        "after": _hooks_summary(new),
    }


REDIRECTS_CHANGED = "survey.redirects_changed"
"""Audit action for a transaction that changes where participants are sent after the
survey (end-of-survey plan §4.2, EN2): `settings.redirectTemplates` or any ending's
`redirect`. Piped answers in a redirect are data exports (lead decision 3), so the detail
names, per outcome, the template, its host and each param's kind (literal, a piped
question, a piped variable, a built-in); it holds no participant data."""


def _redirects_summary(body: Any) -> dict[str, Any] | None:
    settings = body.get("settings") if isinstance(body, dict) else None
    if not isinstance(settings, dict):
        return None
    templates = settings.get("redirectTemplates")
    hooks = body.get("hooks") if isinstance(body, dict) else None
    hook_templates = hooks.get("redirects") if isinstance(hooks, dict) else None
    known: dict[str, Any] = {}
    for source in (hook_templates, templates):
        if isinstance(source, dict):
            known.update({str(k): v for k, v in source.items()})
    endings = settings.get("endings")
    out: list[dict[str, Any]] = []
    for outcome, ending in endings.items() if isinstance(endings, dict) else ():
        r = ending.get("redirect") if isinstance(ending, dict) else None
        if not isinstance(r, dict):
            continue
        t = known.get(str(r.get("template")))
        url = t.get("url") if isinstance(t, dict) else None
        host = url.split("/", 3)[2] if isinstance(url, str) and url.count("/") >= 2 else None
        params = r.get("params") if isinstance(r.get("params"), dict) else {}
        out.append(
            {
                "outcome": str(outcome),
                "template": str(r.get("template")),
                "host": host,
                "mode": r.get("mode", "auto"),
                "delay": r.get("delay", 5),
                "params": {str(k): _param_kind(body, v) for k, v in params.items()},
            }
        )
    if not out and not (isinstance(templates, dict) and templates):
        return None
    return {
        "templates": sorted(str(k) for k in templates) if isinstance(templates, dict) else [],
        "redirects": sorted(out, key=lambda r: r["outcome"]),
    }


def _param_kind(body: Any, value: Any) -> str:
    """`literal`, `question`, `variable` or `builtin`: what a redirect param sends."""
    if not isinstance(value, str):
        return "literal"
    refs = re.findall(r"\$\{\s*([^}]*?)\s*\}", value)
    if not refs:
        return "literal"
    variables = (
        {v.get("id") for v in (body.get("variables") or []) if isinstance(v, dict)}
        if isinstance(body, dict)
        else set()
    )
    kinds = {
        "builtin" if r.startswith("$") else "variable" if r in variables else "question"
        for r in refs
    }
    for kind in ("question", "variable", "builtin"):
        if kind in kinds:
            return kind
    return "literal"


def _redirects_change(
    before: Any, after: Any, txn_id: str, ops: Sequence[Invocation]
) -> dict[str, Any] | None:
    """The audit detail when a transaction changed redirect templates or endings' redirects."""
    old, new = _redirects_summary(before), _redirects_summary(after)
    if old == new:
        return None
    return {
        "transaction": txn_id,
        "kind": _kind(txn_id),
        "ops": [o.op for o in ops],
        "before": old,
        "after": new,
    }


def _publish_message(diagnostics: Sequence[Diagnostic]) -> str:
    """The headline for a refused publish. A missing retention policy is named, since it
    is the one error a survey that previews fine can still have."""
    errors = _errors(diagnostics)
    if any(d.code == RETENTION_REQUIRED for d in errors):
        rest = len(errors) - 1
        more = f" ({rest} other error{'s' if rest != 1 else ''} too)" if rest else ""
        return (
            "Choose how long participant data is kept (settings.retention) "
            f"before publishing{more}."
        )
    return "Fix the errors before publishing."


def _errors(diagnostics: Sequence[Diagnostic]) -> list[Diagnostic]:
    return [d for d in diagnostics if d.severity == "error"]


def _new_txn(prefix: str = "") -> str:
    return prefix + secrets.token_hex(16)


def _kind(txn_id: str) -> str:
    if txn_id.startswith(UNDO_PREFIX):
        return "undo"
    if txn_id.startswith(REDO_PREFIX):
        return "redo"
    return "edit"


def _invocations(ops: object) -> list[Invocation]:
    if not isinstance(ops, (list, tuple)):
        raise InvalidRequest("ops must be a list")
    out: list[Invocation] = []
    for i, raw in enumerate(ops):
        try:
            out.append(raw if isinstance(raw, Invocation) else Invocation.model_validate(raw))
        except Exception as exc:
            raise Rejected(
                f"ops[{i}] is not an op invocation {{op, params}}",
                [
                    Diagnostic(
                        severity="error",
                        code="op.params",
                        message="each op is an object {op, params}",
                        pointer=f"/ops/{i}",
                    )
                ],
                failed_index=i,
            ) from exc
    return out


# -- the service ----------------------------------------------------------------------


class Builder:
    """Survey-building commands over osp-store. Thread-safe as far as the store is."""

    def __init__(
        self,
        store: Store,
        sessions: SessionService | None = None,
        *,
        bank_host_sharing: bool = True,
    ) -> None:
        self.store = store
        self.sessions = sessions or SessionService(StoreParticipantRepo(store))
        # OSP_BANK_HOST_SHARING (question-bank.md lead decision 2): whether a lab may share
        # bank items with every lab on this host; off, other labs' items are never shown.
        self.bank_host_sharing = bank_host_sharing

    def run(self, command_id: str, actor: object, **params: Any) -> Any:
        """Dispatch an app command by id (what the API, CLI and MCP call)."""
        return dispatch(self, command_id, actor, **params)

    # -- access -------------------------------------------------------------------

    @staticmethod
    def _readable_tenants(actor: Actor) -> list[str]:
        return sorted(
            tid
            for tid in actor.roles
            if can(actor, Action.SURVEY_READ, Resource(ResourceKind.SURVEY, tid))
        )

    def _locate(self, actor: Actor, survey_id: object, action: Action) -> TenantContext:
        if not isinstance(survey_id, str) or not 0 < len(survey_id) <= 36:
            raise NotFoundError("Survey not found.")
        for tid in self._readable_tenants(actor):
            ctx = TenantContext(tid, actor.user_id)
            try:
                self.store.get_survey(ctx, survey_id)
            except NotFound:
                continue
            if not can(actor, action, Resource.survey(tid, survey_id)):
                raise Forbidden("Not permitted.")
            return ctx
        raise NotFoundError("Survey not found.")

    def _draft(self, ctx: TenantContext, survey_id: str) -> Draft:
        try:
            return self.store.get_draft(ctx, survey_id)
        except NotFound as exc:
            raise NotFoundError("Survey not found.") from exc

    # -- CRUD ---------------------------------------------------------------------

    @command("survey.create", label="Create survey", action=Action.SURVEY_EDIT)
    def create_survey(
        self,
        actor: Actor,
        *,
        title: str,
        survey: Any = None,
        tenant_id: str | None = None,
    ) -> SurveyView:
        if not isinstance(title, str) or not title.strip() or len(title) > _MAX_TITLE:
            raise InvalidRequest(f"title must be 1-{_MAX_TITLE} characters")
        title = title.strip()
        tenants = [
            tid
            for tid in sorted(actor.roles)
            if can(actor, Action.SURVEY_EDIT, Resource(ResourceKind.SURVEY, tid))
        ]
        if tenant_id is None:
            if len(tenants) != 1:
                raise (
                    Forbidden("Not permitted.")
                    if not tenants
                    else InvalidRequest("tenantId is required")
                )
            tenant_id = tenants[0]
        elif tenant_id not in tenants:
            raise Forbidden("Not permitted.")
        body = default_survey(title) if survey is None else survey
        model, diagnostics = parse(body)
        if model is None:
            raise Rejected("The survey is not structurally valid.", diagnostics)
        # Rich text is validated on every write (planning/rich-text.md §3.2): a survey given
        # whole (import, JSON) may not carry text the ops would refuse either.
        bad_text = [d for d in diagnostics if d.code in TEXT_CODES]
        if bad_text:
            raise Rejected(
                "The survey holds text the model refuses (link, length, level).", bad_text
            )
        ctx = TenantContext(tenant_id, actor.user_id)
        s, draft = self.store.create_survey(ctx, title, body)
        return SurveyView(s, draft)

    @command("survey.list", label="List surveys", action=Action.SURVEY_READ)
    def list_surveys(self, actor: Actor) -> list[Survey]:
        out: list[Survey] = []
        for tid in self._readable_tenants(actor):
            out.extend(self.store.list_surveys(TenantContext(tid, actor.user_id)))
        return out

    @command("survey.get", label="Get survey draft", action=Action.SURVEY_READ)
    def get_survey(self, actor: Actor, *, survey_id: str) -> SurveyView:
        ctx = self._locate(actor, survey_id, Action.SURVEY_READ)
        return SurveyView(
            self.store.get_survey(ctx, survey_id),
            self._draft(ctx, survey_id),
            len(self.store.list_versions(ctx, survey_id)),
        )

    @command("survey.delete", label="Delete survey", action=Action.SURVEY_DELETE)
    def delete_survey(self, actor: Actor, *, survey_id: str) -> None:
        ctx = self._locate(actor, survey_id, Action.SURVEY_DELETE)
        try:
            self.store.delete_unpublished_survey(ctx, survey_id)
        except Conflict as exc:
            raise ConflictError("A published survey can't be deleted; close it instead.") from exc

    # -- edits ----------------------------------------------------------------------

    def _commit(
        self,
        ctx: TenantContext,
        survey_id: str,
        ops: list[Invocation],
        base_revision: object,
        txn_id: str,
    ) -> EditResult:
        if type(base_revision) is not int or base_revision < 0:
            raise InvalidRequest("baseRevision must be a non-negative integer")
        draft = self._draft(ctx, survey_id)
        if draft.revision != base_revision:
            raise RevisionConflictError(base_revision, draft.revision)
        res = apply_transaction(
            OpsDraft(survey=draft.body, revision=draft.revision), ops, base_revision
        )
        if res.status == "conflict":
            raise RevisionConflictError(base_revision, draft.revision)
        if res.status != "ok":
            raise Rejected("The edit was rejected.", res.diagnostics, res.failed_index)
        if not res.patch:
            return EditResult(draft.revision, [], res.diagnostics, None)
        n = len(ops)
        records = [
            OpRecord(
                ops[i].op,
                ops[i].params,
                res.inverse[n - 1 - i].model_dump(mode="json"),
            )
            for i in range(n)
        ]
        saved = self._persist(ctx, survey_id, draft, res.draft.survey, records, txn_id, ops)
        return EditResult(saved.revision, list(res.patch), list(res.diagnostics), txn_id)

    def _persist(
        self,
        ctx: TenantContext,
        survey_id: str,
        draft: Draft,
        body: Any,
        records: list[OpRecord],
        txn_id: str,
        ops: Sequence[Invocation],
    ) -> Draft:
        """Store ``body`` as the revision after ``draft`` with its op log rows, keep the
        listing title in step and audit hook and redirect changes (every edit path)."""
        try:
            saved = self.store.save_draft(
                ctx, survey_id, body, draft.revision, ops=records, txn_id=txn_id
            )
        except RevisionConflict as exc:
            raise RevisionConflictError(draft.revision, exc.current) from exc
        new_title, old_title = title_of(body), title_of(draft.body)
        if new_title and new_title != old_title:
            self.store.set_survey_title(ctx, survey_id, new_title)
        hooks_change = _hooks_change(draft.body, body, txn_id, ops)
        if hooks_change is not None:
            self.store.audit(ctx, HOOKS_CHANGED, "survey", survey_id, hooks_change)
        redirects_change = _redirects_change(draft.body, body, txn_id, ops)
        if redirects_change is not None:
            self.store.audit(ctx, REDIRECTS_CHANGED, "survey", survey_id, redirects_change)
        return saved

    def _transaction(self, ctx: TenantContext, survey_id: str, txn_id: str) -> list[OpLogEntry]:
        return [e for e in self.store.list_ops(ctx, survey_id) if e.txn_id == txn_id]

    @command("survey.apply_ops", label="Apply ops", action=Action.SURVEY_EDIT)
    def apply_ops(
        self,
        actor: Actor,
        *,
        survey_id: str,
        ops: Sequence[Invocation | dict[str, Any]],
        base_revision: int,
        transaction_id: str | None = None,
    ) -> EditResult:
        ctx = self._locate(actor, survey_id, Action.SURVEY_EDIT)
        invocations = _invocations(ops)
        if transaction_id is None:
            txn = _new_txn()
        elif isinstance(transaction_id, str) and _CLIENT_TXN.match(transaction_id):
            txn = transaction_id
            if type(base_revision) is int and base_revision >= 0:
                done = [
                    e
                    for e in self.store.list_ops(ctx, survey_id, after_revision=base_revision)
                    if e.txn_id == txn
                ]
                if done:  # a retried request: it already landed
                    return EditResult(done[0].revision, [], [], txn, replayed=True)
        else:
            raise InvalidRequest("transactionId must be 1-36 of [A-Za-z0-9_-]")
        return self._commit(ctx, survey_id, invocations, base_revision, txn)

    def _reverse(
        self,
        ctx: TenantContext,
        survey_id: str,
        transaction_id: object,
        base_revision: object,
        prefix: str,
    ) -> EditResult:
        if not isinstance(transaction_id, str) or not 0 < len(transaction_id) <= 36:
            raise NotFoundError("Transaction not found.")
        rows = self._transaction(ctx, survey_id, transaction_id)
        if not rows:
            raise NotFoundError("Transaction not found.")
        try:
            inverse = [Invocation.model_validate(r.inverse) for r in reversed(rows)]
        except Exception as exc:  # a corrupt log row: refuse, don't crash
            raise ConflictError("That transaction can't be reversed.") from exc
        return self._commit(ctx, survey_id, inverse, base_revision, _new_txn(prefix))

    @command("survey.undo", label="Undo", action=Action.SURVEY_EDIT)
    def undo(
        self, actor: Actor, *, survey_id: str, transaction_id: str, base_revision: int
    ) -> EditResult:
        ctx = self._locate(actor, survey_id, Action.SURVEY_EDIT)
        if isinstance(transaction_id, str) and transaction_id.startswith(UNDO_PREFIX):
            raise InvalidRequest("That transaction is an undo: redo it instead.")
        return self._reverse(ctx, survey_id, transaction_id, base_revision, UNDO_PREFIX)

    @command("survey.redo", label="Redo", action=Action.SURVEY_EDIT)
    def redo(
        self, actor: Actor, *, survey_id: str, transaction_id: str, base_revision: int
    ) -> EditResult:
        ctx = self._locate(actor, survey_id, Action.SURVEY_EDIT)
        if not (isinstance(transaction_id, str) and transaction_id.startswith(UNDO_PREFIX)):
            raise InvalidRequest("Only an undo transaction can be redone.")
        return self._reverse(ctx, survey_id, transaction_id, base_revision, REDO_PREFIX)

    @command("survey.history", label="Edit history", action=Action.SURVEY_READ)
    def history(self, actor: Actor, *, survey_id: str) -> list[HistoryEntry]:
        ctx = self._locate(actor, survey_id, Action.SURVEY_READ)
        out: dict[str, HistoryEntry] = {}
        for e in self.store.list_ops(ctx, survey_id):
            h = out.get(e.txn_id)
            if h is None:
                out[e.txn_id] = HistoryEntry(
                    e.txn_id, _kind(e.txn_id), e.revision, [e.op_id], e.actor, e.at
                )
            else:
                h.ops.append(e.op_id)
        return list(out.values())

    # -- publish and export -----------------------------------------------------------

    @command("survey.publish", label="Publish", action=Action.SURVEY_PUBLISH)
    def publish(
        self,
        actor: Actor,
        *,
        survey_id: str,
        base_revision: int | None = None,
        save_mode: str | None = None,
    ) -> PublishResult:
        ctx = self._locate(actor, survey_id, Action.SURVEY_PUBLISH)
        if save_mode is not None and save_mode not in SAVE_MODES:
            raise InvalidRequest(f"saveMode must be one of {', '.join(SAVE_MODES)}")
        draft = self._draft(ctx, survey_id)
        if base_revision is not None and base_revision != draft.revision:
            raise RevisionConflictError(base_revision, draft.revision)
        # Publishing also needs a retention policy (decided 16 Oct 2026, no silent default).
        diagnostics = publish_diagnostics(draft.body)
        if _errors(diagnostics) or not isinstance(draft.body, dict):
            raise Rejected(_publish_message(diagnostics), diagnostics)
        retention = _retention_policy(draft.body)

        # The plan's seed version is the published number (semantics R1-1), so compile
        # for the number this version will get; the store re-checks it atomically.
        number = 1 + max((v.number for v in self.store.list_versions(ctx, survey_id)), default=0)
        # metadata.instruments is derived from the `source` fields here, so the published
        # version names every instrument it uses (question-bank.md lead decision 1). Bundled
        # items are described from osp-instruments; lab items keep what insert captured.
        body = with_instruments({**draft.body, "version": number}, bundled_instrument)
        plan, plan_diags = compile_survey(body)
        if plan is None:
            raise Rejected("The runtime plan can't be built.", _errors(plan_diags) or plan_diags)
        theme, theme_diags = resolve_theme(self.store, ctx, draft.body)
        if theme is None:
            raise Rejected("The survey theme fails the accessibility check.", theme_diags)
        plan = embed_theme(plan, theme)
        config = runtime_config(plan, save_mode=save_mode)
        try:
            RuntimeConfig.from_json(config)
        except InvalidPayload as exc:
            raise Rejected(
                "The survey's assignment or quota settings can't run.",
                [Diagnostic(severity="error", code=exc.code, message=exc.message, pointer="")],
            ) from exc
        slug = self.store.ensure_public_slug(ctx, survey_id)

        def frozen(n: int) -> Any:
            if n != number:  # another publish landed in between: the plan is stale
                raise ConflictError("The survey was published meanwhile; publish again.")
            return body

        xform = xlsform_artefact(body)
        version = self.store.publish_version(
            ctx,
            survey_id,
            xform=xform,
            meta={
                "draftRevision": draft.revision,
                "specVersion": SPEC_VERSION,
                "planVersion": PLAN_VERSION,
                "engineVersion": ENGINE_VERSION,
                "planChecksum": plan["checksum"],
                "runtimeConfig": config,
                "slug": slug,
                "xform": "xlsform" if xform else None,  # what `versions.xform` holds
            },
            body=frozen,
        )
        self.store.set_retention(ctx, survey_id, retention)
        try:
            self.sessions.publish(ctx.tenant_id, ctx.actor, version.id, slug, plan, config)
        except (InvalidPayload, Conflict) as exc:  # not expected: config was checked above
            raise ConflictError("The version was saved but could not be made live.") from exc
        return PublishResult(
            version.id,
            version.number,
            version.checksum,
            version.published_at,
            draft.revision,
            diagnostics,
            slug,
            plan["checksum"],
            plan,
            config,
        )

    @command("survey.export_xlsform", label="Export XLSForm", action=Action.SURVEY_EXPORT)
    def export_xlsform(self, actor: Actor, *, survey_id: str) -> ExportResult:
        ctx = self._locate(actor, survey_id, Action.SURVEY_EXPORT)
        draft = self._draft(ctx, survey_id)
        content, diagnostics = export_xlsform(draft.body)
        if not content:
            raise Rejected("The survey can't be exported to XLSForm.", diagnostics)
        return ExportResult(content, f"survey-{survey_id[:8]}-r{draft.revision}.xlsx", diagnostics)

    @command("survey.export_lss", label="Export LimeSurvey (.lss)", action=Action.SURVEY_EXPORT)
    def export_lss(self, actor: Actor, *, survey_id: str) -> ExportResult:
        ctx = self._locate(actor, survey_id, Action.SURVEY_EXPORT)
        draft = self._draft(ctx, survey_id)
        content, diagnostics = export_lss(draft.body)
        if not content:
            raise Rejected("The survey can't be exported to LimeSurvey.", diagnostics)
        return ExportResult(content, f"survey-{survey_id[:8]}-r{draft.revision}.lss", diagnostics)

    @command("survey.export_qsf", label="Export Qualtrics (.qsf)", action=Action.SURVEY_EXPORT)
    def export_qsf(self, actor: Actor, *, survey_id: str) -> ExportResult:
        ctx = self._locate(actor, survey_id, Action.SURVEY_EXPORT)
        draft = self._draft(ctx, survey_id)
        content, diagnostics = export_qsf(draft.body)
        if not content:
            raise Rejected("The survey can't be exported to Qualtrics.", diagnostics)
        return ExportResult(content, f"survey-{survey_id[:8]}-r{draft.revision}.qsf", diagnostics)

    @command("survey.export_surveyjs", label="Export SurveyJS (.json)", action=Action.SURVEY_EXPORT)
    def export_surveyjs(self, actor: Actor, *, survey_id: str) -> ExportResult:
        ctx = self._locate(actor, survey_id, Action.SURVEY_EXPORT)
        draft = self._draft(ctx, survey_id)
        content, diagnostics = export_surveyjs(draft.body)
        if not content:
            raise Rejected("The survey can't be exported to SurveyJS.", diagnostics)
        return ExportResult(
            content, f"survey-{survey_id[:8]}-r{draft.revision}.surveyjs.json", diagnostics
        )
