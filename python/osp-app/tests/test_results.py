"""Results aggregation (task V1): every V-D5 rule against hand-computed expectations.

The fixture responses are in ``results_data.py``; each expectation below is worked out by
hand from that table (comments show the arithmetic).
"""

from __future__ import annotations

import copy
import json
import math
from datetime import timedelta

import pytest
from osp_app import Forbidden, InvalidRequest, NotFoundError, build_services, make_identity
from osp_app.auth.testing import FakeClock
from osp_app.results import Bins, numeric_edges, periods, quantile, t975, wilson
from osp_store import Keyring, Store, TenantContext, create_engine, migrate

from .results_data import SURVEY, T0, A, add_response, publish, seed

KEY = "a" * 43 + "="


@pytest.fixture
def env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'r.db'}")
    migrate(engine)
    store = Store(engine, Keyring({"k1": KEY}, active="k1"))
    svc = build_services(store, clock=FakeClock())
    owner = svc.admit(make_identity("owner-a", {"lab-a": "owner"}))
    editor = svc.admit(make_identity("editor-a", {"lab-a": "editor"}))
    viewer = svc.admit(make_identity("viewer-a", {"lab-a": "viewer"}))
    other = svc.admit(make_identity("owner-b", {"lab-b": "owner"}))
    sid = svc.builder.run("survey.create", owner, title="R", survey=SURVEY).survey.id
    ctx = TenantContext(next(iter(owner.roles)), "system:test")
    v1 = publish(store, ctx, sid, SURVEY)
    ids = seed(store, ctx, v1.id)

    class Env:
        pass

    e = Env()
    e.svc, e.store, e.sid, e.ctx, e.v1, e.ids = svc, store, sid, ctx, v1, ids
    e.owner, e.editor, e.viewer, e.other = owner, editor, viewer, other

    def q(actor=owner, **query):
        return svc.builder.run("survey.results_query", actor, survey_id=sid, query=query)

    def card(question, **query):
        out = q(cards=[{"question": question, **query.pop("card", {})}], **query)
        return out["cards"][0]

    def text(actor=owner, **params):
        return svc.builder.run("survey.results_text", actor, survey_id=sid, **params)

    e.q, e.card, e.text = q, card, text
    return e


def cells(group):
    return {c["key"]: (c["count"], c["pct"]) for c in group["cells"]}


def approx(x):
    return pytest.approx(x, rel=1e-6, abs=1e-9)


# -- statistics helpers -----------------------------------------------------------------


def test_quantiles_are_type_7():
    s = [20.0, 25.0, 30.0, 40.0]
    assert quantile(s, 0.5) == 27.5  # h = 1.5: 25 + 0.5 * 5
    assert quantile(s, 0.25) == 23.75  # h = 0.75: 20 + 0.75 * 5
    assert quantile(s, 0.75) == 32.5  # h = 2.25: 30 + 0.25 * 10
    assert quantile([], 0.5) is None


def test_wilson_and_t():
    lo, hi = wilson(2, 3)
    assert lo == pytest.approx(20.77, abs=0.01) and hi == pytest.approx(93.85, abs=0.01)
    assert wilson(0, 0) is None
    assert wilson(0, 10)[0] == 0.0
    assert t975(1) == pytest.approx(12.706, abs=1e-3)
    assert t975(30) == pytest.approx(2.0423, abs=1e-4)
    assert t975(60) == pytest.approx(2.0003, abs=1e-4)  # Cornish-Fisher
    assert t975(1000) == pytest.approx(1.9623, abs=1e-4)


def test_numeric_edges_and_periods():
    assert numeric_edges([20, 40], _bins(), True)[0] == [float(x) for x in range(20, 42)]
    assert numeric_edges([10, 99], _bins(), True)[0] == [float(x) for x in range(10, 101, 10)]
    edges, coarse = numeric_edges([0, 1e6], _bins(width=1), False)
    assert coarse and len(edges) - 1 <= 200
    assert periods(T0.date(), T0.date() + timedelta(days=15), "week") == [
        "2026-W01",
        "2026-W02",
        "2026-W03",
    ]


