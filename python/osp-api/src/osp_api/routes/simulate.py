"""Simulator (task M1). Thin: HTTP <-> the ``survey.simulate`` app command.

``POST /api/surveys/{id}/simulate`` (``survey.edit``: owner, editor; viewers 403, other
labs 404). Runs N simulated participants (n <= 10,000) through the TS engine on the
current draft and returns coverage (labelled ``exhaustive`` or ``sampled``), balance
checks and warnings. 503 when the simulator can't run (no Node, timeout, too large).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from osp_runtime.sim_sidecar import SimulatorError
from pydantic import BaseModel, ConfigDict, Field

from .common import Auth, Services, ServiceUnavailable, errors

router = APIRouter(prefix="/api/surveys", tags=["surveys"])


class SimulateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: int = Field(1000, ge=1, le=10_000, description="Simulated participants")
    seed: int = Field(
        1, ge=0, le=2**53 - 1, description="Seed of the simulation (same seed, same report)"
    )
    answerStrategy: Literal["uniform", "skip-optional", "first-choice", "weights"] = Field(
        "uniform",
        description="uniform: random valid answers (blank is one option for optional "
        "questions); skip-optional; first-choice; weights: per-question answer weights",
    )
    weights: dict[str, dict[str, float]] | None = Field(
        None,
        description="answerStrategy 'weights': question id -> answer -> weight. Answer is "
        "the choice code, a number or text; '' is blank; a multi answer is codes joined by ','",
    )
    quotaFull: float = Field(
        0.1, ge=0, le=1, description="Probability a quota check comes back full"
    )
    exhaustive: bool = Field(
        True, description="Also enumerate every path when the path space is small enough"
    )


class SimWarning(BaseModel):
    code: str = Field(
        description="node.unreachable | end.never_reached | branch.arm_never_taken | "
        "branch.always_same_arm | question.required_never_shown | participants.stuck | "
        "assignment.imbalanced | randomiser.imbalanced | runtime.diagnostic | coverage.sampled"
    )
    severity: Literal["error", "warning", "info"]
    target: str | None = Field(description="Node, page, question or variable id")
    message: str
    certain: bool = Field(description="True when it comes from exhaustive enumeration")


class PathSpace(BaseModel):
    exhaustive: bool
    paths: int | None = Field(description="Distinct paths, when enumerated")
    combinations: int | None = Field(description="Answer combinations enumerated")
    randomiserOrders: int
    assignmentCombinations: int
    reasons: list[str] = Field(description="Why coverage is only sampled")


class SimPath(BaseModel):
    pages: list[str]
    end: str = Field(description="<outcome>@<end node> or stuck@<page>")
    count: int


class SimNode(BaseModel):
    id: str
    type: str
    reached: int = Field(description="Simulated participants who reached it")
    covered: bool = Field(description="Reached at least once (by the coverage source)")


class SimBranch(BaseModel):
    id: str
    reached: int
    then: int
    else_: int = Field(alias="else")
    undetermined: int
    thenCovered: bool
    elseCovered: bool


class SimEnd(BaseModel):
    id: str
    outcome: str | None
    reached: int
    covered: bool


class SimPage(BaseModel):
    id: str
    reached: int
    shown: int
    covered: bool


class SimQuestion(BaseModel):
    id: str
    required: bool
    states: dict[str, int] = Field(description="answered, unanswered, irrelevant, not-reached")
    shownCovered: bool


class Balance(BaseModel):
    test: str | None = Field(
        description="levels | orders | first-position; null when too few to test"
    )
    chiSquare: float | None
    df: int | None
    pValue: float | None
    maxDeviation: float | None = Field(description="max |observed - expected| / expected")
    balanced: bool | None = Field(description="pValue >= 0.001")


class SimAssignment(Balance):
    variable: str
    reached: int
    observed: dict[str, int]
    expected: dict[str, float]


class SimRandomiser(Balance):
    id: str
    reached: int
    children: list[str]
    pick: int | None
    possibleOrders: int
    observedOrders: int
    orders: dict[str, int] = Field(description="child ids joined by ',' -> count")
    expected: float | None = Field(description="Expected count per category")


class SimQuota(BaseModel):
    node: str
    quota: str | None
    open: int
    full: int


class SimulationReport(BaseModel):
    format: Literal["osp-sim-report/1"]
    surveyId: str
    revision: int
    planChecksum: str | None
    participants: int
    seed: int | None
    answerStrategy: Any
    quotaFull: float | None
    coverage: Literal["exhaustive", "sampled"]
    pathSpace: PathSpace
    pathsSeen: int = Field(description="Distinct paths in the sample")
    topPaths: list[SimPath]
    outcomes: dict[str, int] = Field(description="End outcome (or 'stuck') -> participants")
    stuck: dict[str, int] = Field(description="Page -> participants who could not pass it")
    nodes: list[SimNode]
    branches: list[SimBranch]
    ends: list[SimEnd]
    pages: list[SimPage]
    questions: list[SimQuestion]
    assignments: list[SimAssignment]
    randomisers: list[SimRandomiser]
    quotas: list[SimQuota]
    diagnostics: dict[str, int] = Field(description="'<code> <site>' -> participants")
    warnings: list[SimWarning]


@router.post(
    "/{survey_id}/simulate",
    operation_id="simulateSurvey",
    response_model=SimulationReport,
    response_model_by_alias=True,
    responses=errors(401, 403, 404, 422, 503),
)
def simulate(
    survey_id: str, body: SimulateRequest, auth: Auth, services: Services
) -> dict[str, Any]:
    try:
        return services.builder.run(
            "survey.simulate",
            auth.actor,
            survey_id=survey_id,
            n=body.n,
            seed=body.seed,
            answer_strategy=body.answerStrategy,
            weights=body.weights,
            quota_full=body.quotaFull,
            exhaustive=body.exhaustive,
        )
    except SimulatorError as exc:
        raise ServiceUnavailable(exc.message) from exc
