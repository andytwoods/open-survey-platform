"""The LimeSurvey HTML writer (planning/rich-text.md §8, task RT4): the rich tree as our
own tags only, every text through the escaper, a lone paragraph unwrapped."""

from __future__ import annotations

import html
from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from osp_targets.lss.html import is_block_html, to_html


def _html(blocks: list[dict[str, Any]]) -> str:
    return to_html(
        {"type": "rich", "blocks": blocks},
        escape=lambda s, _path: html.escape(s, quote=False).replace("\n", "<br />"),
        pipe=lambda qid, _path: "{" + qid + "}",
        report=lambda _key, _path: None,
    )


def _p(*content: Any) -> dict[str, Any]:
    return {"type": "p", "content": list(content)}


def test_lone_paragraph_has_no_wrapper() -> None:
    assert _html([_p({"text": "Apple", "marks": ["b"]}, {"text": " & pear"})]) == (
        "<strong>Apple</strong> &amp; pear"
    )


def test_marks_links_lang_breaks_and_pipes() -> None:
    out = _html(
        [
            _p(
                {"text": "Hello ", "marks": ["b"]},
                {"pipe": "name"},
                {"text": ", "},
                {"text": "both", "marks": ["b", "i"]},
                {"br": True},
                {"text": "Merci", "lang": "fr", "marks": ["i"]},
                {"text": " the ", "href": "https://example.org/?a=1&b=2"},
                {"text": "sheet", "marks": ["b"], "href": "https://example.org/?a=1&b=2"},
                {"text": " <now>"},
            )
        ]
    )
    assert out == (
        "<strong>Hello </strong>{name}, <strong><em>both</em></strong><br />"
        '<span lang="fr"><em>Merci</em></span>'
        '<a href="https://example.org/?a=1&amp;b=2" target="_blank" rel="noopener noreferrer">'
        " the <strong>sheet</strong></a> &lt;now&gt;"
    )


def test_blocks_headings_and_lists() -> None:
    out = _html(
        [
            {"type": "h", "level": 1, "content": [{"text": "Before"}]},
            _p({"text": "Read it."}),
            {"type": "h", "level": 3, "content": [{"text": "Deep"}]},
            {"type": "ul", "items": [[{"text": "one"}], [{"text": "two", "marks": ["i"]}]]},
            {"type": "ol", "items": [[{"pipe": "q"}]]},
        ]
    )
    assert out == (
        "<h3>Before</h3><p>Read it.</p><h5>Deep</h5><ul><li>one</li><li><em>two</em></li></ul>"
        "<ol><li>{q}</li></ol>"
    )
    assert is_block_html(out)
    assert not is_block_html("plain &lt;p&gt;")


def test_only_https_links_are_written() -> None:
    assert _html([_p({"text": "x", "href": "javascript:alert(1)"})]) == "x"
    assert _html([_p({"text": "x", "href": "https://ok.example"})]).startswith('<a href="https://')


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
def test_never_raises_and_writes_only_our_tags(tree: dict[str, Any]) -> None:
    out = _html(tree["blocks"] if isinstance(tree["blocks"], list) else [])
    assert isinstance(out, str)
    # Every `<` opens one of our tags (text is escaped); every `href` is https.
    import re

    for tag in re.findall(r"<(/?[a-z0-9]+)", out):
        assert tag.lstrip("/") in {
            "p",
            "h3",
            "h4",
            "h5",
            "ul",
            "ol",
            "li",
            "strong",
            "em",
            "a",
            "span",
            "br",
        }
    for href in re.findall(r'href="([^"]*)"', out):
        assert href.startswith("https://")