def _bins(**kw):
    return Bins(**kw)


# -- every question type -----------------------------------------------------------------


def test_single_choice_unordered(env):
    c = env.card("fruit")
    assert c["type"] == "single" and c["ordered"] is False
    # answered r1 apple, r2 banana, r3 apple; r4 unanswered; r5 "durian" is not declared
    assert c["states"] == {
        "answered": 3, "unanswered": 1, "irrelevant": 0, "notReached": 0,
        "notInVersion": 0, "unrecorded": 0, "invalid": 1,
    }  # fmt: skip
    (g,) = c["groups"]
    assert g["key"] == "all" and g["n"] == 3 and g["responses"] == 5
    assert cells(g) == {"apple": (2, approx(200 / 3)), "banana": (1, approx(100 / 3)),
                        "cherry": (0, 0.0)}  # fmt: skip
    assert [k["key"] for k in c["categories"]] == ["apple", "banana", "cherry"]  # declared
    assert g["stats"]["mode"] == ["apple"] and "median" not in g["stats"]


def test_shown_denominator_adds_unanswered_only(env):
    g = env.card("fruit", denominator="shown")["groups"][0]
    assert g["n"] == 4  # answered 3 + unanswered 1; never invalid / irrelevant
    assert cells(g)["apple"] == (2, 50.0)


def test_single_choice_ordered_scale(env):
    c = env.card("sat")
    g = c["groups"][0]
    assert c["ordered"] is True and g["n"] == 4  # 5, 4, 1, 2
    s = g["stats"]
    assert s["median"] == "2"  # sorted 1, 2, 4, 5: the 2nd (lower median)
    assert s["top2"] == 50.0 and s["bottom2"] == 50.0  # (4, 5) and (1, 2): 2 of 4 each
    assert s["mode"] == ["1", "2", "4", "5"]  # all tie at 1
    assert "mean" not in s or s.get("mean") is None  # codes are never averaged


def test_multiple_choice_percent_of_respondents(env):
    c = env.card("col")
    g = c["groups"][0]
    # answered r1 [red, green], r2 [red], r3 [] (answered, nothing ticked), r5 [blue, green]
    assert g["n"] == 4 and c["states"]["unanswered"] == 1
    assert cells(g) == {"red": (2, 50.0), "green": (2, 50.0), "blue": (1, 25.0)}
    assert sum(p for _, p in cells(g).values()) == 125.0  # can sum to more than 100
    assert g["stats"]["meanOptions"] == 1.25  # (2 + 1 + 0 + 2) / 4


def test_integer_histogram_and_stats(env):
    c = env.card("age")
    g = c["groups"][0]
    assert c["binning"] == "bins" and c["binEdges"] == [float(x) for x in range(20, 42)]
    assert {k: v[0] for k, v in cells(g).items() if v[0]} == {"0": 1, "5": 1, "10": 1, "20": 1}
    assert g["cells"][0]["label"] == "20"
    s = g["stats"]
    assert s["n"] == 4 and s["mean"] == 28.75  # (20 + 25 + 30 + 40) / 4
    assert s["sd"] == approx(math.sqrt(218.75 / 3))  # squares 76.5625 + 14.0625 + ...
    assert (s["median"], s["q1"], s["q3"], s["min"], s["max"]) == (27.5, 23.75, 32.5, 20, 40)
    assert c["states"]["irrelevant"] == 1
    assert "meanCi" not in s  # intervals are off by default


def test_custom_bin_width(env):
    c = env.card("age", card={"bins": {"width": 10}})
    assert c["binEdges"] == [20.0, 30.0, 40.0, 50.0]
    assert [x["count"] for x in c["groups"][0]["cells"]] == [2, 1, 1]  # 20,25 | 30 | 40
    assert c["groups"][0]["cells"][0]["label"] == "20–30"


