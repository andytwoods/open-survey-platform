"""Instrument stubs and the licensed-copy composer (planning/question-bank.md §1.7, §6;
task QB5): every stub is a valid, text-free recipe; composing a lab's own items from it
gives a fragment a survey can hold, with the recipe as computed variables that evaluate
the way the literature says (reversal, means, SUS's offset and factor)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from osp_instruments import (
    ComposeRequest,
    compose_fragment,
    load_stub,
    load_stub_document,
    load_stubs,
    parse_items,
    prefix_from,
    request_from_stub,
    stub_ids,
)
from osp_spec import validate
from osp_spec.bank import check_fragment, fragment_survey
from osp_spec.model import LICENCE_CLASSES

PKG = Path(__file__).resolve().parents[1]
STUBS_DIR = PKG / "src" / "osp_instruments" / "stubs"


def _items(stub, n: int | None = None) -> list[str]:
    """Placeholder item lines (never real text): `Item i`, with per-item options when the
    stub's items each have their own wording."""
    n = stub.itemCount if n is None else n
    opts = ""
    if stub.response.kind == "per-item":
        opts = " | " + " | ".join(
            f"opt {v}" for v in range(stub.response.min, stub.response.max + 1)
        )
    return [f"Item {i}{opts}" for i in range(1, n + 1)]


def test_stubs_load() -> None:
    stubs = load_stubs()
    assert [s.id for s in stubs] == stub_ids() and len(stubs) >= 25
    assert load_stub("nope") is None and load_stub_document("nope") is None
    assert {s.terms for s in stubs} == {"ask", "licensed"}
    assert load_stub_document("bdi-ii")["abbreviation"] == "BDI-II"


@pytest.mark.parametrize("stub_id", stub_ids())
def test_stub_is_complete_and_text_free(stub_id: str) -> None:
    doc = load_stub_document(stub_id)
    raw = json.dumps(doc)
    # No item text: a stub is metadata and a recipe. No bank-item keys either.
    assert "fragment" not in doc and "licence" not in doc
    assert doc["terms"] in ("ask", "licensed")
    assert doc["terms"] not in LICENCE_CLASSES  # a stub's terms are not a bank licence class
    assert doc["citation"]["text"] and doc["holder"]["name"] and doc["scoring"]["text"]
    assert "check it against the manual" in doc["scoring"]["text"]
    if doc["holder"]["url"]:
        assert re.match(r"^https://[^\s]+$", doc["holder"]["url"])
    if doc["citation"]["doi"]:
        assert doc["citation"]["doi"].startswith("10.")
    assert len(raw) < 6000


@pytest.mark.parametrize("stub_id", stub_ids())
@pytest.mark.parametrize("layout", ["matrix", "single"])
def test_stub_composes_into_a_valid_fragment(stub_id: str, layout: str) -> None:
    stub = load_stub(stub_id)
    req = request_from_stub(stub, _items(stub), layout=layout, stem="How often…")
    fragment, diags = compose_fragment(req)
    assert fragment is not None, diags
    assert diags == []
    assert [d for d in check_fragment(fragment) if d.severity == "error"] == []
    survey, _ = fragment_survey(fragment)
    assert validate(survey) == []
    ids = {v["id"] for v in fragment["variables"]}
    p = req.prefix
    if stub.scoring.aggregate is None:
        assert ids == set()
    else:
        expected = {f"{p}_{k}" for k in stub.scoring.subscales} | (
            {f"{p}_total"} if stub.scoring.total else set()
        )
        assert ids == expected
    # Items count as the stub says, whichever layout.
    page = fragment["block"]["pages"][0]
    n = sum(len(q["rows"]) if q["type"] == "matrix" else q["type"] != "note" for q in page["items"])
    assert n == stub.itemCount
    if stub.response.kind == "per-item":
        assert all(q["type"] != "matrix" for q in page["items"])
        assert all("choices" in q for q in page["items"] if q["type"] == "single")
        assert fragment["choiceLists"] == []


def test_stub_rejects_wrong_item_count() -> None:
    stub = load_stub("pss-10")
    fragment, diags = compose_fragment(request_from_stub(stub, _items(stub, 4)))
    assert fragment is None
    assert {d.code for d in diags} == {"bank.compose_scoring"}  # reversed items 5, 7, 8 missing


def test_per_item_stub_needs_options_on_every_line() -> None:
    stub = load_stub("bdi-ii")
    plain = [f"Item {i}" for i in range(1, 22)]
    fragment, diags = compose_fragment(request_from_stub(stub, plain))
    assert fragment is None and {d.code for d in diags} == {"bank.compose_items"}
    assert "its own options" in diags[0].message


def _eval_sum_expr(expr: dict, values: dict[str, int]) -> float:
    k = expr["kind"]
    if k == "ref":
        return values[expr["id"]]
    if k == "int":
        return expr["value"]
    if k == "decimal":
        return float(expr["value"])
    a, b = _eval_sum_expr(expr["left"], values), _eval_sum_expr(expr["right"], values)
    op = expr["op"]
    if op == "/":
        return a / b
    return {"+": a + b, "-": a - b, "*": a * b}[op]


