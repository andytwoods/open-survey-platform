"""Preview plan (task B11): compile the current draft into a runtime plan for the builder's
preview and debugger, without publishing anything.

The plan's seed version is ``"draft"`` (semantics R1-1: an unpublished survey seeds as
``draft``), so a preview never shares randomisation with a published version. The theme is
resolved as publish would (survey theme, else the lab default, else the preset) so the
preview looks like the participant page; a theme that fails the guard is left out and
reported. ``conditions`` holds every display/branch condition of the plan as text
(``osp_expr.to_text``), keyed by the engine's diagnostic site (``items.<id>.showIf``,
``pages.<id>.showIf``, ``flow.<id>.if``, ``quotas.<id>.when``, ``variables.<id>.expr``), so
the debugger can explain a decision without a second printer in the browser.

Needs ``survey.edit`` (owner, editor). Never raises on a bad draft: errors come back as
diagnostics with ``plan: null``.
"""

from __future__ import annotations

from typing import Any

from osp_expr import to_text
from osp_expr.ast import EXPR_ADAPTER
from osp_runtime.plan import compile_survey, embed_theme
from osp_spec import Diagnostic

from .auth.permissions import Action, Actor
from .builder import Builder
from .commands import command
from .publish_theme import resolve_theme


def _text(ast: Any) -> str | None:
    try:
        return to_text(EXPR_ADAPTER.validate_python(ast))
    except Exception:  # never crash on input (AGENTS.md rule 3)
        return None


def condition_texts(plan: dict[str, Any]) -> dict[str, str]:
    """Every expression in the plan as text, by engine site."""
    out: dict[str, str] = {}

    def put(site: str, ast: Any) -> None:
        if ast is not None and (t := _text(ast)) is not None:
            out[site] = t

    for iid, item in (plan.get("items") or {}).items():
        put(f"items.{iid}.showIf", item.get("showIf"))
        put(f"items.{iid}.constraint", item.get("constraint"))
    for pid, page in (plan.get("pages") or {}).items():
        put(f"pages.{pid}.showIf", page.get("showIf"))
    for qid, quota in (plan.get("quotas") or {}).items():
        put(f"quotas.{qid}.when", quota.get("when"))
    for vid, var in (plan.get("variables") or {}).items():
        put(f"variables.{vid}.expr", var.get("expr"))

    def walk(nodes: list[Any]) -> None:
        for n in nodes:
            if not isinstance(n, dict):
                continue
            if n.get("type") == "branch":
                put(f"flow.{n.get('id')}.if", n.get("if"))
                walk(n.get("then") or [])
                walk(n.get("else") or [])
            elif n.get("type") == "randomiser":
                walk(n.get("children") or [])

    walk(plan.get("flow") or [])
    return out


@command("survey.preview_plan", label="Preview plan", action=Action.SURVEY_EDIT)
def preview_plan(builder: Builder, actor: Actor, *, survey_id: str) -> dict[str, Any]:
    ctx = builder._locate(actor, survey_id, Action.SURVEY_EDIT)
    draft = builder._draft(ctx, survey_id)
    body = draft.body
    if isinstance(body, dict):
        body = {**body, "version": None}  # seedVersion "draft" (R1-1), whatever the draft says
    plan, diagnostics = compile_survey(body)
    found: list[Diagnostic] = list(diagnostics)
    texts: dict[str, str] = {}
    if plan is not None:
        theme, theme_diags = resolve_theme(builder.store, ctx, body)
        found.extend(theme_diags)
        if theme is not None:
            plan = embed_theme(plan, theme)
        texts = condition_texts(plan)
    return {
        "surveyId": survey_id,
        "revision": draft.revision,
        "plan": plan,
        "conditions": texts,
        "diagnostics": [d.model_dump(mode="json") for d in found],
    }
