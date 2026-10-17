"""Media (planning/media.md): the URL rules, the deployment origin check and the model."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from osp_spec import Media, parse, publish_diagnostics, validate
from osp_spec.media import media_origin, normalise_origins, url_problem

P0 = "/blocks/0/pages/0/items"


def base() -> dict[str, Any]:
    return {
        "specVersion": "osp-survey/0.1",
        "id": "srv",
        "metadata": {"title": "T", "languages": ["en"]},
        "blocks": [
            {"id": "b1", "pages": [{"id": "p1", "items": [
                {"id": "q1", "type": "integer", "label": "Q1"},
                {"id": "q2", "type": "integer", "label": "Q2"},
            ]}]},
        ],
        "flow": [{"type": "block", "id": "f1", "block": "b1"}],
    }  # fmt: skip


def _items(s: dict) -> list:
    return s["blocks"][0]["pages"][0]["items"]


def _image(**extra: Any) -> dict:
    return {"kind": "image", "url": "/media/a.png", "alt": "A face", **extra}


def _video(**extra: Any) -> dict:
    return {"kind": "video", "url": "https://cdn.example.org/c.mp4",
            "captionsUrl": "/media/c.vtt", "transcriptUrl": "/media/c.html", **extra}  # fmt: skip


@pytest.mark.parametrize(
    "url",
    [
        "/media/a.png",
        "/a",
        "https://cdn.example.org/a.png",
        "https://cdn.example.org:8443/a.png?x=1#t",
        "https://[2001:db8::1]/a.png",
        "https://cdn.example.org",
    ],
)
def test_good_urls(url: str) -> None:
    assert url_problem(url) is None


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("http://cdn.example.org/a.png", "media.url"),
        ("http://localhost/a.png", "media.url_insecure"),
        ("http://127.0.0.1:8000/a.png", "media.url_insecure"),
        ("//cdn.example.org/a.png", "media.url"),
        ("ftp://x/a", "media.url"),
        ("javascript:alert(1)", "media.url"),
        ("data:image/png;base64,AAAA", "media.url"),
        ("a.png", "media.url"),
        ("https://u:p@cdn.example.org/a.png", "media.url"),
        ("https://cdn.example.org/a b.png", "media.url"),
        ("https://cdn.example.org:99999/a.png", "media.url"),
        ("https://cdn.example.org/${q1}.png", "media.url_pipe"),
        ("/media/${q1}.png", "media.url_pipe"),
    ],
)
def test_bad_urls(url: str, code: str) -> None:
    problem = url_problem(url)
    assert problem is not None and problem[0] == code


def test_origins() -> None:
    assert media_origin("/media/a.png") is None
    assert media_origin("https://CDN.Example.org/a.png") == "https://cdn.example.org"
    assert media_origin("https://cdn.example.org:443/a.png") == "https://cdn.example.org"
    assert media_origin("https://cdn.example.org:8443/a") == "https://cdn.example.org:8443"
    assert media_origin("http://localhost:5173/a") == "http://localhost:5173"
    assert normalise_origins([" https://CDN.example.org/ ", "junk", "http://localhost:5173"]) == {
        "https://cdn.example.org",
        "http://localhost:5173",
    }


def _with_media(items: list[dict[str, Any]]) -> dict[str, Any]:
    s = base()
    _items(s)[0]["media"] = items
    return s


def test_valid_media_survey_round_trips() -> None:
    s = _with_media(
        [
            _image(caption={"en": "Figure ${q2}"}, width=640, height=480, mimeType="image/png"),
            _video(posterUrl="/media/c.jpg", durationSeconds=12.5, autoplay=True),
            {
                "kind": "audio",
                "url": {"en": "/media/a-en.mp3"},
                "transcriptUrl": {"en": "/media/a-en.html"},
                "mustPlayToEnd": True,
            },
        ]
    )
    survey, diags = parse(s)
    assert survey is not None and diags == []
    dumped = survey.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert parse(dumped)[0] == survey
    assert _items(dumped)[0]["media"][2]["mustPlayToEnd"] is True


def test_media_limits_are_schema_errors() -> None:
    s = _with_media([_image()] * 4)
    assert [d.code for d in validate(s)] == ["schema.value"]
    s = _with_media([_image(width=0, height=9000)])
    assert {d.code for d in validate(s)} == {"schema.value"}
    s = _with_media([_image(url="x" * 2049)])
    assert {"schema.value"} <= {d.code for d in validate(s)} <= {"schema.value", "schema.type"}
    s = _with_media([_image(mimeType="text/html")])
    assert {d.code for d in validate(s)} == {"schema.pattern"}
    s = _with_media([_image(durationSeconds=0)])
    assert {d.code for d in validate(s)} == {"schema.value"}


def test_duration_takes_an_integer() -> None:
    m = Media.model_validate({"kind": "audio", "url": "/a.mp3", "durationSeconds": 30})
    assert m.durationSeconds == 30


def test_allowed_origins_are_enforced_only_when_given() -> None:
    s = _with_media(
        [
            _image(url="https://cdn.example.org/a.png"),
            _image(url="/media/b.png"),
            {
                "kind": "video",
                "url": "https://video.example.org/c.mp4",
                "captionsUrl": {"en": "https://cdn.example.org/c.vtt"},
                "transcriptUrl": "/t.html",
                "posterUrl": "https://video.example.org/c.jpg",
            },
        ]
    )
    assert validate(s) == []
    got = sorted(
        (d.code, d.pointer) for d in validate(s, media_origins=["https://cdn.example.org"])
    )
    assert got == [
        ("media.origin_not_allowed", f"{P0}/0/media/2/posterUrl"),
        ("media.origin_not_allowed", f"{P0}/0/media/2/url"),
    ]
    assert validate(s, media_origins=["https://cdn.example.org", "https://video.example.org"]) == []
    none_allowed = validate(s, media_origins=[])
    assert len(none_allowed) == 4 and {d.code for d in none_allowed} == {"media.origin_not_allowed"}
    assert "this site only" in none_allowed[0].message
    s["settings"] = {"retention": {"kind": "indefinite"}}
    s["consent"] = {"text": "ok?"}
    errors = [d.code for d in publish_diagnostics(s, media_origins=[]) if d.severity == "error"]
    assert errors == ["media.origin_not_allowed"] * 4


def test_choice_media_on_shared_lists_and_matrix_columns() -> None:
    s = base()
    s["choiceLists"] = [
        {"id": "faces", "choices": [{"value": 1, "label": "A", "media": _image()}]},
    ]
    _items(s)[0] = {"id": "q1", "type": "single", "label": "Q1", "choiceList": "faces"}
    _items(s)[1] = {
        "id": "q2",
        "type": "matrix",
        "label": "M",
        "rows": [{"id": "a", "label": "A"}],
        "choices": [{"value": 1, "label": "Yes", "media": {"kind": "image", "url": "/y.png"}}],
    }
    got = sorted((d.code, d.pointer) for d in validate(s))
    assert got == [("media.alt_missing", f"{P0}/1/choices/0/media/alt")]


def test_validator_does_not_mutate_media_input() -> None:
    s = _with_media([_video()])
    before = copy.deepcopy(s)
    validate(s, media_origins=["https://cdn.example.org"])
    assert s == before