def test_intervals_when_asked(env):
    g = env.card("age", intervals=True)["groups"][0]
    lo, hi = g["stats"]["meanCi"]
    half = 3.182446 * math.sqrt(218.75 / 3) / 2  # t(0.975, 3) * sd / sqrt(4)
    assert lo == approx(28.75 - half) and hi == approx(28.75 + half)
    f = env.card("fruit", intervals=True)["groups"][0]
    apple = next(x for x in f["cells"] if x["key"] == "apple")
    assert apple["ci"] == [approx(wilson(2, 3)[0]), approx(wilson(2, 3)[1])]


def test_decimal(env):
    c = env.card("price", card={"bins": {"width": 1}})
    g = c["groups"][0]
    assert c["states"]["answered"] == 2 and c["states"]["invalid"] == 1  # "abc"
    assert c["binEdges"] == [2.0, 3.0, 4.0]
    assert [x["count"] for x in g["cells"]] == [1, 1]
    assert g["stats"]["mean"] == 2.75 and g["stats"]["sd"] == approx(math.sqrt(0.125))


def test_slider_frequency_bars_and_histogram(env):
    c = env.card("sl")  # 0..10 step 1: 11 values <= 21, so one bar per value
    g = c["groups"][0]
    assert c["binning"] == "values" and len(g["cells"]) == 11
    assert cells(g)["3"] == (2, approx(200 / 3)) and cells(g)["7"] == (1, approx(100 / 3))
    assert c["states"]["invalid"] == 1 and c["states"]["notReached"] == 1  # 3.5; r4
    big = env.card("big")  # 0..100: histogram, width 10 from 10 (span 89)
    assert big["binning"] == "bins" and big["binEdges"][0] == 10.0
    assert [x["count"] for x in big["groups"][0]["cells"]] == [1, 0, 0, 0, 1, 0, 0, 0, 1]


def test_date_periods(env):
    c = env.card("when")
    g = c["groups"][0]
    assert c["binUnit"] == "month" and [x["key"] for x in g["cells"]] == [
        "2026-01", "2026-02", "2026-03",
    ]  # fmt: skip
    assert [x["count"] for x in g["cells"]] == [2, 0, 1]
    assert g["stats"]["earliest"] == "2026-01-15" and g["stats"]["latest"] == "2026-03-01"
    assert c["states"]["invalid"] == 1  # 2026-13-01
    days = env.card("when", card={"bins": {"unit": "year"}})
    assert [x["key"] for x in days["groups"][0]["cells"]] == ["2026"]


def test_text_card_has_no_values(env):
    c = env.card("why")
    g = c["groups"][0]
    assert g["cells"] == [] and g["n"] == 3
    assert g["stats"]["meanLength"] == 4.0  # sunny 5, rain! 5, ok 2
    assert "sunny" not in json.dumps(c, default=str)


def test_matrix_rows_are_separate_variables(env):
    c = env.card("grid")
    assert c["type"] == "matrix" and c["states"] is None and c["ordered"] is True
    r1, r2 = c["rows"]
    assert r1["id"] == "grid_r1" and r1["name"] == "grid_r1" and r1["label"] == "Row one"
    # r1 row: 1, 2, 5 answered; r4 not reached; r5 has no state recorded
    assert r1["states"]["answered"] == 3 and r1["states"]["unrecorded"] == 1
    g1 = r1["groups"][0]
    assert g1["n"] == 3 and g1["stats"]["median"] == "2"
    assert g1["stats"]["top2"] == approx(100 / 3) and g1["stats"]["bottom2"] == approx(200 / 3)
    assert r2["groups"][0]["n"] == 2 and r2["states"]["unanswered"] == 1  # its own n


def test_note_and_unknown_cards(env):
    out = env.q(cards=[{"question": "n1"}, {"question": "nope"}])
    (note,) = out["cards"]
    assert note["type"] == "note" and note["states"] is None and note["groups"] == []
    assert out["warnings"][0]["code"] == "question.not_found"


