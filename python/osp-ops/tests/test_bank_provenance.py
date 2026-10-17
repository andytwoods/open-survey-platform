"""Question-bank provenance is never set in place (planning/question-bank.md §2.3, §4):
`set_property` refuses `source` on questions, pages and blocks and the derived
`metadata.instruments`; other edits keep `source` unchanged."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from osp_ops import run

BASE: dict[str, Any] = json.loads((Path(__file__).parent / "base_survey.json").read_text("utf-8"))
SRC = {"bank": "demo2", "version": 1, "library": "bundled"}


def base() -> dict[str, Any]:
    return copy.deepcopy(BASE)


def question(survey: dict[str, Any], qid: str) -> dict[str, Any]:
    return next(
        q for b in survey["blocks"] for p in b["pages"] for q in p["items"] if q["id"] == qid
    )


@pytest.mark.parametrize("target", ["age", "p_demo", "b_intro"])
def test_set_property_refuses_source(target: str) -> None:
    res = run("set_property", base(), {"target": target, "property": "source", "value": SRC})
    assert not res.ok and "op.not_allowed" in [d.code for d in res.diagnostics]


def test_set_property_refuses_metadata_instruments() -> None:
    params = {"target": "/metadata", "property": "instruments", "value": [SRC]}
    res = run("set_property", base(), params)
    assert not res.ok and "op.not_allowed" in [d.code for d in res.diagnostics]


def test_label_edit_keeps_source() -> None:
    s = base()
    question(s, "age")["source"] = SRC
    res = run("set_property", s, {"target": "age", "property": "label", "value": "How old?"})
    assert res.ok
    after = question(res.survey, "age")
    assert after["source"] == SRC and after["label"] == "How old?"
