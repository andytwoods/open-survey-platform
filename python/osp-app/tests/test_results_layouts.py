"""Saved results layouts (V-D9): the settings schema admits settings and nothing else, and
the commands are survey.export-gated, tenant-scoped and audited (no HTTP)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from osp_app import (
    ConflictError,
    Forbidden,
    InvalidRequest,
    NotFoundError,
    Rejected,
    build_services,
    make_identity,
)
from osp_app.auth.testing import FakeClock
from osp_app.results import Bins, parse_query
from osp_app.results_layouts import SCHEMA_VERSION, LayoutSettings, validate_settings
from osp_store import Keyring, Store, TenantContext, create_engine, migrate

KEY = "a" * 43 + "="

FULL = {
    "schemaVersion": SCHEMA_VERSION,
    "query": {
        "versions": [2, 1],
        "status": "all",
        "submittedFrom": "2026-10-01T00:00:00Z",
        "submittedTo": None,
        "filters": [{"question": "gender", "in": [1, "2"]}],
        "condition": {"variable": "arm", "in": ["a"]},
        "split": {"question": "group", "excludeMissing": True},
        "denominator": "shown",
        "intervals": True,
        "language": "cy",
    },
    "cards": [
        {"question": "q1", "chart": "bars-sorted", "caption": "Figure 1"},
        {"question": "age", "chart": "histogram", "bins": {"width": 5}},
        {"question": "when", "bins": {"unit": "week"}, "splitLayout": "multiples"},
        {"question": "why", "hidden": True},
    ],
    "showNotes": True,
}


# -- the schema ----------------------------------------------------------------------------


def test_empty_settings_normalise_to_the_defaults():
    out = validate_settings({})
    assert out == LayoutSettings().model_dump(mode="json", by_alias=True)
    assert out["schemaVersion"] == SCHEMA_VERSION
    assert out["query"]["denominator"] == "answered" and out["cards"] == []


def test_a_full_layout_round_trips():
    out = validate_settings(FULL)
    assert out["query"]["versions"] == [2, 1]  # as given; the query parser sorts
    assert out["query"]["filters"] == [{"question": "gender", "in": [1, "2"]}]
    assert out["query"]["submittedFrom"] == "2026-10-01T00:00:00Z"
    assert [c["question"] for c in out["cards"]] == ["q1", "age", "when", "why"]
    assert out["cards"][1]["bins"] == {"width": 5.0, "count": None, "unit": None}
    assert validate_settings(out) == out  # idempotent


@pytest.mark.parametrize(
    ("bad", "pointer"),
    [
        ({"data": [1, 2, 3]}, "/data"),  # never data: unknown fields are refused
        ({"cards": [{"question": "q", "values": [1]}]}, "/cards/0/values"),
        ({"schemaVersion": "osp-results-layout/9.9"}, "/schemaVersion"),
        ({"query": {"denominator": "participants"}}, "/query/denominator"),
        ({"query": {"status": "x"}}, "/query/status"),
        ({"query": {"versions": []}}, "/query/versions"),
        ({"query": {"versions": [0]}}, "/query/versions/0"),
        ({"query": {"filters": [{"question": "q", "in": []}]}}, "/query/filters/0/in"),
        ({"query": {"filters": [{"question": "q"}]}}, "/query/filters/0/in"),
        ({"query": {"split": {}}}, "/query/split"),  # exactly one of question / condition
        ({"query": {"split": {"question": "a", "condition": "b"}}}, "/query/split"),
        (
            {"query": {"split": {"question": "a", "excludeMissing": "y"}}},
            "/query/split/excludeMissing",
        ),
        ({"query": {"intervals": 1}}, "/query/intervals"),
        ({"cards": [{"question": "q", "hidden": "no"}]}, "/cards/0/hidden"),
        ({"cards": [{"question": "q", "bins": {"width": float("inf")}}]}, "/cards/0/bins/width"),
        ({"query": {"language": ""}}, "/query/language"),
        ({"cards": [{"question": ""}]}, "/cards/0/question"),
        ({"cards": [{"question": "q", "chart": "Bars"}]}, "/cards/0/chart"),
        ({"cards": [{"question": "q", "chart": "x" * 41}]}, "/cards/0/chart"),
        ({"cards": [{"question": "q", "splitLayout": "pie"}]}, "/cards/0/splitLayout"),
        ({"cards": [{"question": "q", "bins": {"width": 0}}]}, "/cards/0/bins/width"),
        ({"cards": [{"question": "q", "bins": {"count": 201}}]}, "/cards/0/bins/count"),
        ({"cards": [{"question": "q", "bins": {"unit": "hour"}}]}, "/cards/0/bins/unit"),
        ({"cards": [{"question": "q", "caption": "x" * 2001}]}, "/cards/0/caption"),
        ({"cards": [{"question": "q"}, {"question": "q"}]}, ""),  # listed twice
        ({"cards": [{"question": f"q{i}"} for i in range(501)]}, "/cards"),
        ({"showNotes": "yes"}, "/showNotes"),
        ([], ""),
        ("{}", ""),
    ],
)
def test_bad_settings_are_rejected_with_a_pointer(bad, pointer):
    with pytest.raises(Rejected) as exc:
        validate_settings(bad)
    diags = exc.value.diagnostics
    assert diags and all(d.code == "layout.schema" and d.severity == "error" for d in diags)
    assert pointer in {d.pointer for d in diags}, [d.pointer for d in diags]


def test_the_normalised_query_is_what_the_results_endpoint_parses():
    """The saved query plus the cards' bins is a ``ResultsQuery`` V1's parser accepts, and
    means the same thing (the parser normalises codes to text and sorts versions)."""
    out = validate_settings(FULL)
    q = parse_query(
        {
            **out["query"],
            "cards": [{"question": c["question"], "bins": c["bins"]} for c in out["cards"]],
        }
    )
    assert q.versions == (1, 2) and q.status == "all" and q.denominator == "shown"
    assert q.filters == (("gender", frozenset({"1", "2"})),)
    assert q.condition == ("arm", frozenset({"a"}))
    assert (q.split_question, q.split_condition, q.exclude_missing) == ("group", None, True)
    assert q.intervals is True and q.language == "cy"
    assert q.submitted_from == datetime(2026, 10, 1, tzinfo=UTC) and q.submitted_to is None
    assert [c for c, _ in q.cards] == ["q1", "age", "when", "why"]
    assert q.cards[1][1] == Bins(width=5.0) and q.cards[2][1] == Bins(unit="week")
    # Pydantic normalises before the parser runs (True -> the code 1), so the parser is a
    # second line of defence rather than a different answer.
    out = validate_settings({"query": {"filters": [{"question": "q", "in": [True]}]}})
    assert out["query"]["filters"] == [{"question": "q", "in": [1]}]


# -- the commands --------------------------------------------------------------------------


@pytest.fixture
def env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    migrate(engine)
    store = Store(engine, Keyring({"k1": KEY}, active="k1"))
    svc = build_services(store, clock=FakeClock())
    actors = {
        "owner_a": svc.admit(make_identity("owner-a", {"lab-a": "owner"}, "Owner A")),
        "editor_a": svc.admit(make_identity("editor-a", {"lab-a": "editor"})),
        "viewer_a": svc.admit(make_identity("viewer-a", {"lab-a": "viewer"})),
        "owner_b": svc.admit(make_identity("owner-b", {"lab-b": "owner"})),
    }
    sid = svc.builder.run("survey.create", actors["owner_a"], title="S").survey.id
    return svc, actors, sid


def test_owner_and_editor_share_the_surveys_layouts(env):
    svc, actors, sid = env
    run = svc.builder.run
    lay = run(
        "survey.results_layout_create",
        actors["editor_a"],
        survey_id=sid,
        name=" Team view ",
        settings={"cards": [{"question": "q1", "chart": "donut"}]},
        default=True,
    )
    assert lay.name == "Team view" and lay.is_default and lay.created_by == "editor-a"
    assert lay.settings["cards"][0] == {
        "question": "q1", "chart": "donut", "splitLayout": None, "hidden": False,
        "bins": None, "caption": None,
    }  # fmt: skip
    view = run("survey.results_layouts", actors["owner_a"], survey_id=sid)
    assert [x.id for x in view.layouts] == [lay.id] and view.default_layout_id == lay.id
    got = run("survey.results_layout_get", actors["owner_a"], survey_id=sid, layout_id=lay.id)
    assert got == lay

    up = run(
        "survey.results_layout_update",
        actors["owner_a"],
        survey_id=sid,
        layout_id=lay.id,
        name="Lab view",
        settings={},
    )
    assert (up.name, up.settings["cards"], up.updated_by) == ("Lab view", [], "owner-a")
    same = run("survey.results_layout_update", actors["owner_a"], survey_id=sid, layout_id=lay.id)
    assert same == up  # nothing to change

    cleared = run(
        "survey.results_layout_set_default", actors["owner_a"], survey_id=sid, layout_id=None
    )
    assert cleared.default_layout_id is None
    again = run(
        "survey.results_layout_set_default", actors["owner_a"], survey_id=sid, layout_id=lay.id
    )
    assert again.default_layout_id == lay.id
    run("survey.results_layout_delete", actors["editor_a"], survey_id=sid, layout_id=lay.id)
    assert run("survey.results_layouts", actors["owner_a"], survey_id=sid).layouts == []

    actions = [e.action for e in svc.store.list_audit(TenantContext("lab-a", "x"))]
    assert actions.count("results.layout.create") == 1
    assert {"results.layout.update", "results.layout.delete", "results.layout.default.set",
            "results.layout.default.clear"} <= set(actions)  # fmt: skip


def test_bad_input_is_refused_before_the_store(env):
    svc, actors, sid = env
    owner = actors["owner_a"]
    with pytest.raises(InvalidRequest):
        svc.builder.run("survey.results_layout_create", owner, survey_id=sid, name="", settings={})
    with pytest.raises(Rejected):
        svc.builder.run(
            "survey.results_layout_create", owner, survey_id=sid, name="x", settings={"d": 1}
        )
    with pytest.raises(InvalidRequest):
        svc.builder.run(
            "survey.results_layout_create", owner, survey_id=sid, name="x", settings={},
            default="yes",
        )  # fmt: skip
    lay = svc.builder.run(
        "survey.results_layout_create", owner, survey_id=sid, name="One", settings={}
    )
    with pytest.raises(ConflictError):
        svc.builder.run(
            "survey.results_layout_create", owner, survey_id=sid, name="One", settings={}
        )
    with pytest.raises(Rejected):
        svc.builder.run(
            "survey.results_layout_update", owner, survey_id=sid, layout_id=lay.id,
            settings={"cards": "no"},
        )  # fmt: skip
    with pytest.raises(NotFoundError):
        svc.builder.run("survey.results_layout_get", owner, survey_id=sid, layout_id="nope")
    with pytest.raises(NotFoundError):
        svc.builder.run("survey.results_layout_set_default", owner, survey_id=sid, layout_id=7)
    assert svc.builder.run("survey.results_layouts", owner, survey_id=sid).layouts == [lay]


@pytest.mark.parametrize(
    "command_id",
    [
        "survey.results_layouts",
        "survey.results_layout_get",
        "survey.results_layout_create",
        "survey.results_layout_update",
        "survey.results_layout_delete",
        "survey.results_layout_set_default",
    ],
)
def test_viewers_are_forbidden_and_other_labs_see_nothing(env, command_id):
    svc, actors, sid = env
    lay = svc.builder.run(
        "survey.results_layout_create", actors["owner_a"], survey_id=sid, name="L", settings={}
    )
    params = {
        "survey.results_layouts": {},
        "survey.results_layout_get": {"layout_id": lay.id},
        "survey.results_layout_create": {"name": "x", "settings": {}},
        "survey.results_layout_update": {"layout_id": lay.id, "name": "x"},
        "survey.results_layout_delete": {"layout_id": lay.id},
        "survey.results_layout_set_default": {"layout_id": lay.id},
    }[command_id]
    with pytest.raises(Forbidden):
        svc.builder.run(command_id, actors["viewer_a"], survey_id=sid, **params)
    with pytest.raises(NotFoundError):
        svc.builder.run(command_id, actors["owner_b"], survey_id=sid, **params)
    view = svc.builder.run("survey.results_layouts", actors["owner_a"], survey_id=sid)
    assert [x.name for x in view.layouts] == ["L"]  # untouched
    audit_b = svc.store.list_audit(TenantContext("lab-b", "x"))
    assert not any(e.action.startswith("results.layout") for e in audit_b)
