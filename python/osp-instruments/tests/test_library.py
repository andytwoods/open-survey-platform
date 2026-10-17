"""The bundled instrument library (planning/question-bank.md §3, §7, lead decision 7):
every document is a valid bank item whose fragment a survey can hold, every licence is in
the bundle allow-list with a quoted statement, a URL and an access date, and LICENCES.md
is current."""

from __future__ import annotations

import os
import re
import tomllib
from datetime import date
from pathlib import Path

import pytest
from osp_instruments import library_ids, licences_markdown, load_document, load_library, lookup
from osp_spec import Source, validate
from osp_spec.bank import check_bank_item, fragment_survey, with_instruments

PKG = Path(__file__).resolve().parents[1]
REPO = PKG.parents[1]
POLICY = tomllib.loads((REPO / "licence-policy.toml").read_text(encoding="utf-8"))
ALLOWED = set(POLICY["instruments"]["allowed"])
UPDATE = os.environ.get("OSP_UPDATE_GOLDEN") == "1"
QB_PLAN = (REPO / "planning" / "question-bank.md").read_text(encoding="utf-8")

# Items per instrument (English), as in the audit table of question-bank.md §7.0. A
# matrix row counts as one item; notes do not count.
EXPECTED_ITEMS = {
    "ace-brfss": 13,
    "gad2": 2,
    "gad7": 7,
    "mini-ipip": 20,
    "nasa-tlx": 6,
    "osp-demographics": 5,
    "phq2": 2,
    "phq9": 10,
}


def _items(doc: dict) -> int:
    n = 0
    for p in doc["fragment"]["block"]["pages"]:
        for q in p["items"]:
            if q["type"] == "matrix":
                n += len(q["rows"])
            elif q["type"] != "note":
                n += 1
    return n


def test_library_loads() -> None:
    items = load_library()
    assert [i.id for i in items] == library_ids() == sorted(EXPECTED_ITEMS)
    assert load_document("nope") is None


@pytest.mark.parametrize("instrument", sorted(EXPECTED_ITEMS))
def test_document_is_a_valid_bank_item(instrument: str) -> None:
    doc = load_document(instrument)
    assert doc is not None and doc["id"] == instrument
    assert check_bank_item(doc) == []
    survey, _ = fragment_survey(doc["fragment"])
    assert validate(survey) == []
    assert _items(doc) == EXPECTED_ITEMS[instrument]
    assert doc["languages"] == ["en"]


@pytest.mark.parametrize("instrument", sorted(EXPECTED_ITEMS))
def test_licence_evidence(instrument: str) -> None:
    """The licence is bundle-able and its evidence is complete: the holder's statement,
    the https page it was read on and the date (not in the future)."""
    doc = load_document(instrument)
    lic = doc["licence"]
    assert lic["class"] in ALLOWED, f"{instrument}: {lic['class']} may not be bundled"
    assert lic["class"] not in {"free-noncommercial", "licensed-to-lab", "unknown"}
    assert re.match(r"^https://[^\s]+$", lic["url"])
    assert date.fromisoformat(lic["evidenceDate"]) <= date(2026, 10, 17)
    assert len(lic["statement"]) > 40 and lic.get("holder")
    if lic["class"] == "author-permission":
        assert (PKG / "permissions" / lic["permission"]).is_file()
    assert doc["citation"]["text"] and doc["scoring"]["text"]
    assert re.match(r"^https://", doc["source"]["url"])
    # The audit table in the plan names every bundled instrument with its terms page.
    assert f"`{instrument}`" in QB_PLAN and lic["url"] in QB_PLAN


def test_licences_md_is_current() -> None:
    path = PKG / "LICENCES.md"
    text = licences_markdown()
    if UPDATE:
        path.write_text(text, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == text, (
        "LICENCES.md is stale: OSP_UPDATE_GOLDEN=1 uv run pytest python/osp-instruments"
    )
    for i in library_ids():
        assert f"(`{i}`)" in text


def test_policy_allow_list_is_narrow() -> None:
    assert ALLOWED <= {"public-domain", "cc0", "cc-by-4.0", "author-permission"}


def test_lookup_describes_bundled_sources() -> None:
    entry = lookup(Source(bank="phq9", version=1, library="bundled"))
    assert entry["abbreviation"] == "PHQ-9"
    assert entry["licence"]["class"] == "public-domain"
    assert entry["citation"]["doi"] == "10.1046/j.1525-1497.2001.016009606.x"
    assert lookup(Source(bank="phq9", version=2, library="bundled")) is None
    assert lookup(Source(bank="phq9", version=1, library="lab")) is None
    assert lookup(Source(bank="nope", version=1, library="bundled")) is None


def test_bundled_block_in_a_survey_lists_its_instrument() -> None:
    """A survey holding a bundled block with `source` derives `metadata.instruments`."""
    doc = load_document("gad2")
    survey, _ = fragment_survey(doc["fragment"])
    survey["blocks"][0]["source"] = {"bank": "gad2", "version": 1, "library": "bundled"}
    out = with_instruments(survey, lookup)
    [entry] = out["metadata"]["instruments"]
    assert entry["bank"] == "gad2" and entry["title"] == doc["title"]
    assert entry["licence"]["url"] == doc["licence"]["url"]
    assert validate(out) == []


def test_scoring_recipes_read_only_their_items() -> None:
    """Every scoring variable reads ids inside its own fragment (else the bank could not
    insert it), and reversed IPIP items use 6 - answer."""
    doc = load_document("mini-ipip")
    names = {v["id"] for v in doc["fragment"]["variables"]}
    assert names == {
        "mini_ipip_extraversion",
        "mini_ipip_agreeableness",
        "mini_ipip_conscientiousness",
        "mini_ipip_neuroticism",
        "mini_ipip_intellect",
    }
    text = str(doc["fragment"]["variables"])
    assert text.count("'value': 6") == 11  # 11 of the 20 Mini-IPIP items are minus-keyed