def test_default_cards_are_every_question_in_order(env):
    out = env.q()
    assert [c["question"] for c in out["cards"]] == [
        "fruit", "sat", "col", "age", "price", "sl", "big", "when", "why", "grid",
    ]  # fmt: skip
    assert out["responses"] == 5 and out["versionsUsed"] == [1] and out["cached"] is False


# -- splits and filters -----------------------------------------------------------------


def test_split_by_condition_each_group_its_own_n(env):
    out = env.q(cards=[{"question": "fruit"}, {"question": "age"}], split={"condition": "arm"})
    assert [(g["key"], g["responses"]) for g in out["split"]["groups"]] == [
        ("a", 2), ("b", 2), ("_missing", 1),
    ]  # fmt: skip
    fruit, age = out["cards"]
    a, b, missing = fruit["groups"]
    assert cells(a)["apple"] == (1, 50.0) and a["n"] == 2
    assert b["n"] == 1 and cells(b)["apple"] == (1, 100.0)  # r4 unanswered
    assert missing["missing"] and missing["n"] == 0 and cells(missing)["apple"] == (0, None)
    # shared bin edges; one value in group b: SD not available, never 0
    assert all(len(g["cells"]) == 21 for g in age["groups"])
    gb = age["groups"][1]["stats"]
    assert gb["mean"] == 25 and gb["sd"] is None and "sd" in gb["notAvailable"]
    assert age["groups"][2]["stats"]["mean"] == 40  # r5 has no arm: the missing group


def test_split_missing_can_be_excluded(env):
    out = env.q(cards=[{"question": "fruit"}], split={"condition": "arm", "excludeMissing": True})
    assert [g["key"] for g in out["cards"][0]["groups"]] == ["a", "b"]
    assert out["responses"] == 4


def test_split_by_question(env):
    out = env.q(cards=[{"question": "age"}], split={"question": "fruit"})
    groups = {g["key"]: g for g in out["cards"][0]["groups"]}
    assert list(groups) == ["apple", "banana", "cherry", "_missing"]
    assert groups["apple"]["stats"]["mean"] == 22.5  # r1 20, r3 25
    assert groups["_missing"]["stats"]["n"] == 1  # r5 (invalid fruit) age 40; r4 irrelevant
    with pytest.raises(InvalidRequest):
        env.q(split={"question": "col"})  # multiple choice cannot split


def test_answer_and_condition_filters(env):
    out = env.q(cards=[{"question": "age"}], filters=[{"question": "fruit", "in": ["apple"]}])
    assert out["responses"] == 2 and out["cards"][0]["groups"][0]["stats"]["mean"] == 22.5
    multi = env.q(cards=[{"question": "age"}], filters=[{"question": "col", "in": ["green"]}])
    assert multi["responses"] == 2  # r1, r5
    cond = env.q(cards=[{"question": "fruit"}], condition={"variable": "arm", "in": ["b"]})
    assert cond["responses"] == 2
    with pytest.raises(InvalidRequest):
        env.q(filters=[{"question": "age", "in": [1]}])


def test_submitted_date_range(env):
    out = env.q(
        cards=[{"question": "fruit"}],
        submittedFrom=(T0 + timedelta(days=1)).isoformat(),
        submittedTo=(T0 + timedelta(days=3)).isoformat(),
    )
    assert out["responses"] == 2  # r2, r3 (to is exclusive)


def test_completion_status_and_languages(env):
    add_response(env.store, env.ctx, env.v1.id, {"fruit": A("cherry")},
                 record={"end": "screened_out", "language": "cy"})  # fmt: skip
    add_response(env.store, env.ctx, env.v1.id, {"fruit": A("cherry")},
                 record={"end": "complete", "language": "cy"})  # fmt: skip
    assert env.q(cards=[{"question": "fruit"}])["responses"] == 6  # 5 row-only + 1 complete
    out = env.q(cards=[{"question": "fruit"}], status="all", language="cy")
    assert out["responses"] == 7 and out["language"] == "cy"
    c = out["cards"][0]
    assert c["label"] == "Ffrwyth?" and c["categories"][0]["label"] == "Afal"
    assert cells(c["groups"][0])["cherry"][0] == 2  # aggregated by id, whatever language
    fr = env.q(cards=[{"question": "fruit"}], language="fr")
    assert fr["language"] == "en" and fr["warnings"][0]["code"] == "language.unknown"


