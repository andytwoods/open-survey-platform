"""The op registry: every survey edit is a named op (AGENTS.md golden rule 2).

An op has an `id`, a pydantic params model, `enabled(survey, params)` and
`run(survey, params) -> OpResult(survey', inverse, patch, diagnostics)`.

Contract (enforced here, once, for every op):
- Ops are pure. The input survey (plain JSON) is deep-copied and never mutated.
- The input must parse as an `osp-spec` `Survey` (structurally valid) and so must the
  output; semantic problems (forward references, missing translations ...) are allowed
  in a draft and come back as `diagnostics` (the full validator output for survey').
- An op may not introduce a new duplicate id: ops address objects by id.
- Delete ops may not introduce a dangling reference unless `cascade` or `force` is set
  (see README.md, "Dangling references").
- Nothing raises. Bad params, a bad survey or a bug become `op.*` diagnostics.

`enabled` is a dry run of `run`, so the two can never disagree.
"""

from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from osp_spec import Diagnostic, Survey, parse
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from . import patch as jp

type Json = Any

# Codes osp-ops reports itself (all errors). Validator codes come from osp_spec.CODES.
OP_CODES: dict[str, str] = {
    "op.unknown": "no op with this id",
    "op.params": "params do not match the op's params schema",
    "op.invalid_survey": "the input survey is not structurally valid",
    "op.not_found": "the target id does not exist (or is the wrong kind of object)",
    "op.not_allowed": "the edit is not allowed in this state",
    "op.duplicate_id": "the edit would create a duplicate id",
    "op.dangling_ref": "the delete would leave references to deleted objects",
    "op.cascade_blocked": "cascade cannot repair a required expression",
    "op.invalid_result": "the edit would make the survey structurally invalid",
    "op.expr_syntax": "condition text does not parse",
    "op.patch": "the JSON Patch is malformed or does not apply",
    "op.conflict": "baseRevision is stale (HTTP 409)",
    "op.internal": "an op failed unexpectedly (a bug; never expected)",
}

# Validator codes an op may not newly introduce: ids address objects, references must
# resolve. Compared as (code, message) multisets before vs after.
_DUPLICATE_CODES = frozenset({"id.duplicate"})
_DANGLING_CODES = frozenset(
    {
        "ref.unknown",
        "ref.unknown_block",
        "ref.unknown_choice_list",
        "ref.unknown_quota",
        "ref.unknown_variable",
    }
)


def diag(code: str, message: str, pointer: str = "") -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, pointer=pointer)


class OpError(Exception):
    """Raised inside an op's `run`; the registry turns it into diagnostics."""

    def __init__(self, code: str, message: str, pointer: str = "", *more: Diagnostic) -> None:
        super().__init__(message)
        self.diagnostics = [diag(code, message, pointer), *more]


class Params(BaseModel):
    """Base for every op's params model: strict JSON types, no unknown keys."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Invocation(BaseModel):
    """One op call: what the UI, CLI and MCP send, and what an inverse is."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op: str
    params: dict[str, JsonValue] = Field(default_factory=dict)


class OpResult(BaseModel):
    """`survey` is survey' when `ok`, else the unchanged input. `inverse` undoes the op
    exactly (survey' -> survey). `patch` is RFC 6902 from survey to survey'."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    survey: Json = None
    inverse: Invocation | None = None
    patch: list[dict[str, JsonValue]] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


# Returned by an op's `run` when its inverse is best expressed as the reverse patch
# (cascading deletes, which touch many objects).
REVERSE_PATCH = Invocation(op="apply_patch", params={"patch": []})


@dataclass
class Ctx:
    """What an op's `run` sees. `doc` is a private deep copy it may mutate (or replace)."""

    doc: Json
    before: Json
    check_dangling: bool = False  # set by deletes unless `force`
    _index: dict[str, Any] | None = field(default=None, repr=False)

    def index(self) -> dict[str, Any]:
        """Id -> location in `doc` (recomputed after `touch()`)."""
        from .doc import build_index  # local: doc imports registry

        if self._index is None:
            self._index = build_index(self.doc)
        return self._index

    def touch(self) -> None:
        self._index = None


type RunFn = Callable[[Ctx, Any], Invocation]


@dataclass(frozen=True)
class OpSpec:
    id: str
    label: str
    area: str
    params: type[Params]
    run: RunFn
    whole_document: bool = False  # replace_survey / apply_patch: skip the id/ref guards
    description: str = ""


REGISTRY: dict[str, OpSpec] = {}


def op(
    op_id: str, params: type[Params], *, label: str, area: str, whole_document: bool = False
) -> Callable[[RunFn], RunFn]:
    """Register `run` as op `op_id`. Each area module calls this at import time."""

    def deco(fn: RunFn) -> RunFn:
        if op_id in REGISTRY:
            raise RuntimeError(f"op {op_id!r} registered twice")
        REGISTRY[op_id] = OpSpec(
            id=op_id,
            label=label,
            area=area,
            params=params,
            run=fn,
            whole_document=whole_document,
            description=(fn.__doc__ or "").strip(),
        )
        return fn

    return deco


