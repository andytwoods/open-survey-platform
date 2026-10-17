"""Expression text <-> AST for the condition builder (task B7).

- ``POST /api/meta/expressions/parse``: text (+ optional survey/target) -> AST, canonical
  text and diagnostics. Parse errors carry character offsets (``start``/``end``) so the
  text view can underline them. With ``surveyId`` the expression is also type-checked
  against that draft's questions; with ``target`` too, it is checked in place (as if
  ``set_condition`` had been applied), so validator diagnostics such as ``ref.forward``
  and ``ref.unknown`` come back as well.
- ``POST /api/meta/expressions/print``: AST -> canonical text.

Neither endpoint changes anything, and neither raises on bad input: problems come back
as diagnostics. ``parse_expression`` / ``print_expression`` are plain functions so the
builder's end-to-end tests can serve the same answers without a server.
"""

from __future__ import annotations

import re
from typing import Any, Literal

import osp_expr
import osp_ops
from fastapi import APIRouter
from osp_expr.ast import EXPR_ADAPTER
from osp_ops.condition_ops import FIELDS, MAX_TEXT
from osp_ops.doc import NODE, QUESTION, QUOTA, build_index
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .common import Auth, Services, errors

ExprField = Literal["showIf", "constraint", "if", "when", "expr"]


class ExprDiagnostic(BaseModel):
    code: str
    message: str
    severity: Literal["error", "warning", "info"] = "error"
    start: int | None = Field(None, description="0-based character offset (parse errors)")
    end: int | None = Field(None, description="Exclusive end offset (parse errors)")
    path: str | None = Field(None, description="JSON pointer into the AST (type errors)")
    questionId: str | None = Field(None, description="The question or variable it is about")


class ParseExpressionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=MAX_TEXT)
    surveyId: str | None = Field(None, description="Type-check against this survey's draft")
    target: str | None = Field(
        None, description="Check in place: the question, branch, quota or variable it is for"
    )
    field: ExprField | None = Field(None, description="Default: showIf / if / when / expr")


class ParseExpressionResponse(BaseModel):
    ok: bool = Field(description="True iff the text parsed (ast is set)")
    ast: dict[str, Any] | None = Field(None, description="Expression AST (osp-expr JSON)")
    text: str | None = Field(None, description="Canonical text of the AST")
    references: list[str] = Field(default_factory=list, description="Ids the expression uses")
    diagnostics: list[ExprDiagnostic] = Field(default_factory=list)


class PrintExpressionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ast: dict[str, Any]


class PrintExpressionResponse(BaseModel):
    text: str | None = Field(None, description="Canonical text; null if the AST is invalid")
    diagnostics: list[ExprDiagnostic] = Field(default_factory=list)


# --- pure functions ---------------------------------------------------------------------

_QUOTED_ID = re.compile(r"'([A-Za-z_][A-Za-z0-9_]*)'")


def _question_id(message: str) -> str | None:
    m = _QUOTED_ID.search(message)
    return m.group(1) if m else None


def _types(survey: Any) -> dict[str, str]:
    """Question id -> semantics §2 type, from survey JSON (notes have no value)."""
    out: dict[str, str] = {}
    if not isinstance(survey, dict):
        return out
    for block in survey.get("blocks") or []:
        for page in (block or {}).get("pages") or []:
            for q in (page or {}).get("items") or []:
                if isinstance(q, dict) and isinstance(q.get("id"), str):
                    qtype = q.get("type")
                    if qtype == "matrix":
                        # semantics §2 (C2c-1): each row is a single-choice variable m_r.
                        for row in q.get("rows") or []:
                            if isinstance(row, dict) and isinstance(row.get("id"), str):
                                out[f"{q['id']}_{row['id']}"] = "single"
                    elif qtype == "slider":
                        vt = q.get("valueType")
                        out[q["id"]] = vt if vt in ("integer", "decimal") else "integer"
                    elif isinstance(qtype, str) and qtype != "note":
                        out[q["id"]] = qtype
    for v in survey.get("variables") or []:
        if isinstance(v, dict) and isinstance(v.get("id"), str):
            vtype = v.get("valueType") or ("single" if v.get("kind") == "assigned" else None)
            if isinstance(vtype, str):
                out[v["id"]] = vtype
    return out


