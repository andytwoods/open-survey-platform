"""Question bank documents (planning/question-bank.md §2): fragments, bank items, the
`source` provenance field and the derived `metadata.instruments`. Invented test data."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from osp_spec import parse, validate
from osp_spec.bank import (
    BANK_CODES,
    MAX_ITEMS,
    check_bank_item,
    check_fragment,
    extract_fragment,
    fragment_checksum,
    fragment_languages,
    fragment_survey,
    instrument_entry,
    with_instruments,
)

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"


def ref(qid: str) -> dict[str, Any]:
    return {"kind": "ref", "id": qid}


def add(*ids: str) -> dict[str, Any]:
    node: dict[str, Any] = ref(ids[0])
    for i in ids[1:]:
        node = {"kind": "arith", "op": "+", "left": node, "right": ref(i)}
    return node


def survey() -> dict[str, Any]:
    """Two blocks: `demo` is a 2-item invented instrument with a scoring variable; `other`
    asks an unrelated question that the instrument's second item depends on."""
    return {
        "specVersion": "osp-survey/0.1",
        "id": "srv",
        "metadata": {"title": "T", "languages": ["en", "de"]},
        "choiceLists": [
            {"id": "agree4", "choices": [
                {"value": 0, "label": {"en": "Never", "de": "Nie"}},
                {"value": 1, "label": {"en": "Often", "de": "Oft"}},
            ]},
            {"id": "unused", "choices": [{"value": 1, "label": "x"}]},
        ],
        "variables": [
            {"id": "demo_total", "kind": "computed", "expr": add("demo_q1", "demo_q2")},
            {"id": "demo_double", "kind": "computed", "expr": add("demo_total", "demo_total")},
            {"id": "mixed", "kind": "computed", "expr": add("demo_q1", "age")},
            {"id": "const", "kind": "computed", "expr": {"kind": "int", "value": 1}},
        ],
        "blocks": [
            {"id": "other", "pages": [{"id": "p_other", "items": [
                {"id": "age", "type": "integer", "label": "Age"},
            ]}]},
            {"id": "demo", "title": "Demo scale", "pages": [{"id": "p_demo", "items": [
                {"id": "demo_q1", "type": "single", "label": {"en": "Item one", "de": "Eins"},
                 "choiceList": "agree4"},
                {"id": "demo_q2", "type": "single", "choiceList": "agree4",
                 "label": {"en": "Item two (age ${age})", "de": "Zwei"},
                 "showIf": {"kind": "answered", "ref": ref("age")}},
            ]}]},
        ],
        "flow": [
            {"type": "block", "id": "f1", "block": "other"},
            {"type": "block", "id": "f2", "block": "demo"},
        ],
    }  # fmt: skip


def codes(diags: list) -> list[str]:
    return [d.code for d in diags]


# -- extract_fragment -----------------------------------------------------------------


def test_extract_block_carries_lists_and_scoring() -> None:
    s = survey()
    before = copy.deepcopy(s)
    frag, diags = extract_fragment(s, "demo")
    assert s == before  # never mutates the survey
    assert frag is not None
    assert set(frag) == {"choiceLists", "variables", "block"}
    assert [cl["id"] for cl in frag["choiceLists"]] == ["agree4"]
    # demo_total reads only fragment items; demo_double reads demo_total (transitive);
    # `mixed` reads `age` from outside and `const` reads nothing: both stay behind.
    assert [v["id"] for v in frag["variables"]] == ["demo_total", "demo_double"]
    q2 = frag["block"]["pages"][0]["items"][1]
    assert "showIf" not in q2
    assert q2["label"] == {"en": "Item two (age )", "de": "Zwei"}
    assert codes(diags) == ["bank.external_ref", "bank.external_ref"]
    assert {d.pointer for d in diags} == {
        "/blocks/1/pages/0/items/1/showIf",
        "/blocks/1/pages/0/items/1/label/en",
    }
    assert check_fragment(frag) == []


