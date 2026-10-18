"""Save a draft the builder edited in the browser (task CE5, planning/client-edits.md §3).

The builder applies its ops locally with ``@osp/ops`` (the TypeScript port of osp-ops) and
sends the result as an RFC 6902 patch against the revision it started from:

    survey.save_draft(survey_id, base_revision, patch, ops, transaction_id)
      -> DraftSaved(revision, diagnostics, transaction_id, replayed)

The server does not re-run the ops (they are for the audit log); it checks the *document*:

1. ``base_revision`` must be the current revision, else ``RevisionConflictError`` (409).
2. A ``transaction_id`` already logged after ``base_revision`` is a retried request that
   landed: nothing is applied again (``replayed``).
3. The patch must apply (``op.patch``) and the result must be structurally valid
   (``op.invalid_result``, ``osp_spec.parse``): else ``Rejected`` (422), nothing saved.
4. The result may not add validator errors that no op would let through, judged against
   the stored draft exactly as the op registry judges an op's output:
   - text the model refuses (``TEXT_CODES``: a ``javascript:`` link, over-long text,
     a heading level the field doesn't allow): always (``op.invalid_text``). Rich text is
     sanitised at save, whoever made the patch;
   - a duplicate id (``op.duplicate_id``), unless one of the ops is a whole-document op
     (``replace_survey``, ``apply_patch``), which the registry doesn't guard either;
   - a dangling structural reference: a flow node, choice list, quota or variable id that
     doesn't exist (``op.dangling_ref``), unless an op ran with ``force`` (a delete the
     researcher confirmed) or is a whole-document op. An unknown name inside an expression
     (``ref.unknown``) stays a diagnostic, as with ``set_condition``.
   The ``ops`` list can only relax rule 4 the way the op registry would; rules 1-3 and the
   text check do not depend on anything the client says.
5. The document is stored as the next revision with one op-log row per op (``history``
   shows them; an empty ``ops`` logs one ``apply_patch``). The first row carries the reverse
   patch as its inverse, so ``POST /undo`` with this transaction id (another client, MCP)
   reverses the whole save. Title, hooks and redirect changes are kept and audited as for
   ``survey.apply_ops``.

The answer's diagnostics are ``osp_spec.parse``'s for the saved document (what the
builder's own validator should have shown already; the server's win).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from osp_ops import REGISTRY, Invocation, PatchError, apply_patch, diff_patch
from osp_ops.registry import TEXT_CODES
from osp_spec import Diagnostic, parse
from osp_store import OpRecord

from .auth.permissions import Action, Actor
from .builder import _CLIENT_TXN, Builder, _invocations
from .commands import command
from .errors import InvalidRequest, Rejected, RevisionConflictError

MAX_OPS = 1_000
MAX_PATCH = 10_000

DUPLICATE_CODES = frozenset({"id.duplicate"})
STRUCTURAL_REF_CODES = frozenset(
    {"ref.unknown_block", "ref.unknown_choice_list", "ref.unknown_quota", "ref.unknown_variable"}
)


@dataclass(frozen=True)
class DraftSaved:
    revision: int
    diagnostics: list[Diagnostic]
    transaction_id: str | None  # None: the patch changed nothing, nothing was logged
    replayed: bool = False


def _diag(code: str, message: str, pointer: str = "") -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, pointer=pointer)


def _new_errors(
    before: Sequence[Diagnostic], after: Sequence[Diagnostic], codes: frozenset[str]
) -> list[Diagnostic]:
    """Errors in ``after`` with one of ``codes`` that ``before`` doesn't already have
    (counted by code and message, as the op registry's guard counts them)."""
    seen = Counter((d.code, d.message) for d in before if d.code in codes)
    out: list[Diagnostic] = []
    for d in after:
        if d.code not in codes or d.severity != "error":
            continue
        key = (d.code, d.message)
        if seen[key] > 0:
            seen[key] -= 1
        else:
            out.append(d)
    return out


def guarded_codes(ops: Sequence[Invocation]) -> frozenset[str]:
    """The validator codes a save may not add, given the ops the client says it ran."""
    whole = any(o.op in REGISTRY and REGISTRY[o.op].whole_document for o in ops)
    forced = any(isinstance(o.params, dict) and o.params.get("force") is True for o in ops)
    codes = set(TEXT_CODES)
    if not whole:
        codes |= DUPLICATE_CODES
        if not forced:
            codes |= STRUCTURAL_REF_CODES
    return frozenset(codes)


def check_document(before: Any, after: Any, ops: Sequence[Invocation]) -> list[Diagnostic]:
    """The saved document's diagnostics; raises ``Rejected`` if it may not be saved."""
    model, diagnostics = parse(after)
    if model is None:
        raise Rejected(
            "The saved survey would not be structurally valid.",
            [_diag("op.invalid_result", "the edit would make the survey invalid"), *diagnostics],
        )
    _, old = parse(before)
    new = _new_errors(old, diagnostics, guarded_codes(ops))
    if new:
        first = new[0].code
        if first in TEXT_CODES:
            code, message = "op.invalid_text", "The survey would hold text the model refuses."
        elif first in DUPLICATE_CODES:
            code, message = "op.duplicate_id", "The survey would have a duplicate id."
        else:
            code, message = "op.dangling_ref", "The survey would refer to something that's gone."
        raise Rejected(message, [_diag(code, f"the edit would add: {new[0].message}"), *new])
    return list(diagnostics)


def _audit_ops(ops: object) -> list[Invocation]:
    if isinstance(ops, (list, tuple)) and len(ops) > MAX_OPS:
        raise InvalidRequest(f"ops must be a list of at most {MAX_OPS}")
    out = _invocations(ops)
    for i, o in enumerate(out):
        if o.op not in REGISTRY:
            raise Rejected(
                "The save names an op that doesn't exist.",
                [_diag("op.unknown", f"no op with id {o.op[:60]!r}", f"/ops/{i}")],
                failed_index=i,
            )
    return out


@command("survey.save_draft", label="Save draft", action=Action.SURVEY_EDIT)
def save_draft(
    builder: Builder,
    actor: Actor,
    *,
    survey_id: str,
    base_revision: int,
    patch: Any,
    ops: Sequence[Invocation | dict[str, Any]] = (),
    transaction_id: str,
) -> DraftSaved:
    ctx = builder._locate(actor, survey_id, Action.SURVEY_EDIT)
    if type(base_revision) is not int or base_revision < 0:
        raise InvalidRequest("baseRevision must be a non-negative integer")
    if not (isinstance(transaction_id, str) and _CLIENT_TXN.match(transaction_id)):
        raise InvalidRequest("transactionId must be 1-36 of [A-Za-z0-9_-]")
    if not isinstance(patch, list) or len(patch) > MAX_PATCH:
        raise InvalidRequest(f"patch must be a list of at most {MAX_PATCH} operations")
    invocations = _audit_ops(ops)

    done = [
        e
        for e in builder.store.list_ops(ctx, survey_id, after_revision=base_revision)
        if e.txn_id == transaction_id
    ]
    if done:  # a retried request: it already landed
        return DraftSaved(done[0].revision, [], transaction_id, replayed=True)

    draft = builder._draft(ctx, survey_id)
    if draft.revision != base_revision:
        raise RevisionConflictError(base_revision, draft.revision)
    try:
        body = apply_patch(draft.body, patch)
    except PatchError as exc:
        raise Rejected(
            "The change does not apply to the saved draft.", [_diag("op.patch", str(exc)[:300])]
        ) from None
    diagnostics = check_document(draft.body, body, invocations)
    reverse = diff_patch(body, draft.body)
    if not reverse:
        return DraftSaved(draft.revision, diagnostics, None)

    logged = invocations or [Invocation(op="apply_patch", params={"patch": patch})]
    records = [
        OpRecord(
            o.op,
            o.params,
            {"op": "apply_patch", "params": {"patch": reverse if i == 0 else []}},
        )
        for i, o in enumerate(logged)
    ]
    saved = builder._persist(ctx, survey_id, draft, body, records, transaction_id, logged)
    return DraftSaved(saved.revision, diagnostics, transaction_id)
