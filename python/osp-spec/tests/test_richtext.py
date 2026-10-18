"""Rich text helpers (planning/rich-text.md §3, task RT2): normalisation parity cases
shared with the TypeScript engine, flattening, counting, and a Hypothesis fuzz over trees
that the validator never raises on."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from osp_spec import CODES, Diagnostic, validate
from osp_spec.richtext import (
    LIMITS,
    char_count,
    features,
    flatten_text,
    has_pipes,
    normalise_text,
    plain_text,
    text_level,
    to_plain,
)

CASES = json.loads(
    (Path(__file__).parent / "cases" / "richtext-normalise.json").read_text(encoding="utf-8")
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_normalise_shared_cases(case: dict[str, Any]) -> None:
    before = json.loads(json.dumps(case["input"]))
    assert normalise_text(case["input"]) == case["output"]
    assert case["input"] == before, "normalise_text must not mutate its input"


def _rich(*blocks: dict) -> dict:
    return {"type": "rich", "blocks": list(blocks)}


def _p(*content: dict) -> dict:
    return {"type": "p", "content": list(content)}


TREE = _rich(
    {"type": "h", "level": 2, "content": [{"text": "Before you start"}]},
    _p({"text": "Hello "}, {"pipe": "name"}, {"text": "!", "marks": ["b"]}, {"br": True},
       {"text": "Read the "}, {"text": "sheet", "href": "https://example.org/s"}),
    {"type": "ul", "items": [[{"text": "one", "lang": "fr"}], [{"text": "two"}]]},
    {"type": "ol", "items": [[{"text": "first"}]]},
)  # fmt: skip


def test_to_plain_flattens_blocks_lists_breaks_and_pipes() -> None:
    assert to_plain(TREE) == (
        "Before you start\n\nHello ${name}!\nRead the sheet\n\n- one\n- two\n\n1. first"
    )
    assert to_plain("plain") == "plain"
    assert to_plain(None) == "" and to_plain(42) == ""


def test_flatten_and_plain_text() -> None:
    assert flatten_text(None) is None
    assert flatten_text("x") == "x"
    assert flatten_text({"en": "x", "de": _rich(_p({"text": "y", "marks": ["i"]}))}) == {
        "en": "x",
        "de": "y",
    }
    assert plain_text({"en": "x", "de": "y"}, "de") == "y"
    assert plain_text({"en": "x", "de": "y"}) == "x"
    assert plain_text({"en": "x"}, "fr") == "x"
    assert plain_text(TREE).startswith("Before you start")


def test_char_count_ignores_pipes_and_breaks() -> None:
    assert char_count("abc ${name} d") == 6
    assert char_count(_p()) == 0
    assert char_count(_rich(_p({"text": "ab"}, {"pipe": "x"}, {"br": True}, {"text": "c"}))) == 3
    assert LIMITS == {"block": 20_000, "stem": 2_000, "inline": 500}


def test_has_pipes_and_features() -> None:
    assert has_pipes("${a}") and not has_pipes("a")
    assert has_pipes(TREE) and not has_pipes(_rich(_p({"text": "a"})))
    assert has_pipes({"en": "a", "de": _rich(_p({"pipe": "q"}))})
    assert features(TREE) == {"heading", "bold", "break", "link", "list", "lang"}
    assert features(_rich(_p({"text": "a", "marks": ["i"]}))) == {"italic"}


def test_text_level_table() -> None:
    assert text_level("NoteQuestion", "label") == "block"
    assert text_level("SingleQuestion", "label") == "stem"
    assert text_level("MatrixQuestion", "help") == "stem"
    assert text_level("TextQuestion", "constraintMessage") == "inline"
    assert text_level("SliderQuestion", "minLabel") == "inline"
    assert text_level("Choice", "label") == "inline"
    assert text_level("Page", "title") == "inline"
    assert text_level("Consent", "text") == "block"
    assert text_level("Ending", "body") == "block"
    assert text_level("Metadata", "title") is None
    assert text_level("Block", "title") is None


# --- Fuzz: hostile trees never crash the validator ---------------------------------------

_INLINE = st.one_of(
    st.fixed_dictionaries(
        {"text": st.text(max_size=6)},
        optional={
            "marks": st.lists(st.sampled_from(["b", "i", "u", 3]), max_size=3),
            "href": st.one_of(st.text(max_size=12), st.just("https://x.org"), st.integers()),
            "lang": st.one_of(st.just("fr"), st.text(max_size=4)),
        },
    ),
    st.fixed_dictionaries(
        {"pipe": st.one_of(st.just("q1"), st.just("$trial"), st.text(max_size=6))}
    ),
    st.fixed_dictionaries({"br": st.one_of(st.just(True), st.booleans(), st.integers())}),
    st.text(max_size=4),
    st.none(),
)
_BLOCK = st.one_of(
    st.fixed_dictionaries({"type": st.just("p"), "content": st.lists(_INLINE, max_size=4)}),
    st.fixed_dictionaries(
        {
            "type": st.just("h"),
            "level": st.integers(-1, 5),
            "content": st.lists(_INLINE, max_size=3),
        }
    ),
    st.fixed_dictionaries(
        {
            "type": st.sampled_from(["ul", "ol"]),
            "items": st.lists(st.lists(_INLINE, max_size=3), max_size=3),
        }
    ),
    st.fixed_dictionaries({"type": st.text(max_size=3)}),
    st.integers(),
)
TREES = st.one_of(
    st.fixed_dictionaries({"type": st.just("rich"), "blocks": st.lists(_BLOCK, max_size=4)}),
    st.fixed_dictionaries({"type": st.just("rich"), "blocks": st.text(max_size=3)}),
    st.fixed_dictionaries({"type": st.just("rich")}),
    st.text(max_size=8),
    st.dictionaries(st.sampled_from(["en", "de", "type"]), st.text(max_size=4), max_size=2),
)


def _survey(label: Any, note: Any, choice: Any, consent: Any) -> dict:
    return {
        "specVersion": "osp-survey/0.1",
        "id": "srv",
        "metadata": {"title": "T", "languages": ["en"]},
        "consent": {"text": consent},
        "blocks": [{"id": "b1", "pages": [{"id": "p1", "items": [
            {"id": "q1", "type": "integer", "label": "Q1"},
            {"id": "q2", "type": "single", "label": label,
             "choices": [{"value": 1, "label": choice}]},
            {"id": "n1", "type": "note", "label": note},
        ]}]}],
        "flow": [{"type": "block", "id": "f1", "block": "b1"}],
    }  # fmt: skip


@settings(max_examples=300, deadline=None)
@given(TREES, TREES, TREES, TREES)
def test_fuzz_trees_never_raise(label: Any, note: Any, choice: Any, consent: Any) -> None:
    out = validate(_survey(label, note, choice, consent))
    for d in out:
        assert isinstance(d, Diagnostic)
        assert d.code in CODES and d.code != "internal.error", d
        assert d.pointer == "" or d.pointer.startswith("/")
    for value in (label, note, choice, consent):
        n = normalise_text(value)
        assert normalise_text(n) == n  # idempotent
        assert isinstance(to_plain(value), str)
        flat = flatten_text(value)
        assert flat is None or isinstance(flat, (str, dict))
        assert isinstance(char_count(value), int)


@settings(max_examples=200, deadline=None)
@given(TREES)
def test_fuzz_valid_trees_round_trip_through_normalise(tree: Any) -> None:
    """When a tree is accepted by the model, normalising it never changes what it says."""
    s = _survey(tree, "N", "C", "ok")
    if any(d.code.startswith("schema.") for d in validate(s)):
        return
    assert to_plain(normalise_text(tree)) == to_plain(tree)
