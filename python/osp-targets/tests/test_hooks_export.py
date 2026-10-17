"""Researcher hooks (task R11): neither export target runs custom code, so a survey with a
hook manifest exports with one "hooks not exported" diagnostic and nothing from inside the
manifest leaks into the file or into further diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from osp_targets import export_lss, export_xlsform

CASE = Path(__file__).resolve().parents[2] / "osp-spec/tests/cases/valid/v12_hooks.json"


def _survey() -> dict[str, Any]:
    return json.loads(CASE.read_text(encoding="utf-8"))["survey"]


@pytest.mark.parametrize(("target", "export"), [("xlsform", export_xlsform), ("lss", export_lss)])
def test_hooks_are_reported_once_as_unsupported(target: str, export: Any) -> None:
    survey = _survey()
    content, diags = export(survey)
    assert content, [d.message for d in diags]
    about_hooks = [d for d in diags if d.pointer.startswith("/hooks")]
    assert [(d.feature, d.level, d.pointer, d.target) for d in about_hooks] == [
        ("Survey.hooks", "unsupported", "/hooks", target)
    ]
    assert "not exported" in about_hooks[0].message
    # The export itself is the same as without hooks: the manifest is dropped whole.
    plain = dict(survey)
    del plain["hooks"]
    plain_content, plain_diags = export(plain)
    assert len(plain_content) > 0
    assert [d for d in plain_diags if d.pointer.startswith("/hooks")] == []
    assert survey["hooks"]["source"].encode() not in content
