"""Transactions: a list of ops applied all-or-nothing against a revision.

A drag, a bulk paste or a "add block + place it in the flow" gesture is one transaction
(builder-design.md §4). It yields one inverse transaction (the ops' inverses in reverse
order), so undo is `apply_transaction(draft, result.inverse, ...)` and its own inverse
is the redo. A stale `base_revision` is a conflict (HTTP 409 in osp-api).

osp-ops keeps no history and no clock: the caller stores drafts, revisions and
inverse transactions (osp-app / osp-store).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from osp_spec import Diagnostic, parse
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from .registry import Invocation, _execute, diag

type Json = Any
MAX_OPS = 1_000


class Draft(BaseModel):
    """A survey document (plain JSON) at a revision."""

    model_config = ConfigDict(frozen=True)

    survey: Json
    revision: int = 0


class TransactionResult(BaseModel):
    """`status`: ok (applied), rejected (nothing applied; `failed_index` says which op)
    or conflict (stale base revision; nothing applied). `patch` is RFC 6902 from the old
    survey to the new one; `inverse` undoes the whole transaction."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok", "rejected", "conflict"]
    draft: Draft
    inverse: list[Invocation] = Field(default_factory=list)
    patch: list[dict[str, JsonValue]] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    failed_index: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def apply_transaction(
    draft: Draft, ops: Sequence[Invocation | dict[str, Any]] | Any, base_revision: int
) -> TransactionResult:
    """Apply `ops` in order to `draft`, all or nothing. Never raises.

    On success the revision goes up by one if anything changed (an empty or no-op
    transaction keeps the revision). Diagnostics are the validator's for the result.
    """
    try:
        return _apply(draft, ops, base_revision)
    except Exception as exc:  # never crash on input (AGENTS.md rule 3)
        return TransactionResult(
            status="rejected",
            draft=draft,
            diagnostics=[diag("op.internal", f"transaction failed: {type(exc).__name__}")],
        )


def _apply(draft: Draft, ops: Any, base_revision: Any) -> TransactionResult:
    if type(base_revision) is not int or base_revision != draft.revision:
        return TransactionResult(
            status="conflict",
            draft=draft,
            diagnostics=[
                diag(
                    "op.conflict",
                    f"base revision {str(base_revision)[:20]} is not the current revision "
                    f"{draft.revision}; refetch and replay",
                )
            ],
        )
    if not isinstance(ops, (list, tuple)) or len(ops) > MAX_OPS:
        return _reject(draft, None, [diag("op.params", f"ops must be a list of <= {MAX_OPS}")])

    survey = draft.survey
    parsed = parse(survey)
    inverses: list[Invocation] = []
    patch: list[dict[str, JsonValue]] = []
    diagnostics = parsed[1]
    for i, inv in enumerate(ops):
        if isinstance(inv, Invocation):
            op_id, params = inv.op, inv.params
        elif isinstance(inv, dict):
            op_id, params = inv.get("op"), inv.get("params", {})
        else:
            return _reject(draft, i, [diag("op.params", "each op is an object {op, params}")])
        res = _execute(op_id, survey, params, parsed=parsed)
        if not res.ok:
            return _reject(draft, i, res.diagnostics)
        assert res.inverse is not None
        inverses.append(res.inverse)
        patch.extend(res.patch)
        survey = res.survey
        diagnostics = res.diagnostics
        parsed = (_PARSED_OK, diagnostics)  # the op just validated its output
    revision = draft.revision + 1 if patch else draft.revision
    return TransactionResult(
        status="ok",
        draft=Draft(survey=survey, revision=revision),
        inverse=list(reversed(inverses)),
        patch=patch,
        diagnostics=diagnostics,
    )


def _reject(draft: Draft, index: int | None, diagnostics: list[Diagnostic]) -> TransactionResult:
    return TransactionResult(
        status="rejected", draft=draft, diagnostics=diagnostics, failed_index=index
    )


class _ParsedOk:
    """Stands in for the parsed `Survey`: only its not-None-ness is used."""


_PARSED_OK: Any = _ParsedOk()