def test_recipes_follow_the_literature() -> None:
    # PSS-10: items 4, 5, 7, 8 reversed on 0-4; all 4s -> 6*4 + 4*0 = 24.
    pss = load_stub("pss-10")
    frag, _ = compose_fragment(request_from_stub(pss, _items(pss)))
    total = next(v for v in frag["variables"] if v["id"].endswith("_total"))
    vals = {f"pss_10_q{i}": 4 for i in range(1, 11)}
    assert _eval_sum_expr(total["expr"], vals) == 24
    # SUS: all odd 5, all even 1 -> every item contributes 4 -> (40 - 10) * 2.5 = 75? no:
    # odd (5-1)=4 each x5 = 20, even (5-1)=4 each x5 = 20 -> 40 * 2.5 = 100.
    sus = load_stub("sus")
    frag, _ = compose_fragment(request_from_stub(sus, _items(sus)))
    total = next(v for v in frag["variables"] if v["id"].endswith("_total"))
    vals = {f"sus_q{i}": (5 if i % 2 else 1) for i in range(1, 11)}
    assert _eval_sum_expr(total["expr"], vals) == 100
    vals = {f"sus_q{i}": 3 for i in range(1, 11)}
    assert _eval_sum_expr(total["expr"], vals) == 50
    # WHO-5: sum x 4.
    who = load_stub("who-5")
    frag, _ = compose_fragment(request_from_stub(who, _items(who)))
    total = next(v for v in frag["variables"] if v["id"].endswith("_total"))
    assert _eval_sum_expr(total["expr"], {f"who_5_q{i}": 3 for i in range(1, 6)}) == 60
    # TIPI: pair means after reversal; no total.
    tipi = load_stub("tipi")
    frag, _ = compose_fragment(request_from_stub(tipi, _items(tipi)))
    ids = [v["id"] for v in frag["variables"]]
    assert "tipi_total" not in ids and "tipi_extraversion" in ids
    extra = next(v for v in frag["variables"] if v["id"] == "tipi_extraversion")
    assert _eval_sum_expr(extra["expr"], {"tipi_q1": 7, "tipi_q6": 1}) == 7  # 6 reversed: 8-1


def test_prefix_from() -> None:
    assert prefix_from("BDI-II") == "bdi_ii"
    assert prefix_from("10-item scale") == "i_10_item_scale"
    assert prefix_from("***") == "instrument"
    assert len(prefix_from("x" * 100)) == 40


def test_parse_items_and_blank_requests() -> None:
    items = parse_items(["  First  item ", "", "Second | a | b | c", 7])  # type: ignore[list-item]
    assert [i.label for i in items] == ["First item", "Second"]
    assert items[1].options == ["a", "b", "c"]
    frag, diags = compose_fragment(
        ComposeRequest(
            prefix="own",
            title="Own scale",
            items=["One", "Two", "Three"],
            layout="matrix",
            scale_min=1,
            scale_max=3,
            labels=["Low", "Mid", "High"],
            reversed=[2],
            aggregate="mean",
            language="en",
        )
    )
    assert frag is not None and diags == []
    assert frag["choiceLists"][0]["choices"][0]["label"] == {"en": "Low"}
    assert frag["block"]["pages"][0]["items"][0]["rows"][1]["label"] == {"en": "Two"}
    assert [d for d in check_fragment(frag) if d.severity == "error"] == []


@pytest.mark.parametrize(
    ("req", "codes"),
    [
        (ComposeRequest(prefix="1bad", title="t", items=["a"]), {"bank.compose_prefix"}),
        (ComposeRequest(prefix="and", title="t", items=["a"]), {"bank.compose_prefix"}),
        (ComposeRequest(prefix="ok", title=" ", items=["a"]), {"bank.compose_title"}),
        (ComposeRequest(prefix="ok", title="t", items=[]), {"bank.compose_items"}),
        (ComposeRequest(prefix="ok", title="t", items=["a"] * 201), {"bank.too_large"}),
        (
            ComposeRequest(prefix="ok", title="t", items=["a"], scale_min=3, scale_max=3),
            {"bank.compose_scale"},
        ),
        (ComposeRequest(prefix="ok", title="t", items=["a"], labels=["x"]), {"bank.compose_scale"}),
        (
            ComposeRequest(prefix="ok", title="t", items=["a | x | y", "b"]),
            {"bank.compose_items", "bank.compose_layout"},
        ),
        (
            ComposeRequest(prefix="ok", title="t", items=["a | x | y"], layout="single"),
            {"bank.compose_items"},
        ),
        (
            ComposeRequest(prefix="ok", title="t", items=["a"], reversed=[2]),
            {"bank.compose_scoring"},
        ),
        (
            ComposeRequest(prefix="ok", title="t", items=["a"], subscales={"s": []}),
            {"bank.compose_scoring"},
        ),
        (
            ComposeRequest(prefix="ok", title="t", items=["a"], factor="lots"),
            {"bank.compose_scoring"},
        ),
        (
            ComposeRequest(prefix="ok", title="t", items=["a"], aggregate="median"),
            {"bank.compose_scoring"},
        ),  # type: ignore[arg-type]
    ],
)
def test_compose_refusals(req: ComposeRequest, codes: set[str]) -> None:
    fragment, diags = compose_fragment(req)
    assert fragment is None
    assert {d.code for d in diags} == codes


def test_per_item_options_make_single_questions_with_inline_choices() -> None:
    req = ComposeRequest(
        prefix="pi",
        title="Per item",
        items=["Q1 | never | sometimes", "Q2 | no | yes"],
        layout="single",
        scale_min=0,
        scale_max=1,
        stem="Pick one per line.",
    )
    frag, diags = compose_fragment(req)
    assert frag is not None and diags == []
    items = frag["block"]["pages"][0]["items"]
    assert items[0] == {"id": "pi_stem", "type": "note", "label": "Pick one per line."}
    assert items[1]["choices"] == [
        {"value": 0, "label": "never"},
        {"value": 1, "label": "sometimes"},
    ]
    assert frag["choiceLists"] == []
    assert [d for d in check_fragment(frag) if d.severity == "error"] == []


def test_stub_files_are_the_loaded_documents() -> None:
    files = sorted(p.stem for p in STUBS_DIR.glob("*.json"))
    assert files == stub_ids()