def _field_pointer(survey: Any, target: str, field: str | None) -> str | None:
    loc = build_index(survey).get(target)
    if loc is None:
        return None
    obj: Any = survey
    for part in loc.path:
        obj = obj[part]
    if loc.kind == QUESTION:
        kind = "question"
    elif loc.kind == QUOTA:
        kind = "quota"
    else:
        kind = str(obj.get("type") if loc.kind == NODE else obj.get("kind"))
    fields = FIELDS.get(kind)
    if not fields:
        return None
    return f"{loc.pointer}/{field or fields[0]}"


def _in_place(ast: Any, survey: Any, target: str, field: str | None) -> list[ExprDiagnostic]:
    params: dict[str, Any] = {"target": target, "condition": ast}
    if field is not None:
        params["field"] = field
    res = osp_ops.run("set_condition", survey, params)
    if not res.ok:
        return [
            ExprDiagnostic(code=d.code, message=d.message, questionId=_question_id(d.message))
            for d in res.diagnostics
        ]
    ptr = _field_pointer(res.survey, target, field)
    if ptr is None:
        return []
    return [
        ExprDiagnostic(
            code=d.code,
            message=d.message,
            severity=d.severity,
            path=d.pointer[len(ptr) :] or "/",
            questionId=_question_id(d.message) if d.code.startswith("ref.") else None,
        )
        for d in res.diagnostics
        if d.pointer == ptr or d.pointer.startswith(ptr + "/")
    ]


def parse_expression(
    text: str, survey: Any = None, target: str | None = None, field: str | None = None
) -> ParseExpressionResponse:
    """Parse ``text``; with ``survey`` also type-check (in place when ``target`` is set)."""
    res = osp_expr.parse(text)
    if res.expr is None:
        return ParseExpressionResponse(
            ok=False,
            diagnostics=[
                ExprDiagnostic(code=d.code, message=d.message, start=d.start, end=d.end)
                for d in res.diagnostics
            ],
        )
    ast = EXPR_ADAPTER.dump_python(res.expr, mode="json")
    diags: list[ExprDiagnostic] = []
    if survey is not None and target:
        diags = _in_place(ast, survey, target, field)
    elif survey is not None:
        diags = [
            ExprDiagnostic(
                code=d.code,
                message=d.message,
                severity=d.severity,
                path=d.path,
                questionId=_question_id(d.message) if d.code == "unknown-question" else None,
            )
            for d in osp_expr.typecheck(res.expr, _types(survey))
        ]
    return ParseExpressionResponse(
        ok=True,
        ast=ast,
        text=osp_expr.to_text(res.expr),
        references=list(osp_expr.references(res.expr)),
        diagnostics=diags,
    )


def print_expression(ast: Any) -> PrintExpressionResponse:
    """Canonical text for an AST, or a diagnostic if it is not a valid AST."""
    try:
        expr = EXPR_ADAPTER.validate_python(ast)
    except ValidationError as err:
        msg = str(err.errors(include_url=False, include_input=False)[0]["msg"])[:300]
        return PrintExpressionResponse(
            diagnostics=[ExprDiagnostic(code="invalid-ast", message=f"not an expression: {msg}")]
        )
    except RecursionError:
        return PrintExpressionResponse(
            diagnostics=[ExprDiagnostic(code="too-deep", message="expression is nested too deeply")]
        )
    try:
        return PrintExpressionResponse(text=osp_expr.to_text(expr))
    except RecursionError:
        return PrintExpressionResponse(
            diagnostics=[ExprDiagnostic(code="too-deep", message="expression is nested too deeply")]
        )


# --- routes -----------------------------------------------------------------------------

router = APIRouter(prefix="/api/meta/expressions", tags=["meta"])


@router.post("/parse", operation_id="parseExpression", responses=errors(401, 403, 404, 422))
def parse(body: ParseExpressionRequest, auth: Auth, services: Services) -> ParseExpressionResponse:
    survey = None
    if body.surveyId is not None:
        view = services.builder.run("survey.get", auth.actor, survey_id=body.surveyId)
        survey = view.draft.body
    return parse_expression(body.text, survey, body.target, body.field)


@router.post("/print", operation_id="printExpression", responses=errors(401, 422))
def print_(body: PrintExpressionRequest, _auth: Auth) -> PrintExpressionResponse:
    return print_expression(body.ast)