# -- versions ---------------------------------------------------------------------------


def _v2(env):
    body = copy.deepcopy(SURVEY)
    body["choiceLists"][0]["choices"].append({"value": "date", "label": "Date"})
    items = body["blocks"][0]["pages"][0]["items"]
    body["blocks"][0]["pages"][0]["items"] = [i for i in items if i["id"] != "sat"] + [
        {"type": "integer", "id": "extra", "label": "Extra"}
    ]
    v2 = publish(env.store, env.ctx, env.sid, body)
    add_response(env.store, env.ctx, v2.id, {"fruit": A("date"), "age": A(50), "extra": A(1)})
    add_response(env.store, env.ctx, v2.id, {"fruit": A("apple"), "age": A(60), "extra": A(2)})
    return v2


def test_versions_default_latest_combined_or_faceted(env):
    _v2(env)
    assert env.q(cards=[{"question": "age"}])["versionsUsed"] == [2]
    out = env.q(versions=[1, 2], cards=[{"question": q} for q in ("age", "sat", "fruit", "extra")])
    age, sat, fruit, extra = out["cards"]
    assert age["facets"] is None and age["versionsUsed"] == [1, 2]
    assert age["groups"][0]["n"] == 6 and age["groups"][0]["stats"]["mean"] == approx(225 / 6)
    assert sat["states"]["notInVersion"] == 2 and sat["groups"][0]["n"] == 4  # outside n
    assert extra["states"]["notInVersion"] == 5 and extra["versionsUsed"] == [2]
    # fruit gained a code in v2: per-version facets, never pooled
    assert fruit["groups"] == [] and fruit["warnings"][0]["code"] == "versions.incompatible"
    f1, f2 = fruit["facets"]
    assert (f1["version"], f1["groups"][0]["n"]) == (1, 3)
    assert (f2["version"], f2["groups"][0]["n"]) == (2, 2)
    assert [k["key"] for k in f2["categories"]][-1] == "date"
    assert fruit["states"]["answered"] == 5
    with pytest.raises(NotFoundError):
        env.q(versions=[9])


# -- text endpoint ----------------------------------------------------------------------


def test_text_endpoint_pages(env):
    p1 = env.text(question="why", limit=2)
    assert p1["total"] == 3 and [i["value"] for i in p1["items"]] == ["sunny", "rain!"]
    assert p1["states"]["answered"] == 3 and p1["states"]["notReached"] == 1
    p2 = env.text(question="why", limit=2, cursor=p1["nextCursor"])
    assert [i["value"] for i in p2["items"]] == ["ok"] and p2["nextCursor"] is None
    f = env.text(question="why", filters=["fruit:apple"])
    assert [i["value"] for i in f["items"]] == ["sunny"]
    c = env.text(question="why", condition="arm:a")
    assert c["total"] == 2
    with pytest.raises(InvalidRequest):
        env.text(question="age")
    with pytest.raises(NotFoundError):
        env.text(question="nope")
    with pytest.raises(InvalidRequest):
        env.text(question="why", cursor="!!")


# -- access, audit, cache ---------------------------------------------------------------


def test_editor_allowed_viewer_and_other_lab_refused(env):
    assert env.q(actor=env.editor)["responses"] == 5
    with pytest.raises(Forbidden):
        env.q(actor=env.viewer)
    with pytest.raises(Forbidden):
        env.text(actor=env.viewer, question="why")
    with pytest.raises(NotFoundError):
        env.q(actor=env.other)
    with pytest.raises(NotFoundError):
        env.text(actor=env.other, question="why")


