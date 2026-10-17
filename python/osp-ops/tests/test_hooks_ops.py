"""`set_hooks` (task R11): stores a normalised manifest, removes it, refuses a malformed one
with a pointer, and lets reference problems through as validator diagnostics (a draft may
be mid-edit; publishing is what they block)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from osp_ops import run

BASE: dict[str, Any] = json.loads((Path(__file__).parent / "base_survey.json").read_text("utf-8"))


def base() -> dict[str, Any]:
    return json.loads(json.dumps(BASE))


def manifest(**extra: Any) -> dict[str, Any]:
    return {
        "format": "osp-hooks/1",
        "source": "osp.on('onPageShown', function (c, d, act) { act.addParadata('t', c.trial); });",
        "handlers": {"onPageShown": {"reads": ["age"], "writes": [], "timeoutMs": None}},
        **extra,
    }


def test_set_hooks_stores_a_normalised_manifest_and_unsets_cleanly() -> None:
    res = run("set_hooks", base(), {"hooks": manifest()})
    assert res.ok, res.diagnostics
    stored = res.survey["hooks"]
    assert stored["handlers"] == {"onPageShown": {"reads": ["age"], "writes": []}}  # no null
    assert stored["source"] == manifest()["source"]
    assert [d for d in res.diagnostics if d.code.startswith("hooks.")] == []
    assert res.inverse is not None and res.inverse.op == "apply_patch"
    back = run("set_hooks", res.survey, {"hooks": None})
    assert back.ok and back.survey == base()
    # Removing when there is nothing is a no-op, not an error.
    none = run("set_hooks", base(), {"hooks": None})
    assert none.ok and none.patch == []


def test_set_hooks_rejects_a_malformed_manifest_with_a_pointer() -> None:
    bad = manifest()
    bad["handlers"]["onExplode"] = {"reads": [], "writes": []}
    res = run("set_hooks", base(), {"hooks": bad})
    assert not res.ok
    assert res.diagnostics[0].code == "op.invalid_result"
    assert res.diagnostics[0].pointer.startswith("/hooks/handlers")
    huge = manifest(source="x" * (256 * 1024 + 1))
    res = run("set_hooks", base(), {"hooks": huge})
    assert not res.ok and res.diagnostics[0].pointer == "/hooks/source"
    assert not run("set_hooks", base(), {"hooks": {"format": "osp-hooks/2"}}).ok
    assert not run("set_hooks", base(), {"hooks": "osp.on()"}).ok  # params schema


def test_reference_problems_are_diagnostics_not_a_refusal() -> None:
    m = manifest()
    m["handlers"]["onPageShown"]["reads"] = ["age", "nope"]
    res = run("set_hooks", base(), {"hooks": m})
    assert res.ok  # a draft may point at a question that is about to be added
    assert [(d.code, d.pointer) for d in res.diagnostics if d.code.startswith("hooks.")] == [
        ("hooks.unknown_ref", "/hooks/handlers/onPageShown/reads/1")
    ]


def test_set_hooks_replaces_the_whole_manifest() -> None:
    first = run("set_hooks", base(), {"hooks": manifest(urlParams=["PID"])})
    second = run("set_hooks", first.survey, {"hooks": manifest()})
    assert second.ok and "urlParams" not in second.survey["hooks"]
    assert second.patch == [{"op": "remove", "path": "/hooks/urlParams"}]