def test_extract_page_and_question() -> None:
    frag, diags = extract_fragment(survey(), "p_demo")
    assert frag is not None and "page" in frag and len(codes(diags)) == 2
    frag, diags = extract_fragment(survey(), "demo_q1")
    assert frag is not None and frag["question"]["id"] == "demo_q1"
    assert frag["variables"] == []  # demo_total also reads demo_q2: outside a lone q1
    assert [cl["id"] for cl in frag["choiceLists"]] == ["agree4"]
    assert diags == []


def test_extract_internal_refs_are_kept() -> None:
    s = survey()
    q2 = s["blocks"][1]["pages"][0]["items"][1]
    q2["showIf"] = {"kind": "answered", "ref": ref("demo_q1")}
    q2["label"] = "Again: ${demo_q1} ${$trial}"
    frag, diags = extract_fragment(s, "demo")
    assert diags == []
    kept = frag["block"]["pages"][0]["items"][1]
    assert kept["showIf"] == q2["showIf"] and kept["label"] == q2["label"]


def test_extract_matrix_rows_count_as_inside() -> None:
    s = survey()
    s["blocks"][1]["pages"][0]["items"] = [
        {"id": "m", "type": "matrix", "label": "Grid", "choiceList": "agree4",
         "rows": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]},
    ]  # fmt: skip
    s["variables"] = [{"id": "m_sum", "kind": "computed", "expr": add("m_a", "m_b")}]
    frag, diags = extract_fragment(s, "demo")
    assert diags == [] and [v["id"] for v in frag["variables"]] == ["m_sum"]


@pytest.mark.parametrize("target", ["nope", "f1", "demo_total", 7, None])
def test_extract_unknown_target(target: Any) -> None:
    frag, diags = extract_fragment(survey(), target)
    assert frag is None and codes(diags) == ["bank.target_not_found"]


@pytest.mark.parametrize("bad", [None, [], "x", {"specVersion": "osp-survey/9"}])
def test_extract_invalid_survey(bad: Any) -> None:
    frag, diags = extract_fragment(bad, "demo")
    assert frag is None and codes(diags)[0] == "bank.invalid_survey"


def test_extract_every_fixture_block_round_trips() -> None:
    """Every block of every fixture extracts to a fragment the checker accepts, and the
    throwaway survey built from it validates without errors."""
    n = 0
    for path in sorted(FIXTURES.glob("*/survey.json")):
        s = json.loads(path.read_text(encoding="utf-8"))
        if parse(s)[0] is None:
            continue
        for b in s.get("blocks") or []:
            frag, diags = extract_fragment(s, b["id"])
            assert frag is not None, (path.parent.name, b["id"], diags)
            assert not [d for d in check_fragment(frag) if d.severity == "error"]
            n += 1
    assert n > 20


# -- check_fragment -------------------------------------------------------------------


def test_fragment_round_trips_through_json() -> None:
    frag, _ = extract_fragment(survey(), "demo")
    again = json.loads(json.dumps(frag))
    assert again == frag and check_fragment(again) == []
    assert fragment_checksum(again) == fragment_checksum(frag)
    assert fragment_checksum(again).startswith("sha256:") and len(fragment_checksum(frag)) == 71
    frag["block"]["title"] = "edited"
    assert fragment_checksum(frag) != fragment_checksum(again)


def test_fragment_languages() -> None:
    frag, _ = extract_fragment(survey(), "demo")
    assert fragment_languages(frag) == ["en", "de"]
    s, where = fragment_survey(frag)
    assert s["metadata"]["languages"] == ["en", "de"] and where == "/blocks/0"
    q, _ = extract_fragment(survey(), "demo_q1")
    s, where = fragment_survey(q)
    assert where == "/blocks/0/pages/0/items/0" and validate(s) == []


