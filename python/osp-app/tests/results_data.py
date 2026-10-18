"""Shared test data for the results aggregation (task V1): a survey with every question
type and a few hand-made responses whose expected aggregates are worked out by hand in
``test_results.py``. Fake data only (AGENTS.md rule 7)."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

from osp_store import Store, TenantContext
from osp_store import schema as t
from sqlalchemy import insert


def _bi(en: str, cy: str) -> dict[str, str]:
    return {"en": en, "cy": cy}


LIKERT = [{"value": i, "label": _bi(f"L{i}", f"C{i}")} for i in range(1, 6)]

SURVEY: dict[str, Any] = {
    "specVersion": "osp-survey/0.1",
    "id": "results_all",
    "metadata": {"title": "Results fixture", "languages": ["en", "cy"]},
    "choiceLists": [
        {
            "id": "fruit",
            "choices": [
                {"value": "apple", "label": _bi("Apple", "Afal")},
                {"value": "banana", "label": _bi("Banana", "Banana cy")},
                {"value": "cherry", "label": _bi("Cherry", "Ceiriosen")},
            ],
        },
        {"id": "likert", "choices": LIKERT},
    ],
    "variables": [{"kind": "assigned", "id": "arm", "levels": ["a", "b"]}],
    "blocks": [
        {
            "id": "b1",
            "pages": [
                {
                    "id": "p1",
                    "items": [
                        {"type": "note", "id": "n1", "label": "Hello"},
                        {
                            "type": "single",
                            "id": "fruit",
                            "label": _bi("Fruit?", "Ffrwyth?"),
                            "choiceList": "fruit",
                        },
                        {
                            "type": "single",
                            "id": "sat",
                            "label": "Satisfied?",
                            "choiceList": "likert",
                        },
                        {
                            "type": "multi",
                            "id": "col",
                            "label": "Colours?",
                            "choices": [
                                {"value": "red", "label": "Red"},
                                {"value": "green", "label": "Green"},
                                {"value": "blue", "label": "Blue"},
                            ],
                        },
                        {"type": "integer", "id": "age", "label": "Age?"},
                        {"type": "decimal", "id": "price", "label": "Price?"},
                        {"type": "slider", "id": "sl", "label": "Slide", "min": 0, "max": 10},
                        {"type": "slider", "id": "big", "label": "Big slide"},
                        {"type": "date", "id": "when", "label": "When?"},
                        {"type": "text", "id": "why", "label": "Why?"},
                        {
                            "type": "matrix",
                            "id": "grid",
                            "label": "Grid",
                            "rows": [
                                {"id": "r1", "label": "Row one"},
                                {"id": "r2", "label": "Row two"},
                            ],
                            "choiceList": "likert",
                        },
                    ],
                }
            ],
        }
    ],
    "flow": [
        {"type": "assign", "id": "as1", "variables": ["arm"]},
        {"type": "block", "id": "fb1", "block": "b1"},
    ],
}


def A(v: Any) -> dict[str, Any]:  # noqa: N802
    return {"state": "answered", "value": v}


U = {"state": "unanswered", "value": None}
IRR = {"state": "irrelevant", "value": None}
NR = {"state": "not-reached", "value": None}

# r5 has no entry for grid_r1 / grid_r2 (unrecorded) and some invalid values.
RESPONSES: list[tuple[dict[str, Any], dict[str, Any]]] = [
    (
        {"arm": "a"},
        {
            "fruit": A("apple"), "sat": A(5), "col": A(["red", "green"]), "age": A(20),
            "price": A("2.50"), "sl": A(3), "big": A(10), "when": A("2026-01-15"),
            "why": A("sunny"), "grid_r1": A(1), "grid_r2": A(2),
        },
    ),
    (
        {"arm": "a"},
        {
            "fruit": A("banana"), "sat": A(4), "col": A(["red"]), "age": A(30),
            "price": A("3.00"), "sl": A(3), "big": A(55), "when": A("2026-01-20"),
            "why": A("rain!"), "grid_r1": A(2), "grid_r2": U,
        },
    ),
    (
        {"arm": "b"},
        {
            "fruit": A("apple"), "sat": A(1), "col": A([]), "age": A(25), "price": U,
            "sl": A(7), "big": A(99), "when": A("2026-03-01"), "why": U,
            "grid_r1": A(5), "grid_r2": A(5),
        },
    ),
    (
        {"arm": "b"},
        {
            "fruit": U, "sat": U, "col": U, "age": IRR, "price": IRR, "sl": NR, "big": NR,
            "when": NR, "why": NR, "grid_r1": NR, "grid_r2": NR,
        },
    ),
    (
        {},
        {
            "fruit": A("durian"), "sat": A(2), "col": A(["blue", "green"]), "age": A(40),
            "price": A("abc"), "sl": A(3.5), "big": U, "when": A("2026-13-01"),
            "why": A("ok"),
        },
    ),
]  # fmt: skip

T0 = datetime(2026, 1, 1, 12, tzinfo=UTC)


def add_response(
    store: Store,
    ctx: TenantContext,
    version_id: str,
    answers: dict[str, Any],
    *,
    assigned: dict[str, Any] | None = None,
    at: datetime | None = None,
    record: dict[str, Any] | None = None,
) -> str:
    """One response row; with ``record`` also its full engine record (as the participant
    runtime stores it: ``{"record": ..., "server": ...}``) and its ``end`` as the row's
    outcome column (as the runtime's submit writes it)."""
    end = record.get("end") if record is not None else None
    r = store.record_response(
        ctx,
        version_id,
        answers,
        session_seed=1,
        assigned_conditions=assigned or {},
        submitted_at=at,
        outcome=end if isinstance(end, str) else None,
    )
    if record is not None:
        full = {"record": {"answers": answers, **record}, "server": {}}
        blob, kid = store._enc(full, "response_records", "record", r.id)
        with store.engine.begin() as conn:
            conn.execute(
                insert(t.response_records).values(
                    id=r.id, tenant_id=ctx.tenant_id, record_ct=blob, record_key_id=kid
                )
            )
    return r.id


def publish(store: Store, ctx: TenantContext, survey_id: str, body: dict[str, Any]) -> Any:
    return store.publish_version(ctx, survey_id, b"", body=copy.deepcopy(body))


def seed(store: Store, ctx: TenantContext, version_id: str) -> list[str]:
    """The five fixture responses, one day apart from T0."""
    return [
        add_response(store, ctx, version_id, answers, assigned=assigned, at=T0 + timedelta(days=i))
        for i, (assigned, answers) in enumerate(RESPONSES)
    ]
