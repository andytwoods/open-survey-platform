"""Media (planning/media.md) in the ops: `set_choice_media`, `add_choice` with media,
question media through `set_property`, and media texts in the text sites. Round trips
and fuzzing are in test_guard.py."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from osp_ops import REGISTRY, run
from osp_ops.doc import text_sites

BASE: dict[str, Any] = json.loads((Path(__file__).parent / "base_survey.json").read_text("utf-8"))
IMAGE = {"kind": "image", "url": "/media/x.png", "alt": {"en": "An X", "de": "Ein X"}}


def base() -> dict[str, Any]:
    return copy.deepcopy(BASE)


def question(survey: dict[str, Any], qid: str) -> dict[str, Any]:
    for b in survey["blocks"]:
        for page in b["pages"]:
            for q in page["items"]:
                if q["id"] == qid:
                    return q
    raise KeyError(qid)


def codes(res: Any) -> list[str]:
    return [d.code for d in res.diagnostics]


def test_registered_in_the_choices_area() -> None:
    assert REGISTRY["set_choice_media"].area == "choices"


def test_set_and_unset_choice_media_with_inverses() -> None:
    res = run("set_choice_media", base(), {"owner": "fruit", "value": 2, "media": IMAGE})
    assert res.ok and question(res.survey, "fruit")["choices"][1]["media"] == IMAGE
    assert res.inverse is not None
    assert res.inverse.params == {"owner": "fruit", "value": 2, "unset": True}
    undo = run(res.inverse.op, res.survey, res.inverse.params)
    assert undo.ok and "media" not in question(undo.survey, "fruit")["choices"][1]
    # Replacing remembers the old media; a shared list is addressed by its id.
    res = run("set_choice_media", base(), {"owner": "spare", "value": "a", "media": IMAGE})
    assert res.ok and res.inverse is not None
    assert res.inverse.params["media"]["url"] == "/media/a.png"


def test_choice_media_is_validated_by_the_model() -> None:
    """A shape error is `op.invalid_result`; a semantic one (video on a choice, no alt, a
    bad URL) is applied and reported as the validator's diagnostic, as for any edit."""
    shape = {"kind": "image", "url": "/x.png", "alt": "x", "bogus": 1}
    res = run("set_choice_media", base(), {"owner": "fruit", "value": 1, "media": shape})
    assert not res.ok and "op.invalid_result" in codes(res)
    video = {"kind": "video", "url": "/v.mp4", "captionsUrl": "/v.vtt", "transcriptUrl": "/t"}
    res = run("set_choice_media", base(), {"owner": "fruit", "value": 1, "media": video})
    assert res.ok and "media.choice_kind" in codes(res)
    no_alt = {"kind": "image", "url": "/x.png"}
    res = run("set_choice_media", base(), {"owner": "fruit", "value": 1, "media": no_alt})
    assert res.ok and "media.alt_missing" in codes(res)
    bad_url = {"kind": "image", "url": "http://evil.example/x.png", "alt": "x"}
    res = run("set_choice_media", base(), {"owner": "fruit", "value": 1, "media": bad_url})
    assert res.ok and "media.url" in codes(res)
    res = run("set_choice_media", base(), {"owner": "age", "value": 1, "media": IMAGE})
    assert not res.ok and "op.not_allowed" in codes(res)
    res = run("set_choice_media", base(), {"owner": "fruit", "value": 99, "media": IMAGE})
    assert not res.ok and "op.not_found" in codes(res)


def test_delete_choice_inverse_restores_media() -> None:
    res = run("delete_choice", base(), {"owner": "spare", "value": "a"})
    assert res.ok and res.inverse is not None
    assert res.inverse.op == "add_choice" and res.inverse.params["media"]["url"] == "/media/a.png"
    undo = run(res.inverse.op, res.survey, res.inverse.params)
    assert undo.ok and undo.survey["choiceLists"][1]["choices"][0]["media"]["url"] == "/media/a.png"


def test_question_media_is_a_plain_property() -> None:
    media = [
        IMAGE,
        {"kind": "video", "url": "/v.mp4", "captionsUrl": "/v.vtt", "transcriptUrl": "/t"},
    ]
    res = run("set_property", base(), {"target": "age", "property": "media", "value": media})
    assert res.ok and question(res.survey, "age")["media"] == media
    assert res.inverse is not None and res.inverse.params["unset"] is True
    too_many = run(
        "set_property", base(), {"target": "age", "property": "media", "value": [IMAGE] * 4}
    )
    assert not too_many.ok and "op.invalid_result" in codes(too_many)


def test_type_change_keeps_media() -> None:
    res = run("change_question_type", base(), {"id": "info", "type": "text"})
    assert res.ok and question(res.survey, "info")["media"][0]["url"] == "/media/thanks.mp3"


def test_media_texts_are_text_sites() -> None:
    paths = {"/".join(map(str, p)) for p, _ in text_sites(base())}
    assert "choiceLists/1/choices/0/media/alt" in paths
    assert "blocks/1/pages/0/items/0/media/0/caption" in paths