def test_check_fragment_errors() -> None:
    frag, _ = extract_fragment(survey(), "demo")
    both = {**frag, "question": {"id": "x", "type": "note", "label": "n"}}
    assert codes(check_fragment(both)) == ["bank.kind_mismatch"]
    assert codes(check_fragment({"choiceLists": []})) == ["bank.kind_mismatch"]
    assert codes(check_fragment("x")) == ["bank.fragment_invalid"]
    bad = copy.deepcopy(frag)
    bad["block"]["pages"][0]["items"][0]["type"] = "nonsense"
    assert codes(check_fragment(bad))[0] == "bank.fragment_invalid"
    # Not a computed variable: a fragment carries scoring recipes only.
    emb = {**frag, "variables": [{"id": "e", "kind": "embedded", "param": "e"}]}
    assert codes(check_fragment(emb))[0] == "bank.fragment_invalid"
    # A dangling reference is what the survey validator reports, pointed into the fragment.
    dang = copy.deepcopy(frag)
    dang["block"]["pages"][0]["items"][0]["showIf"] = {"kind": "answered", "ref": ref("zz")}
    got = check_fragment(dang)
    assert [(d.code, d.pointer) for d in got] == [
        ("ref.unknown", "/block/pages/0/items/0/showIf")
    ]
    many = {"question": None, "page": {"id": "p", "items": [
        {"id": f"n{i}", "type": "note", "label": "x"} for i in range(MAX_ITEMS + 1)]}}  # fmt: skip
    assert codes(check_fragment(many)) == ["bank.too_large"]


# -- bank items -----------------------------------------------------------------------


def item(**over: Any) -> dict[str, Any]:
    frag, _ = extract_fragment(survey(), "demo")
    doc = {
        "bankVersion": "osp-bank-item/0.1",
        "id": "demo2",
        "version": 1,
        "kind": "block",
        "title": "Demo two-item scale",
        "abbreviation": "DEMO-2",
        "tags": ["demo"],
        "languages": ["en", "de"],
        "licence": {
            "class": "cc0",
            "holder": "Test",
            "statement": "Invented for tests.",
            "url": "https://example.org/terms",
            "evidenceDate": "2026-10-17",
        },
        "citation": {"text": "Invented (2026)."},
        "scoring": {"text": "Sum of both items."},
        "fragment": frag,
    }
    doc.update(over)
    return doc


def test_bank_item_valid() -> None:
    assert check_bank_item(item()) == []
    assert (
        check_bank_item(item(provenance={"from": {"library": "bundled", "id": "x", "version": 1}}))
        == []
    )


def test_bank_item_errors() -> None:
    assert codes(check_bank_item(item(kind="page"))) == ["bank.kind_mismatch"]
    assert codes(check_bank_item(item(licence={"class": "mine"})))[0] == "bank.fragment_invalid"
    assert codes(check_bank_item(item(tags=["t"] * 21)))[0] == "bank.fragment_invalid"
    assert codes(check_bank_item(item(description="x" * 300_000))) == ["bank.too_large"]
    assert codes(check_bank_item({1, 2})) == ["bank.fragment_invalid"]
    broken = item()
    broken["fragment"]["block"]["pages"][0]["items"][0]["choiceList"] = "missing"
    got = check_bank_item(broken)
    assert got[0].code == "ref.unknown_choice_list"
    assert got[0].pointer.startswith("/fragment/block/pages/0/items/0")


def test_every_bank_code_is_exercised() -> None:
    # Every code above appears in at least one assertion of this module.
    text = Path(__file__).read_text(encoding="utf-8")
    assert all(f'"{code}"' in text for code in BANK_CODES)


# -- source and metadata.instruments --------------------------------------------------

SRC = {"bank": "demo2", "version": 1, "library": "bundled"}


def with_source(s: dict[str, Any], where: str = "block") -> dict[str, Any]:
    s = copy.deepcopy(s)
    block = s["blocks"][1]
    target = {
        "block": block,
        "page": block["pages"][0],
        "question": block["pages"][0]["items"][0],
    }[where]
    target["source"] = {**SRC, "item": "demo_q1", "checksum": "sha256:" + "0" * 64}
    return s


@pytest.mark.parametrize("where", ["block", "page", "question"])
def test_source_is_valid_everywhere(where: str) -> None:
    assert validate(with_source(survey(), where)) == validate(survey())


