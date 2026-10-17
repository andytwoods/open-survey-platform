"""Simulate a survey draft (task M1): compile the draft to a runtime plan, run N simulated
participants through the TS engine (``osp_runtime.sim_sidecar``, a Node sidecar) and turn
the result into a coverage and balance report (``osp_qa.build_report``).

Needs ``survey.edit`` (owner, editor): it is a design-time check of the draft. No
participant data is read or written. Same draft + options ⇒ same report (``seed``
defaults to 1).

Registered on import (``osp_app/__init__.py``); dispatched through ``Builder.run``.
``SimulatorError`` with a ``sim.*`` code (node missing, timeout, too large) is left to the
shell, which answers 503; bad options are ``InvalidRequest``.
"""

from __future__ import annotations

from typing import Any

from osp_qa import build_report
from osp_runtime.plan import compile_survey
from osp_runtime.sim_sidecar import MAX_PARTICIPANTS, SimulatorError, simulate_plan
from osp_spec import Diagnostic

from .auth.permissions import Action, Actor
from .builder import Builder
from .commands import command
from .errors import InvalidRequest, Rejected

STRATEGIES = ("uniform", "skip-optional", "first-choice", "weights")


def _options(
    n: object,
    seed: object,
    strategy: object,
    weights: object,
    quota_full: object,
    exhaustive: object,
) -> dict[str, Any]:
    if type(n) is not int or not 1 <= n <= MAX_PARTICIPANTS:
        raise InvalidRequest(f"n must be an integer from 1 to {MAX_PARTICIPANTS}")
    if type(seed) is not int or not 0 <= seed <= 2**53 - 1:
        raise InvalidRequest("seed must be an integer from 0 to 2^53 - 1")
    if strategy not in STRATEGIES:
        raise InvalidRequest(f"answerStrategy must be one of {', '.join(STRATEGIES)}")
    if not isinstance(quota_full, int | float) or isinstance(quota_full, bool):
        raise InvalidRequest("quotaFull must be a number from 0 to 1")
    if not 0 <= quota_full <= 1:
        raise InvalidRequest("quotaFull must be a number from 0 to 1")
    answer_strategy: Any = strategy
    if strategy == "weights":
        ok = isinstance(weights, dict) and all(
            isinstance(k, str)
            and isinstance(w, dict)
            and all(
                isinstance(a, str)
                and isinstance(x, int | float)
                and not isinstance(x, bool)
                and x >= 0
                for a, x in w.items()
            )
            for k, w in weights.items()
        )
        if not ok:
            raise InvalidRequest("weights must map question id -> answer -> weight (>= 0)")
        answer_strategy = {"weights": weights}
    elif weights is not None:
        raise InvalidRequest("weights need answerStrategy 'weights'")
    return {
        "n": n,
        "seed": seed,
        "answerStrategy": answer_strategy,
        "quotaFull": float(quota_full),
        "exhaustive": exhaustive is not False,
    }


@command("survey.simulate", label="Simulate participants", action=Action.SURVEY_EDIT)
def simulate_survey(
    builder: Builder,
    actor: Actor,
    *,
    survey_id: str,
    n: int = 1000,
    seed: int = 1,
    answer_strategy: str = "uniform",
    weights: dict[str, dict[str, float]] | None = None,
    quota_full: float = 0.1,
    exhaustive: bool = True,
) -> dict[str, Any]:
    ctx = builder._locate(actor, survey_id, Action.SURVEY_EDIT)
    options = _options(n, seed, answer_strategy, weights, quota_full, exhaustive)
    draft = builder._draft(ctx, survey_id)
    plan, diagnostics = compile_survey(draft.body)
    if plan is None:
        errors = [d for d in diagnostics if isinstance(d, Diagnostic) and d.severity == "error"]
        raise Rejected("Fix the errors before simulating.", errors or diagnostics)
    try:
        result = simulate_plan(plan, options)
    except SimulatorError as exc:
        if exc.code.startswith("options."):
            raise InvalidRequest(exc.message) from exc
        if exc.code.startswith("plan."):
            raise Rejected(
                "The runtime plan can't be simulated.",
                [Diagnostic(severity="error", code=exc.code, message=exc.message, pointer="")],
            ) from exc
        raise
    report = build_report(plan, result)
    return {"surveyId": survey_id, "revision": draft.revision, **report}
