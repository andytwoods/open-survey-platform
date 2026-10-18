"""Survey drafting over ``osp_app.Builder``, for the MCP server (task AI1).

Every method returns plain JSON (dicts and lists), so the MCP layer can hand it to an AI
agent unchanged, and every failure is a :class:`DraftingError` with a readable message
(diagnostics included), never a traceback.

Guardrails
- **Draft only.** The server dispatches only the app commands in :data:`ALLOWED_COMMANDS`:
  create, list, read, edit (ops), undo, history, validate, preview. Publishing, deleting,
  exporting, results and anything that touches participant data is not reachable from here,
  whatever role the configured researcher holds (:func:`check_guardrails` proves it against
  the command registry, and ``tests/test_guardrails.py`` runs it).
- **Ops are validated.** Edits go through ``survey.apply_ops``, so osp-ops checks every
  params object and the whole survey after the transaction; a rejected transaction changes
  nothing. :data:`BLOCKED_OPS` are refused before dispatch: ``set_hooks`` (researcher code is
  authored and audited by a human) and ``apply_patch`` (raw JSON surgery is the JSON view's).
- **No participant data.** The drafting layer reads drafts and the op log only.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from osp_app import AppError, Builder, Rejected, RevisionConflictError
from osp_app.auth import Action, Actor
from osp_app.commands import COMMANDS
from osp_ops import REGISTRY, Invocation, op_catalogue
from osp_spec import Diagnostic, flatten_text, publish_diagnostics, validate
from osp_store import StoreError

from .recipes import PageSpec, QuestionSpec, add_block_ops, add_page_ops, add_question_ops

ALLOWED_COMMANDS: frozenset[str] = frozenset(
    {
        "survey.create",
        "survey.list",
        "survey.get",
        "survey.apply_ops",
        "survey.undo",
        "survey.redo",
        "survey.history",
        "survey.preview_plan",
    }
)
"""The only app commands the MCP server dispatches (AGENTS.md rule 2: by id)."""

FORBIDDEN_ACTIONS: frozenset[Action] = frozenset(
    {
        Action.SURVEY_PUBLISH,
        Action.SURVEY_DELETE,
        Action.SURVEY_EXPORT,  # includes response data
        Action.RESPONSE_DELETE,
    }
)
"""No allowed command may need one of these: that is what "draft only" means."""

BLOCKED_OPS: Mapping[str, str] = {
    "set_hooks": "researcher hooks are custom code: a human writes them in the builder",
    "apply_patch": "raw JSON patches are for the builder's JSON view; use the named ops",
}

DEFAULT_BUILDER_URL = "http://localhost:5173/surveys/{id}"
_SURVEY_ID = re.compile(r"^[A-Za-z0-9_-]{1,36}$")
MAX_OPS = 200


class DraftingError(Exception):
    """A refused request. ``message`` is safe to show; ``diagnostics`` say why."""

    def __init__(
        self, code: str, message: str, diagnostics: Sequence[Diagnostic | dict] = ()
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.diagnostics = [_dump(d) for d in diagnostics]

    def render(self) -> str:
        lines = [f"{self.code}: {self.message}"]
        for d in self.diagnostics[:25]:
            where = f" at {d['pointer']}" if d.get("pointer") else ""
            lines.append(f"- [{d['severity']}] {d['code']}{where}: {d['message']}")
        if len(self.diagnostics) > 25:
            lines.append(f"- … {len(self.diagnostics) - 25} more")
        return "\n".join(lines)


def check_guardrails() -> None:
    """Prove the allowlist is draft-only against the live command registry. Raises
    ``RuntimeError`` (at import of the server) if a listed command is unknown or needs a
    forbidden action."""
    for cid in sorted(ALLOWED_COMMANDS):
        spec = COMMANDS.get(cid)
        if spec is None:
            raise RuntimeError(f"osp-mcp allows unknown app command {cid!r}")
        if spec.action in FORBIDDEN_ACTIONS:
            raise RuntimeError(f"osp-mcp must not expose {cid!r} ({spec.action.value})")
    for op_id in BLOCKED_OPS:
        if op_id not in REGISTRY:
            raise RuntimeError(f"osp-mcp blocks unknown op {op_id!r}")


def _dump(d: Any) -> dict[str, Any]:
    return d.model_dump(mode="json") if isinstance(d, Diagnostic) else dict(d)


def _text(value: Any, lang: str | None) -> str | None:
    """A translatable text as one string (the default language, else the first); rich
    text (RT2) flattened to plain text."""
    value = flatten_text(value)
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and value:
        if lang and isinstance(value.get(lang), str):
            return value[lang]
        first = next(iter(value.values()))
        return first if isinstance(first, str) else None
    return None


def _count(diagnostics: Sequence[dict[str, Any]]) -> dict[str, int]:
    out = {"errors": 0, "warnings": 0}
    for d in diagnostics:
        if d.get("severity") == "error":
            out["errors"] += 1
        elif d.get("severity") == "warning":
            out["warnings"] += 1
    return out


@dataclass(frozen=True)
class Drafting:
    """Drafting tools for one researcher (``actor``) over one :class:`Builder`."""

    builder: Builder
    actor: Actor
    builder_url: str = DEFAULT_BUILDER_URL

    # -- dispatch -------------------------------------------------------------------

    def _run(self, command_id: str, **params: Any) -> Any:
        if command_id not in ALLOWED_COMMANDS:  # belt and braces: never reached by a tool
            raise DraftingError("mcp.not_allowed", f"{command_id!r} is not a drafting command")
        try:
            return self.builder.run(command_id, self.actor, **params)
        except Rejected as exc:
            raise DraftingError(exc.code, exc.message, exc.diagnostics) from exc
        except RevisionConflictError as exc:
            raise DraftingError(
                exc.code, f"{exc.message}; call again without baseRevision to use the latest"
            ) from exc
        except AppError as exc:
            raise DraftingError(exc.code, exc.message) from exc
        except StoreError as exc:
            raise DraftingError("store.error", f"storage refused the request: {exc}") from exc

    def _view(self, survey_id: object) -> Any:
        if not isinstance(survey_id, str) or not _SURVEY_ID.match(survey_id):
            raise DraftingError("not_found", "Survey not found.")
        return self._run("survey.get", survey_id=survey_id)

    def _link(self, survey_id: str) -> str:
        return self.builder_url.replace("{id}", survey_id)

    # -- surveys ----------------------------------------------------------------------

    def list_surveys(self) -> list[dict[str, Any]]:
        out = []
        for s in self._run("survey.list"):
            out.append(
                {
                    "surveyId": s.id,
                    "title": s.title,
                    "lab": s.tenant_id,
                    "createdAt": s.created_at.isoformat(),
                    "builderUrl": self._link(s.id),
                }
            )
        return out

    def create_survey(self, title: str, survey: Any = None) -> dict[str, Any]:
        if survey is not None and not isinstance(survey, dict):
            raise DraftingError("request.invalid", "survey must be a JSON object (osp-survey/0.1)")
        view = self._run("survey.create", title=title, survey=survey)
        return {
            "surveyId": view.survey.id,
            "title": view.survey.title,
            "revision": view.draft.revision,
            "builderUrl": self._link(view.survey.id),
            "outline": outline(view.draft.body),
        }

    def get_survey(self, survey_id: str, full: bool = False) -> dict[str, Any]:
        view = self._view(survey_id)
        body = view.draft.body
        diags = [_dump(d) for d in validate(body)]
        out: dict[str, Any] = {
            "surveyId": view.survey.id,
            "title": view.survey.title,
            "revision": view.draft.revision,
            "publishedVersions": view.published_versions,
            "builderUrl": self._link(view.survey.id),
            "problems": _count(diags),
            "outline": outline(body),
        }
        if full:
            out["survey"] = body
        return out

    # -- ops ----------------------------------------------------------------------------

    @staticmethod
    def list_ops(area: str | None = None) -> list[dict[str, Any]]:
        out = []
        for entry in op_catalogue():
            if entry["id"] in BLOCKED_OPS or (area and entry["area"] != area):
                continue
            summary = entry["description"].split(". ")[0].strip().rstrip(".")
            out.append(
                {
                    "id": entry["id"],
                    "label": entry["label"],
                    "area": entry["area"],
                    "summary": summary,
                }
            )
        return out

    @staticmethod
    def describe_op(op_id: str) -> dict[str, Any]:
        if not isinstance(op_id, str) or op_id not in REGISTRY or op_id in BLOCKED_OPS:
            known = ", ".join(sorted(o for o in REGISTRY if o not in BLOCKED_OPS))
            raise DraftingError("op.unknown", f"no drafting op {str(op_id)[:40]!r} (ops: {known})")
        for entry in op_catalogue():
            if entry["id"] == op_id:
                return entry
        raise DraftingError("op.unknown", f"no drafting op {op_id!r}")  # pragma: no cover

    def apply_ops(
        self, survey_id: str, ops: Sequence[Any], base_revision: int | None = None
    ) -> dict[str, Any]:
        if not isinstance(ops, (list, tuple)) or not ops:
            raise DraftingError("request.invalid", "ops must be a non-empty list of {op, params}")
        if len(ops) > MAX_OPS:
            raise DraftingError("request.invalid", f"at most {MAX_OPS} ops per call")
        invocations: list[Invocation] = []
        for i, raw in enumerate(ops):
            try:
                inv = raw if isinstance(raw, Invocation) else Invocation.model_validate(raw)
            except Exception as exc:
                raise DraftingError(
                    "op.params",
                    f"ops[{i}] is not an op invocation: each op is an object {{op, params}}",
                ) from exc
            reason = BLOCKED_OPS.get(inv.op)
            if reason is not None:
                raise DraftingError(
                    "mcp.not_allowed", f"ops[{i}] {inv.op!r} is not allowed: {reason}"
                )
            if inv.op not in REGISTRY:
                raise DraftingError(
                    "op.unknown", f"ops[{i}] {inv.op[:40]!r} is not an op; see list_ops"
                )
            invocations.append(inv)
        view = self._view(survey_id)
        if base_revision is None:
            base_revision = view.draft.revision
        elif type(base_revision) is not int or base_revision < 0:
            raise DraftingError("request.invalid", "baseRevision must be a non-negative integer")
        res = self._run(
            "survey.apply_ops",
            survey_id=survey_id,
            ops=invocations,
            base_revision=base_revision,
        )
        after = self._view(survey_id)
        diags = [_dump(d) for d in res.diagnostics]
        return {
            "surveyId": survey_id,
            "revision": res.revision,
            "transactionId": res.transaction_id,
            "changed": bool(res.patch),
            "diagnostics": diags,
            "outline": outline(after.draft.body),
        }

    # -- typed edits (recipes.py builds the ops; apply_ops validates them) ---------------

    def _body(self, survey_id: str) -> Any:
        body = self._view(survey_id).draft.body
        if not isinstance(body, dict):
            raise DraftingError("rejected", "the draft is not a survey object")
        return body

    def _recipe(self, survey_id: str, build: Callable[[Any], list[dict[str, Any]]]) -> dict:
        try:
            ops = build(self._body(survey_id))
        except (ValueError, TypeError, KeyError) as exc:
            raise DraftingError("request.invalid", str(exc)[:300]) from exc
        return self.apply_ops(survey_id, ops)

    def add_block(
        self,
        survey_id: str,
        block_id: str,
        title: str | None = None,
        pages: list[PageSpec] | None = None,
        in_flow: bool = True,
        flow_index: int | None = None,
    ) -> dict[str, Any]:
        return self._recipe(
            survey_id,
            lambda body: add_block_ops(
                body, block_id, title=title, pages=pages, in_flow=in_flow, flow_index=flow_index
            ),
        )

    def add_page(
        self, survey_id: str, block: str, page: PageSpec, index: int | None = None
    ) -> dict[str, Any]:
        return self._recipe(survey_id, lambda body: add_page_ops(body, block, page, index=index))

    def add_question(
        self, survey_id: str, page: str, question: QuestionSpec, index: int | None = None
    ) -> dict[str, Any]:
        return self._recipe(
            survey_id, lambda body: add_question_ops(body, page, question, index=index)
        )

    def add_choice(
        self,
        survey_id: str,
        owner: str,
        label: str | dict[str, str],
        value: int | str | None = None,
        index: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"owner": owner, "label": label}
        if value is not None:
            params["value"] = value
        if index is not None:
            params["index"] = index
        return self.apply_ops(survey_id, [{"op": "add_choice", "params": params}])

    def set_property(
        self, survey_id: str, target: str, property: str, value: Any = None, unset: bool = False
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"target": target, "property": property}
        if unset:
            params["unset"] = True
        else:
            params["value"] = value
        return self.apply_ops(survey_id, [{"op": "set_property", "params": params}])

    def set_condition(
        self, survey_id: str, target: str, condition: str | None, field: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"target": target, "condition": condition}
        if field is not None:
            params["field"] = field
        return self.apply_ops(survey_id, [{"op": "set_condition", "params": params}])

    def undo(self, survey_id: str, transaction_id: str) -> dict[str, Any]:
        view = self._view(survey_id)
        command = "survey.redo" if str(transaction_id).startswith("u:") else "survey.undo"
        res = self._run(
            command,
            survey_id=survey_id,
            transaction_id=transaction_id,
            base_revision=view.draft.revision,
        )
        after = self._view(survey_id)
        return {
            "surveyId": survey_id,
            "revision": res.revision,
            "transactionId": res.transaction_id,
            "diagnostics": [_dump(d) for d in res.diagnostics],
            "outline": outline(after.draft.body),
        }

    def history(self, survey_id: str) -> list[dict[str, Any]]:
        self._view(survey_id)
        return [
            {
                "transactionId": h.transaction_id,
                "kind": h.kind,
                "revision": h.revision,
                "ops": list(h.ops),
                "at": h.at.isoformat(),
            }
            for h in self._run("survey.history", survey_id=survey_id)
        ]

    # -- checks -------------------------------------------------------------------------

    def validate(self, survey_id: str) -> dict[str, Any]:
        view = self._view(survey_id)
        body = view.draft.body
        diags = [_dump(d) for d in validate(body)]
        seen = {(d["code"], d["pointer"], d["message"]) for d in diags}
        blockers = [
            _dump(d)
            for d in publish_diagnostics(body)
            if (d.code, d.pointer, d.message) not in seen
        ]
        return {
            "surveyId": survey_id,
            "revision": view.draft.revision,
            "valid": not any(d["severity"] == "error" for d in diags),
            "problems": _count(diags),
            "diagnostics": diags,
            "publishChecks": blockers,
            "note": (
                "Publishing is a researcher's decision in the builder; this server cannot "
                "publish. publishChecks lists what the builder would still ask for."
            ),
        }

    def preview(self, survey_id: str) -> dict[str, Any]:
        self._view(survey_id)
        res = self._run("survey.preview_plan", survey_id=survey_id)
        plan = res.get("plan")
        diags = list(res.get("diagnostics") or [])
        return {
            "surveyId": survey_id,
            "revision": res.get("revision"),
            "compiles": plan is not None,
            "planChecksum": plan.get("checksum") if isinstance(plan, dict) else None,
            "pages": len(plan.get("pages") or {}) if isinstance(plan, dict) else 0,
            "items": len(plan.get("items") or {}) if isinstance(plan, dict) else 0,
            "problems": _count(diags),
            "diagnostics": diags,
            "builderUrl": self._link(survey_id),
            "howToPreview": (
                "Open builderUrl in the browser and press Preview: the draft runs as a "
                "participant would see it (seed 'draft'; nothing is stored)."
            ),
        }


# -- outline ----------------------------------------------------------------------------


def outline(body: Any) -> dict[str, Any]:
    """A compact map of a survey: every id an op can target, with type and label.
    Never raises on a malformed document (AGENTS.md rule 3)."""
    try:
        return _outline(body)
    except Exception as exc:  # noqa: BLE001 - a bad draft gets a note, not a crash
        return {"problem": f"could not outline the survey: {type(exc).__name__}"}


def _outline(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {"problem": "the draft is not a JSON object"}
    md = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    langs = md.get("languages") if isinstance(md.get("languages"), list) else []
    lang = md.get("defaultLanguage") or (langs[0] if langs else None)
    settings = body.get("settings") if isinstance(body.get("settings"), dict) else {}
    out: dict[str, Any] = {
        "id": body.get("id"),
        "title": _text(md.get("title"), lang),
        "languages": langs,
        "consent": isinstance(body.get("consent"), dict),
        "retention": settings.get("retention"),
        "choiceLists": [
            {"id": cl.get("id"), "choices": len(cl.get("choices") or [])}
            for cl in body.get("choiceLists") or []
            if isinstance(cl, dict)
        ],
        "variables": [
            {"id": v.get("id"), "kind": v.get("kind")}
            for v in body.get("variables") or []
            if isinstance(v, dict)
        ],
        "blocks": [_block(b, lang) for b in body.get("blocks") or [] if isinstance(b, dict)],
        "flow": [_node(n) for n in body.get("flow") or [] if isinstance(n, dict)],
    }
    return out


def _block(b: dict[str, Any], lang: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {"id": b.get("id")}
    if b.get("title") is not None:
        out["title"] = b.get("title")
    out["pages"] = [_page(p, lang) for p in b.get("pages") or [] if isinstance(p, dict)]
    return out


def _page(p: dict[str, Any], lang: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {"id": p.get("id")}
    if p.get("title") is not None:
        out["title"] = _text(p.get("title"), lang)
    if p.get("showIf") is not None:
        out["showIf"] = True
    out["items"] = [_item(q, lang) for q in p.get("items") or [] if isinstance(q, dict)]
    return out


def _item(q: dict[str, Any], lang: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {"id": q.get("id"), "type": q.get("type")}
    label = _text(q.get("label"), lang)
    if label is not None:
        out["label"] = label[:120]
    if q.get("required"):
        out["required"] = True
    if q.get("choiceList") is not None:
        out["choiceList"] = q.get("choiceList")
    elif isinstance(q.get("choices"), list):
        out["choices"] = [
            {"value": c.get("value"), "label": _text(c.get("label"), lang)}
            for c in q["choices"]
            if isinstance(c, dict)
        ]
    if isinstance(q.get("rows"), list):
        out["rows"] = [r.get("id") for r in q["rows"] if isinstance(r, dict)]
    for key in ("showIf", "constraint"):
        if q.get(key) is not None:
            out[key] = True
    return out


def _node(n: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"id": n.get("id"), "type": n.get("type")}
    for key in ("block", "variables", "outcome"):
        if n.get(key) is not None:
            out[key] = n.get(key)
    if n.get("type") == "branch":
        out["if"] = True
        out["then"] = [_node(c) for c in n.get("then") or [] if isinstance(c, dict)]
        out["else"] = [_node(c) for c in n.get("else") or [] if isinstance(c, dict)]
    elif n.get("type") == "randomiser":
        out["children"] = [_node(c) for c in n.get("children") or [] if isinstance(c, dict)]
    return out
