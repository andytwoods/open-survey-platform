"""The XLSForm Markdown writer (planning/rich-text.md §8, task RT4): the rich tree as the
Enketo/Collect subset, literal markup escaped, every approximation reported."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from osp_targets.xlsform.markdown import UNESCAPABLE, escape, escape_plain, to_markdown


def _md(blocks: list[dict[str, Any]]) -> tuple[str, list[tuple[str, tuple[Any, ...]]]]:
    reports: list[tuple[str, tuple[Any, ...]]] = []
    text = to_markdown(
        {"type": "rich", "blocks": blocks},
        pipe=lambda qid, _path: "${" + qid + "}",
        report=lambda key, path: reports.append((key, path)),
    )
    return text, reports


def _p(*content: Any) -> dict[str, Any]:
    return {"type": "p", "content": list(content)}


# --- Escaping ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ("plain", "plain"),
        ("5 * 3 = 15", "5 \\* 3 = 15"),
        ("snake_case_name", "snake\\_case\\_name"),
        ("# not a heading", "\\# not a heading"),
        ("C:\\path", "C:\\\\path"),
        ("**already**", "\\*\\*already\\*\\*"),
    ],
)
def test_literal_markup_is_escaped(raw: str, escaped: str) -> None:
    assert escape(raw) == escaped


def test_plain_string_escapes_outside_pipes() -> None:
    assert (
        escape_plain("Hi ${first_name}, score *${s_1}*") == "Hi ${first_name}, score \\*${s_1}\\*"
    )


@pytest.mark.parametrize("text", ["a < b", "<b>x</b>", "[go](https://x)", "- item", "x\n1. one"])
def test_unescapable_markup_is_detected(text: str) -> None:
    assert UNESCAPABLE.search(text)


@pytest.mark.parametrize("text", ["5 * 3", "a_b", "# h", "1.5 points", "a - b", "x\n\n-no space"])
def test_escapable_or_harmless_text_is_not_flagged(text: str) -> None:
    assert UNESCAPABLE.search(text) is None


# --- The tree --------------------------------------------------------------------------------


def test_marks_links_breaks_and_pipes() -> None:
    text, reports = _md(
        [
            _p(
                {"text": "Thinking about "},
                {"text": "last week", "marks": ["b"]},
                {"text": ", how often did "},
                {"pipe": "name"},
                {"text": " "},
                {"text": "really", "marks": ["i"]},
                {"text": " "},
                {"text": "both", "marks": ["b", "i"]},
                {"br": True},
                {"text": "see the "},
                {"text": "sheet", "href": "https://example.org/info"},
                {"text": "?"},
            )
        ]
    )
    assert text == (
        "Thinking about **last week**, how often did ${name} *really* *__both__*\n"
        "see the [sheet](https://example.org/info)?"
    )
    assert reports == []


def test_markers_hug_the_text() -> None:
    """Enketo and Collect do not read `** text**`: white space stays outside the markers,
    an all-space run stays as it is, and a newline inside a run splits the marks."""
    text, _ = _md([_p({"text": " spaced ", "marks": ["b"]}, {"text": "   ", "marks": ["i"]})])
    assert text == " **spaced**    "
    text, _ = _md([_p({"text": "one\ntwo", "marks": ["i"]})])
    assert text == "*one*\n*two*"


def test_adjacent_runs_with_the_same_href_are_one_link() -> None:
    text, _ = _md(
        [
            _p(
                {"text": "the ", "href": "https://x.org/"},
                {"text": "info", "marks": ["b"], "href": "https://x.org/"},
                {"text": " sheet", "href": "https://x.org/"},
                {"text": " and ", "href": "https://y.org/"},
            )
        ]
    )
    assert text == "[the **info** sheet](https://x.org/)[ and ](https://y.org/)"


def test_blocks_headings_and_lists() -> None:
    text, reports = _md(
        [
            {"type": "h", "level": 1, "content": [{"text": "Before you start"}]},
            _p({"text": "Read it."}),
            {"type": "h", "level": 3, "content": [{"text": "Deep"}]},
            {"type": "ul", "items": [[{"text": "one"}], [{"text": "two", "marks": ["b"]}]]},
            {"type": "ol", "items": [[{"text": "first"}], [{"pipe": "q"}]]},
        ]
    )
    assert text == (
        "## Before you start\n\nRead it.\n\n#### Deep\n\n- one\n- **two**\n\n1. first\n2. ${q}"
    )
    assert reports == []


def test_numbered_list_first_starts_after_a_newline() -> None:
    """Enketo reads `1. ` lines as a list only after a newline (numbered labels are common)."""
    text, _ = _md([{"type": "ol", "items": [[{"text": "a"}], [{"text": "b"}]]}])
    assert text == "\n1. a\n2. b"


def test_break_in_a_list_item_is_a_space_and_reported() -> None:
    text, reports = _md(
        [
            {
                "type": "ul",
                "items": [[{"text": "a"}, {"br": True}, {"text": "b\nc"}], [{"text": "d"}]],
            }
        ]
    )
    assert text == "- a b c\n- d"
    assert reports == [
        ("$rich.listBreak", ("blocks", 0, "items", 0, 1)),
        ("$rich.listBreak", ("blocks", 0, "items", 0, 2)),
    ]


def test_link_that_markdown_cannot_hold_is_text_plus_url() -> None:
    text, reports = _md(
        [
            _p({"text": "a]b", "href": "https://x.org/"}),
            _p({"text": "see", "href": "https://x.org/a)b"}),
            _p({"text": "two", "href": "https://x.org/"}, {"br": True, "href": "https://x.org/"}),
        ]
    )
    assert text == "a]b (https://x.org/)\n\nsee (https://x.org/a)b)\n\ntwo\n (https://x.org/)"
    assert reports == [
        ("$rich.linkSyntax", ("blocks", 0, "content", 0)),
        ("$rich.linkSyntax", ("blocks", 1, "content", 0)),
        ("$rich.linkSyntax", ("blocks", 2, "content", 0)),
    ]


def test_literal_markup_in_runs_is_escaped_and_the_rest_reported() -> None:
    text, reports = _md([_p({"text": "2 * 3 <b>", "marks": ["b"]}, {"text": " \x07"})])
    assert text == "**2 \\* 3 <b>** \x07"
    assert reports == [
        ("$text.markup", ("blocks", 0, "content", 0)),
        ("$text.controlCharacters", ("blocks", 0, "content", 1)),
    ]


def test_lang_span_keeps_its_text() -> None:
    text, reports = _md([_p({"text": "Merci", "lang": "fr", "marks": ["i"]}, {"text": "!"})])
    assert text == "*Merci*!"
    assert reports == []  # the loss is the TextRun.lang capability row's (feature_uses)


# --- Hostile input: never raises ------------------------------------------------------------

_json = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=8),
    lambda c: st.lists(c, max_size=4) | st.dictionaries(st.text(max_size=6), c, max_size=4),
    max_leaves=12,
)
_node = st.one_of(
    _json,
    st.fixed_dictionaries(
        {"text": st.text(max_size=10)},
        optional={
            "marks": st.lists(st.sampled_from(["b", "i", "x"]), max_size=3) | _json,
            "href": st.text(max_size=12) | _json,
            "lang": st.text(max_size=4) | _json,
        },
    ),
    st.fixed_dictionaries({"pipe": st.text(max_size=6) | _json}),
    st.fixed_dictionaries({"br": st.just(True) | _json}),
)
_block = st.one_of(
    _json,
    st.fixed_dictionaries({"type": st.just("p"), "content": st.lists(_node, max_size=5) | _json}),
    st.fixed_dictionaries(
        {
            "type": st.just("h"),
            "level": st.integers(-2, 9) | _json,
            "content": st.lists(_node) | _json,
        }
    ),
    st.fixed_dictionaries(
        {
            "type": st.sampled_from(["ul", "ol"]),
            "items": st.lists(st.lists(_node, max_size=3), max_size=3) | _json,
        }
    ),
)


@given(
    st.fixed_dictionaries({"type": st.just("rich"), "blocks": st.lists(_block, max_size=5) | _json})
)
def test_never_raises_on_hostile_trees(tree: dict[str, Any]) -> None:
    text = to_markdown(tree, pipe=lambda qid, _p: "${" + qid + "}", report=lambda _k, _p: None)
    assert isinstance(text, str)