@pytest.mark.parametrize(
    "bad",
    [
        {"bank": "x", "version": 0, "library": "bundled"},
        {"bank": "x", "version": 1, "library": "elsewhere"},
        {"bank": "", "version": 1, "library": "lab"},
        {"bank": "x", "version": 1, "library": "lab", "checksum": "md5:1"},
        {"bank": "x", "version": 1, "library": "lab", "extra": 1},
    ],
)
def test_source_rejects_bad_values(bad: dict) -> None:
    s = survey()
    s["blocks"][1]["source"] = bad
    assert parse(s)[0] is None


def lookup(src: Any) -> dict[str, Any] | None:
    if src.bank == "demo2":
        return instrument_entry(item())
    return None


def test_with_instruments_derives_from_sources() -> None:
    s = with_source(survey())
    out = with_instruments(s, lookup)
    assert "instruments" not in s["metadata"]  # a new document
    assert out["metadata"]["instruments"] == [
        {
            "bank": "demo2",
            "version": 1,
            "library": "bundled",
            "title": "Demo two-item scale",
            "abbreviation": "DEMO-2",
            "licence": {
                "class": "cc0",
                "holder": "Test",
                "statement": "Invented for tests.",
                "url": "https://example.org/terms",
                "evidenceDate": "2026-10-17",
            },
            "citation": {"text": "Invented (2026)."},
        }
    ]
    assert validate(out) == validate(survey())
    assert with_instruments(out, lookup) == out  # idempotent


def test_with_instruments_keeps_captured_entries_and_drops_stale() -> None:
    s = with_source(survey(), "question")
    s["metadata"]["instruments"] = [
        {**SRC, "title": "Captured at insert"},
        {"bank": "gone", "version": 2, "library": "lab", "title": "Deleted since"},
    ]
    out = with_instruments(s)  # no lookup: the captured entry stands
    assert out["metadata"]["instruments"] == [{**SRC, "title": "Captured at insert"}]
    # A source nobody describes still gets listed by reference.
    s["blocks"][0]["source"] = {"bank": "lab-uuid-1", "version": 3, "library": "lab"}
    out = with_instruments(s)
    assert out["metadata"]["instruments"][0] == {
        "bank": "lab-uuid-1",
        "version": 3,
        "library": "lab",
    }
    # No sources: the field goes.
    assert "instruments" not in with_instruments(survey() | {"metadata": s["metadata"]})["metadata"]


def test_two_versions_are_two_instruments() -> None:
    s = with_source(survey(), "question")
    s["blocks"][1]["pages"][0]["items"][1]["source"] = {**SRC, "version": 2}
    out = with_instruments(s)
    assert [(e["bank"], e["version"]) for e in out["metadata"]["instruments"]] == [
        ("demo2", 1),
        ("demo2", 2),
    ]


@pytest.mark.parametrize("bad", [None, 1, [], {"metadata": 3}])
def test_with_instruments_never_raises(bad: Any) -> None:
    assert with_instruments(bad, lookup) == bad


# -- hostile input --------------------------------------------------------------------

json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=8),
    lambda c: st.lists(c, max_size=4) | st.dictionaries(st.text(max_size=8), c, max_size=4),
    max_leaves=20,
)


@settings(max_examples=150, deadline=None)
@given(json_values)
def test_check_fragment_never_raises(data: Any) -> None:
    for d in check_fragment(data):
        assert d.code in BANK_CODES or d.severity in ("error", "warning", "info")
    check_bank_item(data)
    extract_fragment(data, "demo")
    with_instruments(data)


@settings(max_examples=60, deadline=None)
@given(st.sampled_from(["demo", "p_demo", "demo_q1", "demo_q2", "other", "age"]), json_values)
def test_extract_with_hostile_fields(target: str, junk: Any) -> None:
    s = survey()
    s["blocks"][1]["pages"][0]["items"][0]["help"] = junk
    frag, diags = extract_fragment(s, target)
    assert frag is None or not [d for d in check_fragment(frag) if d.severity == "error"]