# --- running ops ----------------------------------------------------------------------


def run(op_id: Any, survey: Any, params: Any = None) -> OpResult:
    """Run one op. Never raises."""
    return _execute(op_id, survey, params, parsed=None)


def enabled(op_id: Any, survey: Any, params: Any = None) -> Literal[True] | str:
    """True if the op would succeed, else the reason (first diagnostic's message)."""
    res = run(op_id, survey, params)
    if res.ok:
        return True
    first = res.diagnostics[0] if res.diagnostics else None
    return first.message if first else "not enabled"


def invoke(inv: Invocation | Mapping[str, Any], survey: Any) -> OpResult:
    """Run an `Invocation` (or a `{"op", "params"}` mapping)."""
    if isinstance(inv, Invocation):
        return run(inv.op, survey, inv.params)
    if isinstance(inv, Mapping):
        return run(inv.get("op"), survey, inv.get("params", {}))
    return _fail(survey, [diag("op.params", "an invocation is an object {op, params}")])


def _fail(survey: Any, diagnostics: list[Diagnostic]) -> OpResult:
    return OpResult(ok=False, survey=survey, diagnostics=diagnostics)


def _execute(
    op_id: Any,
    survey: Any,
    params: Any,
    *,
    parsed: tuple[Survey | None, list[Diagnostic]] | None,
) -> OpResult:
    try:
        return _execute_unguarded(op_id, survey, params, parsed=parsed)
    except Exception as exc:  # never crash on input (AGENTS.md rule 3)
        msg = f"op {str(op_id)[:60]!r} failed: {type(exc).__name__}"
        return _fail(survey, [diag("op.internal", msg)])


def _execute_unguarded(
    op_id: Any,
    survey: Any,
    params: Any,
    *,
    parsed: tuple[Survey | None, list[Diagnostic]] | None,
) -> OpResult:
    if isinstance(survey, Survey):
        survey = survey.model_dump(mode="json", by_alias=True, exclude_unset=True)
    spec = REGISTRY.get(op_id) if isinstance(op_id, str) else None
    if spec is None:
        return _fail(survey, [diag("op.unknown", f"no op with id {str(op_id)[:60]!r}")])
    if params is None:
        params = {}
    if not isinstance(params, Mapping):
        return _fail(survey, [diag("op.params", "params must be an object")])
    try:
        p = spec.params.model_validate(dict(params))
    except ValidationError as err:
        return _fail(survey, _param_diagnostics(err))

    before_parsed = parsed if parsed is not None else parse(survey)
    if before_parsed[0] is None and not spec.whole_document:
        return _fail(
            survey,
            [diag("op.invalid_survey", "the survey is not structurally valid"), *before_parsed[1]],
        )

    ctx = Ctx(doc=copy.deepcopy(survey), before=survey)
    try:
        inverse = spec.run(ctx, p)
    except OpError as e:
        return _fail(survey, e.diagnostics)

    after_model, after = parse(ctx.doc)
    if after_model is None:
        return _fail(
            survey,
            [diag("op.invalid_result", "the edit would make the survey invalid"), *after],
        )

    if not spec.whole_document:
        guarded = set(_DUPLICATE_CODES)
        if ctx.check_dangling:
            guarded |= _DANGLING_CODES
        new = _new_errors(before_parsed[1], after, guarded)
        if new:
            code = "op.duplicate_id" if new[0].code in _DUPLICATE_CODES else "op.dangling_ref"
            return _fail(survey, [diag(code, f"the edit would add: {new[0].message}"), *new])

    if inverse is REVERSE_PATCH:
        inverse = Invocation(op="apply_patch", params={"patch": jp.diff(ctx.doc, survey)})
    return OpResult(
        ok=True,
        survey=ctx.doc,
        inverse=inverse,
        patch=jp.diff(survey, ctx.doc),
        diagnostics=after,
    )


def _new_errors(
    before: list[Diagnostic], after: list[Diagnostic], codes: set[str]
) -> list[Diagnostic]:
    seen = Counter((d.code, d.message) for d in before if d.code in codes)
    out: list[Diagnostic] = []
    for d in after:
        if d.code not in codes:
            continue
        key = (d.code, d.message)
        if seen[key] > 0:
            seen[key] -= 1
        else:
            out.append(d)
    return out


def _param_diagnostics(err: ValidationError) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    for e in err.errors(include_url=False, include_input=False)[:20]:
        parts = [p for p in e["loc"] if isinstance(p, (str, int))]
        out.append(diag("op.params", str(e["msg"])[:300], jp.to_pointer(parts)))
    return out or [diag("op.params", "invalid params")]