def test_audit_rows_name_the_query_never_values(env):
    env.q(cards=[{"question": "why"}, {"question": "fruit"}])
    env.text(question="why")
    rows = [a for a in env.store.list_audit(env.ctx) if a.action == "results.read"]
    assert len(rows) == 2 and all(r.actor == "owner-a" for r in rows)
    assert rows[0].detail["versions"] == [1]
    assert rows[0].detail["query"]["cards"][0]["question"] == "why"
    assert rows[1].detail["kind"] == "text" and rows[1].detail["returned"] == 3
    dumped = json.dumps([r.detail for r in rows])
    for value in ("sunny", "rain!", "banana", "durian"):
        assert value not in dumped


def _export(env, actor=None, **kw):
    args = {"query": {}, "cards": ["fruit"], "formats": ["png"], **kw}
    return env.svc.builder.run(
        "survey.results_export", actor or env.owner, survey_id=env.sid, **args
    )


def test_export_audit_row_matches_the_query_hash(env):
    query = {"denominator": "shown", "filters": [{"question": "fruit", "in": ["apple"]}]}
    q = env.q(**query)
    out = _export(env, query=query, formats=["zip", "csv", "csv"], scope="page", suppress_below=5)
    assert out == {"recorded": True, "queryHash": q["queryHash"], "versions": [1],
                   "formats": ["csv", "zip"]}  # fmt: skip
    rows = [a for a in env.store.list_audit(env.ctx) if a.action == "results.export"]
    assert len(rows) == 1 and rows[0].actor == "owner-a"
    d = rows[0].detail
    assert d["queryHash"] == q["queryHash"] and d["versions"] == [1]
    assert d["formats"] == ["csv", "zip"] and d["scope"] == "page" and d["suppressBelow"] == 5
    assert d["query"]["filters"] == [{"question": "fruit", "in": ["apple"]}]
    for value in ("sunny", "banana", "count"):
        assert value not in json.dumps(d)


@pytest.mark.parametrize(
    "bad",
    [
        {"formats": []},
        {"formats": ["pdf"]},
        {"formats": "png"},
        {"cards": []},
        {"cards": [3]},
        {"cards": None},
        {"scope": "all"},
        {"suppress_below": 0},
        {"suppress_below": True},
        {"suppress_below": "5"},
        {"query": "x"},
        {"query": {"status": "x"}},
    ],
)
def test_export_rejects_bad_input(env, bad):
    with pytest.raises(InvalidRequest):
        _export(env, **bad)
    assert not [a for a in env.store.list_audit(env.ctx) if a.action == "results.export"]


def test_export_access(env):
    assert _export(env, actor=env.editor)["recorded"] is True
    with pytest.raises(Forbidden):
        _export(env, actor=env.viewer)
    with pytest.raises(NotFoundError):
        _export(env, actor=env.other)
    with pytest.raises(NotFoundError):
        _export(env, query={"versions": [4]})


def test_cache_hits_and_new_responses_invalidate(env):
    first = env.q(cards=[{"question": "fruit"}])
    second = env.q(cards=[{"question": "fruit"}])
    assert second["cached"] is True and second["queryHash"] == first["queryHash"]
    assert second["generatedAt"] == first["generatedAt"]
    add_response(env.store, env.ctx, env.v1.id, {"fruit": A("cherry")})
    third = env.q(cards=[{"question": "fruit"}])
    assert third["cached"] is False and third["watermark"] != first["watermark"]
    assert cells(third["cards"][0]["groups"][0])["cherry"][0] == 1
    env.store.delete_response(env.ctx, env.ids[0])
    assert env.q(cards=[{"question": "fruit"}])["responses"] == 5


def test_bad_queries_are_invalid_requests(env):
    for bad in (
        {"versions": [0]},
        {"status": "x"},
        {"denominator": "x"},
        {"filters": [{"question": "fruit", "in": []}]},
        {"split": {"question": "fruit", "condition": "arm"}},
        {"cards": [{"question": "age", "bins": {"width": -1}}]},
        {"submittedFrom": "yesterday"},
    ):
        with pytest.raises(InvalidRequest):
            env.q(**bad)
