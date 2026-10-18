"""Question bank ops (planning/question-bank.md §4, task QB3): `insert_bank_item` and
`clear_source`. Round trips and params fuzzing for every op are in test_guard.py; here
are the behaviours and a Hypothesis fuzz over hostile fragments."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from osp_ops import REGISTRY, Draft, apply_transaction, run
from osp_ops import patch as jp
from osp_spec import parse
from osp_spec.bank import fragment_checksum, sources

BASE: dict[str, Any] = json.loads((Path(__file__).parent / "base_survey.json").read_text("utf-8"))
SRC = {"bank": "phq2", "version": 1, "library": "bundled"}

REF_Q1 = {"kind": "ref", "id": "phq2_q1"}
REF_Q2 = {"kind": "ref", "id": "phq2_q2"}
FREQUENCY = [
    {"value": 0, "label": "Not at all"},
    {"value": 1, "label": "Several days"},
    {"value": 2, "label": "More than half the days"},
    {"value": 3, "label": "Nearly every day"},
]
# An invented two-item instrument in the shape of the bundled ones: a block with one
# matrix on a shared list and a scoring variable.
BLOCK_FRAGMENT: dict[str, Any] = {
    "choiceLists": [{"id": "phq_frequency", "choices": FREQUENCY}],
    "variables": [
        {
            "id": "phq2_total",
            "kind": "computed",
            "expr": {"kind": "arith", "op": "+", "left": REF_Q1, "right": REF_Q2},
        }
    ],
    "block": {
        "id": "phq2_block",
        "title": "PHQ-2",
        "pages": [
            {
                "id": "phq2_page",
                "items": [
                    {
                        "id": "phq2",
                        "type": "matrix",
                        "label": "Over the last 2 weeks, how often ...?",
                        "choiceList": "phq_frequency",
                        "rows": [
                            {"id": "q1", "label": "Little interest"},
                            {"id": "q2", "label": "Feeling down"},
                        ],
                    },
                    {
                        "id": "phq2_note",
                        "type": "note",
                        "label": "Your score is ${phq2_total}.",
                        "showIf": {"kind": "answered", "ref": {"kind": "ref", "id": "phq2_q2"}},
                    },
                ],
            }
        ],
    },
}
PAGE_FRAGMENT: dict[str, Any] = {
    "choiceLists": [{"id": "yesno", "choices": [{"value": 1, "label": "Yes"}]}],
    "variables": [],
    "page": {
        "id": "p_demo",
        "items": [
            {"id": "age", "type": "single", "label": "Agree?", "choiceList": "yesno"},
            {"id": "why", "type": "text", "label": "Why, ${age}?", "name": "reason"},
        ],
    },
}
QUESTION_FRAGMENT: dict[str, Any] = {
    "question": {
        "id": "happy",
        "type": "integer",
        "label": "How happy are you?",
        "constraint": {
            "kind": "compare",
            "op": "<=",
            "left": {"kind": "ref", "id": "happy"},
            "right": {"kind": "int", "value": 10},
        },
    }
}


def base() -> dict[str, Any]:
    return copy.deepcopy(BASE)


def ids_of(survey: dict[str, Any], key: str) -> list[str]:
    return [o["id"] for o in survey.get(key) or []]


def block(survey: dict[str, Any], bid: str) -> dict[str, Any]:
    return next(b for b in survey["blocks"] if b["id"] == bid)


def question(survey: dict[str, Any], qid: str) -> dict[str, Any]:
    return next(
        q for b in survey["blocks"] for p in b["pages"] for q in p["items"] if q["id"] == qid
    )


def insert(survey: dict[str, Any], fragment: dict[str, Any], **more: Any) -> Any:
    return run("insert_bank_item", survey, {"fragment": fragment, "source": SRC, **more})


def test_registered_in_the_bank_area() -> None:
    assert {k for k, v in REGISTRY.items() if v.area == "bank"} == {
        "insert_bank_item",
        "clear_source",
    }


# --- insert each kind -------------------------------------------------------------------


def test_insert_block_with_lists_variables_and_flow_node() -> None:
    res = insert(base(), BLOCK_FRAGMENT, flow={"after": "n_intro"})
    assert res.ok, [d.message for d in res.diagnostics]
    s = res.survey
    assert ids_of(s, "blocks")[-1] == "phq2_block"
    assert ids_of(s, "choiceLists") == ["yesno", "spare", "phq_frequency"]
    assert ids_of(s, "variables")[-1] == "phq2_total"
    assert [n["id"] for n in s["flow"][:3]] == ["n_intro", "n_phq2_block", "n_quota"]
    assert s["flow"][1] == {"type": "block", "id": "n_phq2_block", "block": "phq2_block"}
    b = block(s, "phq2_block")
    assert b["source"] == {
        **SRC,
        "item": "phq2_block",
        "checksum": fragment_checksum(BLOCK_FRAGMENT),
    }
    # The questions inherit the block's source (osp_spec.bank.sources).
    assert dict(sources(s))["phq2"] == b["source"]
    assert "source" not in b["pages"][0] and "source" not in question(s, "phq2")
    assert not [d for d in res.diagnostics if d.severity == "error"]


def test_insert_block_at_index_without_flow_node() -> None:
    res = insert(base(), BLOCK_FRAGMENT, index=0)
    assert res.ok
    assert ids_of(res.survey, "blocks")[0] == "phq2_block"
    assert [n["id"] for n in res.survey["flow"]] == [n["id"] for n in BASE["flow"]]


def test_insert_block_flow_node_at_the_end_of_the_top_level_flow() -> None:
    res = insert(base(), BLOCK_FRAGMENT, flow={})
    assert res.ok
    assert res.survey["flow"][-1]["block"] == "phq2_block"


def test_insert_block_flow_node_inside_a_randomiser() -> None:
    res = insert(base(), BLOCK_FRAGMENT, flow={"after": "n_main"})
    assert res.ok
    children = res.survey["flow"][3]["then"][0]["children"]
    assert [n["id"] for n in children] == ["n_main", "n_phq2_block", "n_extra"]


def test_insert_page_remaps_pipes_names_and_clashing_ids() -> None:
    # `p_demo`, `age` and `yesno` exist in BASE; `yesno`'s choices differ, so it is added.
    res = insert(base(), PAGE_FRAGMENT, block="b_extra", index=1)
    assert res.ok, [d.message for d in res.diagnostics]
    pages = block(res.survey, "b_extra")["pages"]
    assert [p["id"] for p in pages] == ["p_extra", "p_demo_2"]
    q_age, q_why = pages[1]["items"]
    assert q_age["id"] == "age_2" and q_age["choiceList"] == "yesno_2"
    assert q_why["label"] == "Why, ${age_2}?" and q_why["name"] == "reason"
    assert ids_of(res.survey, "choiceLists") == ["yesno", "spare", "yesno_2"]
    assert pages[1]["source"]["item"] == "p_demo"
    assert question(res.survey, "age")["type"] == "integer", "the original is untouched"


def test_insert_question_keeps_self_reference() -> None:
    res = insert(base(), QUESTION_FRAGMENT, page="p_main", index=0)
    assert res.ok, [d.message for d in res.diagnostics]
    q = block(res.survey, "b_main")["pages"][0]["items"][0]
    assert q["id"] == "happy" and q["constraint"]["left"] == {"kind": "ref", "id": "happy"}
    assert q["source"]["item"] == "happy"


def test_second_insert_gets_suffixed_ids_and_reuses_the_choice_list() -> None:
    first = insert(base(), BLOCK_FRAGMENT)
    second = insert(first.survey, BLOCK_FRAGMENT)
    assert second.ok, [d.message for d in second.diagnostics]
    s = second.survey
    assert ids_of(s, "blocks")[-2:] == ["phq2_block", "phq2_block_2"]
    assert ids_of(s, "choiceLists") == ["yesno", "spare", "phq_frequency"], "reused"
    assert ids_of(s, "variables")[-2:] == ["phq2_total", "phq2_total_2"]
    copy_ = block(s, "phq2_block_2")
    grid, note = copy_["pages"][0]["items"]
    assert grid["id"] == "phq2_2" and grid["choiceList"] == "phq_frequency"
    assert [r["id"] for r in grid["rows"]] == ["q1", "q2"], "row ids are local"
    assert note["id"] == "phq2_note_2"
    assert note["label"] == "Your score is ${phq2_total_2}."
    assert note["showIf"]["ref"] == {"kind": "ref", "id": "phq2_2_q2"}
    total = s["variables"][-1]
    assert total["expr"]["left"] == {"kind": "ref", "id": "phq2_2_q1"}
    assert not [d for d in second.diagnostics if d.severity == "error"]


def test_choice_list_reuse_is_by_content_not_id() -> None:
    frag = copy.deepcopy(BLOCK_FRAGMENT)
    frag["choiceLists"][0]["choices"] = copy.deepcopy(BASE["choiceLists"][1]["choices"])
    res = insert(base(), frag)
    assert res.ok
    assert ids_of(res.survey, "choiceLists") == ["yesno", "spare"]
    assert question(res.survey, "phq2")["choiceList"] == "spare"


def test_matrix_id_avoids_a_clash_with_its_row_variables() -> None:
    s = base()
    s["blocks"][2]["pages"][0]["items"].append({"id": "phq2_q1", "type": "text", "label": "x"})
    res = insert(s, BLOCK_FRAGMENT)
    assert res.ok, [d.message for d in res.diagnostics]
    assert question(res.survey, "phq2_2")["type"] == "matrix"
    assert not [d for d in res.diagnostics if d.code == "id.duplicate"]


def test_fragment_source_fields_are_replaced() -> None:
    frag = copy.deepcopy(BLOCK_FRAGMENT)
    frag["block"]["source"] = {"bank": "old", "version": 3, "library": "lab"}
    frag["block"]["pages"][0]["source"] = {"bank": "older", "version": 1, "library": "host"}
    res = insert(base(), frag)
    assert res.ok
    b = block(res.survey, "phq2_block")
    assert b["source"]["bank"] == "phq2" and "source" not in b["pages"][0]


def test_source_checksum_given_is_kept() -> None:
    src = {**SRC, "checksum": "sha256:" + "0" * 64, "item": "ignored"}
    res = run("insert_bank_item", base(), {"fragment": QUESTION_FRAGMENT, "source": src,
                                             "page": "p_extra"})  # fmt: skip
    assert res.ok
    q = question(res.survey, "happy")
    assert q["source"]["checksum"] == src["checksum"] and q["source"]["item"] == "happy"


# --- refusals ---------------------------------------------------------------------------


def codes(res: Any) -> list[str]:
    return [d.code for d in res.diagnostics]


def test_external_reference_is_refused_whole() -> None:
    frag = copy.deepcopy(BLOCK_FRAGMENT)
    frag["block"]["pages"][0]["items"][0]["showIf"] = {
        "kind": "answered",
        "ref": {"kind": "ref", "id": "age"},
    }
    res = insert(base(), frag)
    assert not res.ok and codes(res)[0] == "op.params"
    assert res.diagnostics[0].pointer == "/fragment/block/pages/0/items/0/showIf"
    assert jp.same(res.survey, BASE), "nothing half-inserted"


def test_external_pipe_is_refused() -> None:
    frag = copy.deepcopy(QUESTION_FRAGMENT)
    frag["question"]["label"] = "Older than ${age}?"
    res = insert(base(), frag, page="p_extra")
    assert not res.ok and codes(res)[0] == "op.params"


@pytest.mark.parametrize(
    "fragment",
    [
        {},
        {"question": QUESTION_FRAGMENT["question"], "page": PAGE_FRAGMENT["page"]},
        {"flow": [{"type": "end", "id": "n"}]},
        {"block": {"id": "b", "pages": []}},
        {"question": {"id": "q", "type": "nope", "label": "x"}},
        {"variables": [{"id": "v", "kind": "embedded", "param": "p"}], "question": None},
    ],
)
def test_bad_fragments_are_refused(fragment: dict[str, Any]) -> None:
    res = insert(base(), fragment, page="p_extra", block="b_extra")
    assert not res.ok and codes(res)[0] == "op.params"
    assert res.diagnostics[0].pointer.startswith("/fragment")


def test_bad_source_is_refused() -> None:
    for src in ({}, {"bank": "x", "version": 0, "library": "lab"}, {**SRC, "library": "web"}):
        res = run("insert_bank_item", base(), {"fragment": QUESTION_FRAGMENT, "source": src,
                                                 "page": "p_extra"})  # fmt: skip
        assert not res.ok and codes(res)[0] == "op.params", src
        assert res.diagnostics[0].pointer.startswith("/source")


@pytest.mark.parametrize(
    ("fragment", "params", "pointer"),
    [
        (QUESTION_FRAGMENT, {}, "/page"),
        (QUESTION_FRAGMENT, {"page": "p_extra", "block": "b_extra"}, "/block"),
        (PAGE_FRAGMENT, {}, "/block"),
        (PAGE_FRAGMENT, {"block": "b_extra", "flow": {}}, "/flow"),
        (BLOCK_FRAGMENT, {"page": "p_extra"}, "/page"),
    ],
)
def test_destination_must_match_the_kind(
    fragment: dict[str, Any], params: dict[str, Any], pointer: str
) -> None:
    res = insert(base(), fragment, **params)
    assert not res.ok and codes(res)[0] == "op.params"
    assert res.diagnostics[0].pointer == pointer


def test_unknown_destination_and_flow_node() -> None:
    assert codes(insert(base(), QUESTION_FRAGMENT, page="nope")) == ["op.not_found"]
    assert codes(insert(base(), PAGE_FRAGMENT, block="p_demo")) == ["op.not_found"]
    assert codes(insert(base(), BLOCK_FRAGMENT, flow={"after": "b_intro"})) == ["op.not_found"]
    assert codes(insert(base(), BLOCK_FRAGMENT, index=9)) == ["op.not_allowed"]


# --- inverse ----------------------------------------------------------------------------


def test_insert_is_one_undo_step() -> None:
    res = insert(base(), BLOCK_FRAGMENT, flow={"after": "n_intro"})
    assert res.ok and res.inverse is not None and res.inverse.op == "apply_patch"
    undo = run(res.inverse.op, res.survey, res.inverse.params)
    assert undo.ok and jp.same(undo.survey, BASE)
    assert undo.inverse is not None
    redo = run(undo.inverse.op, undo.survey, undo.inverse.params)
    assert redo.ok and jp.same(redo.survey, res.survey)


def test_undo_keeps_a_reused_choice_list() -> None:
    frag = copy.deepcopy(BLOCK_FRAGMENT)
    frag["choiceLists"][0]["choices"] = copy.deepcopy(BASE["choiceLists"][1]["choices"])
    res = insert(base(), frag)
    undo = run(res.inverse.op, res.survey, res.inverse.params)
    assert undo.ok and ids_of(undo.survey, "choiceLists") == ["yesno", "spare"]


def test_insert_in_a_transaction_then_clear_source() -> None:
    ops = [
        {"op": "insert_bank_item", "params": {"fragment": BLOCK_FRAGMENT, "source": SRC}},
        {"op": "clear_source", "params": {"target": "phq2_block"}},
    ]
    tx = apply_transaction(Draft(survey=base()), ops, 0)
    assert tx.ok, [d.message for d in tx.diagnostics]
    assert "source" not in block(tx.draft.survey, "phq2_block")
    back = apply_transaction(tx.draft, tx.inverse, 1)
    assert back.ok and jp.same(back.draft.survey, BASE)


# --- clear_source -----------------------------------------------------------------------


def test_clear_source_on_a_block_and_undo() -> None:
    res = run("clear_source", base(), {"target": "b_full"})
    assert res.ok and "source" not in block(res.survey, "b_full")
    assert res.patch == [{"op": "remove", "path": "/blocks/3/source"}]
    undo = run(res.inverse.op, res.survey, res.inverse.params)
    assert undo.ok and jp.same(undo.survey, BASE)


def test_clear_source_on_a_question_and_a_page() -> None:
    s = base()
    question(s, "age")["source"] = SRC
    s["blocks"][0]["pages"][1]["source"] = {**SRC, "bank": "pg"}
    res = run("clear_source", s, {"target": "age"})
    assert res.ok and "source" not in question(res.survey, "age")
    assert res.survey["blocks"][0]["pages"][1]["source"]["bank"] == "pg"
    res = run("clear_source", res.survey, {"target": "p_demo"})
    assert res.ok and "source" not in res.survey["blocks"][0]["pages"][1]


def test_clear_source_needs_a_source_of_its_own() -> None:
    # `sorry` inherits b_full's source but carries none itself.
    res = run("clear_source", base(), {"target": "sorry"})
    assert not res.ok and codes(res) == ["op.not_applicable"]
    assert res.diagnostics[0].pointer == "/blocks/3/pages/0/items/0"
    assert codes(run("clear_source", base(), {"target": "yesno"})) == ["op.not_found"]
    assert codes(run("clear_source", base(), {"target": "n_intro"})) == ["op.not_found"]


# --- hostile fragments ------------------------------------------------------------------

IDENT = st.from_regex(r"\A[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
LONG_ID = "q" * 64
REFS = st.sampled_from(["phq2_q1", "phq2_q2", "age", "phq2_total", "self", LONG_ID, "n"])


def exprs() -> st.SearchStrategy[Any]:
    leaf = st.one_of(
        st.builds(lambda i: {"kind": "ref", "id": i}, REFS),
        st.builds(lambda v: {"kind": "int", "value": v}, st.integers(-5, 5)),
    )
    return st.recursive(
        leaf,
        lambda inner: st.builds(
            lambda a, b, o: {"kind": "arith", "op": o, "left": a, "right": b},
            inner,
            inner,
            st.sampled_from(["+", "-"]),
        ),
        max_leaves=6,
    )


def variables() -> st.SearchStrategy[list[Any]]:
    one = st.builds(
        lambda i, e: {"id": i, "kind": "computed", "expr": e},
        st.sampled_from(["phq2_total", "self", LONG_ID, "age"]),
        exprs(),
    )
    return st.lists(one, max_size=3)


def questions(n: int) -> st.SearchStrategy[list[Any]]:
    def mk(i: int) -> dict[str, Any]:
        return {"id": f"q{i}", "type": "text", "label": f"Q{i}"}

    return st.just([mk(i) for i in range(n)])


FRAGMENTS = st.one_of(
    st.just(BLOCK_FRAGMENT),
    # Cycles and self references in the scoring variables, ids at the 64-char limit.
    st.builds(lambda vs: {**BLOCK_FRAGMENT, "variables": vs}, variables()),
    # Far too many items.
    st.builds(
        lambda qs: {"page": {"id": "big", "items": qs}},
        st.sampled_from([200, 201, 10_000]).flatmap(questions),
    ),
    # A flow node, a bank item, a string, junk.
    st.just({"flow": {"type": "block", "id": "n", "block": "b"}}),
    st.just({"bankVersion": "osp-bank-item/0.1", "fragment": BLOCK_FRAGMENT}),
    st.just("fragment"),
    st.recursive(
        st.one_of(st.none(), st.integers(), st.text(max_size=5), IDENT),
        lambda inner: st.one_of(
            st.lists(inner, max_size=3),
            st.dictionaries(
                st.sampled_from(
                    [
                        "question",
                        "page",
                        "block",
                        "id",
                        "type",
                        "items",
                        "pages",
                        "choiceLists",
                        "variables",
                        "expr",
                        "kind",
                        "showIf",
                        "label",
                    ]
                ),
                inner,
                max_size=4,
            ),  # fmt: skip
        ),
        max_leaves=12,
    ),
)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(fragment=FRAGMENTS, dest=st.sampled_from([{}, {"page": "p_extra"}, {"block": "b_extra"}]))
def test_hostile_fragments_never_crash_or_half_insert(fragment: Any, dest: dict[str, Any]) -> None:
    before = base()
    res = run("insert_bank_item", before, {"fragment": fragment, "source": SRC, **dest})
    assert jp.same(before, BASE)
    assert "op.internal" not in codes(res), res.diagnostics
    if not res.ok:
        assert res.diagnostics and jp.same(res.survey, BASE)
        return
    assert parse(res.survey)[0] is not None
    assert "id.duplicate" not in codes(res)
    undo = run(res.inverse.op, res.survey, res.inverse.params)
    assert undo.ok and jp.same(undo.survey, BASE)


def test_ten_thousand_items_are_refused_fast() -> None:
    frag = {"page": {"id": "big", "items": [
        {"id": f"q{i}", "type": "text", "label": "x"} for i in range(10_000)]}}  # fmt: skip
    res = insert(base(), frag, block="b_extra")
    assert not res.ok and "at most 200" in res.diagnostics[0].message
