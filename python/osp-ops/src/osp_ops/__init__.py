"""osp-ops (layer L2): the survey edit op registry. Every survey edit is an op.

    from osp_ops import run, apply_transaction, Draft
    res = run("set_property", survey, {"target": "q12", "property": "required", "value": True})
    res.survey, res.inverse, res.patch, res.diagnostics

Pure: no I/O, no clock, no randomness. See README.md.
"""

# Area modules register their ops on import (one module per area, AGENTS.md §5).
from . import (  # noqa: F401
    choice_list_ops,
    choice_ops,
    condition_ops,
    consent_ops,
    custom_property_ops,
    duplicate_ops,
    ending_ops,
    flow_ops,
    hooks_ops,
    matrix_row_ops,
    metadata_ops,
    page_ops,
    property_ops,
    question_ops,
    question_type_ops,
    redirect_ops,
    survey_ops,
    theme_ops,
    variable_ops,
)
from .patch import PatchError
from .patch import apply as apply_patch
from .patch import diff as diff_patch
from .registry import OP_CODES, REGISTRY, Invocation, OpResult, OpSpec, enabled, invoke, run
from .schema import op_catalogue, openapi_components
from .transaction import Draft, TransactionResult, apply_transaction

__all__ = [
    "OP_CODES",
    "REGISTRY",
    "Draft",
    "Invocation",
    "OpResult",
    "OpSpec",
    "PatchError",
    "TransactionResult",
    "apply_patch",
    "apply_transaction",
    "diff_patch",
    "enabled",
    "invoke",
    "op_catalogue",
    "openapi_components",
    "run",
]
