"""Preregistration bundle (task OS1): deterministic zip, design description, exclusions,
summary page, hostile input. Built from the fixture surveys; no participant data anywhere."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from osp_targets.data import ExportError, SurveyVersion
from osp_targets.prereg import (
    PreregInputs,
    build_prereg_bundle,
    canonical_sha256,
    prereg_data,
)

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "fixtures"
EXPECTED_FILES = [
    "README.md",
    "checksums.sha256",
    "codebook/codebook.json",
    "codebook/codebook.md",
    "design/design.json",
    "design/exclusions.md",
    "design/randomisation.md",
    "design/structure.md",
    "manifest.json",
    "summary.html",
    "survey/checksum.txt",
    "survey/survey.json",
]


def _survey(fixture: str) -> dict[str, Any]:
    return json.loads((FIXTURES / fixture / "survey.json").read_text(encoding="utf-8"))


def _inputs(
    fixture: str, *, repro: bytes | None = b"PK\x05\x06" + b"\0" * 18, **kw: Any
) -> PreregInputs:
    survey = kw.pop("survey") if "survey" in kw else _survey(fixture)
    return PreregInputs(
        survey=survey,
        survey_id="0123456789abcdef",
        version=kw.pop("version", 1),
        survey_checksum=kw.pop("survey_checksum", canonical_sha256(survey)),
        plan_checksum=kw.pop("plan_checksum", "p" * 64),
        versions={"spec": "osp-survey/0.1", "platform (osp-app)": "0.0.0"},
        repro_package=repro,
    )


def _files(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        roots = {n.split("/", 1)[0] for n in z.namelist()}
        assert len(roots) == 1, roots
        return {n.split("/", 1)[1]: z.read(n) for n in z.namelist()}


def _data(fixture: str, **kw: Any) -> dict[str, Any]:
    survey = kw.pop("survey") if "survey" in kw else _survey(fixture)
    return prereg_data(SurveyVersion(survey, number=1, checksum=canonical_sha256(survey), **kw))


# -- the zip ---------------------------------------------------------------------------------


def test_byte_for_byte_deterministic() -> None:
    a = build_prereg_bundle(_inputs("20-worked-example"))
    b = build_prereg_bundle(_inputs("20-worked-example"))
    assert a.content == b.content and a.filename == "survey-01234567-v1-prereg.zip"
    with zipfile.ZipFile(io.BytesIO(a.content)) as z:
        infos = z.infolist()
        assert [i.filename for i in infos] == sorted(i.filename for i in infos)
        assert {i.date_time for i in infos} == {(2000, 1, 1, 0, 0, 0)}
    assert build_prereg_bundle(_inputs("13-randomiser-blocks")).content != a.content
    assert build_prereg_bundle(_inputs("20-worked-example", version=2)).content != a.content


def test_file_list_and_nested_repro_package() -> None:
    package = b"PK\x05\x06" + b"\0" * 18
    full = build_prereg_bundle(_inputs("20-worked-example", repro=package))
    assert full.files == sorted([*EXPECTED_FILES, "reproducibility-package.zip"])
    files = _files(full.content)
    assert files["reproducibility-package.zip"] == package  # stored verbatim
    assert not [f for f in files if f.startswith("data/")]
    bare = build_prereg_bundle(_inputs("20-worked-example", repro=None))
    assert bare.files == EXPECTED_FILES
    m = json.loads(_files(bare.content)["manifest.json"])
    assert m["includesReproPackage"] is False and m["includesData"] is False
    assert "was not included" in _files(bare.content)["README.md"].decode()


def test_checksums_sha256_covers_every_file(tmp_path: Path) -> None:
    pkg = build_prereg_bundle(_inputs("16-assign"))
    files = _files(pkg.content)
    listed = dict(
        reversed(line.split("  ", 1)) for line in files["checksums.sha256"].decode().splitlines()
    )
    assert sorted(listed) == [f for f in sorted(files) if f != "checksums.sha256"]
    for path, digest in listed.items():
        assert hashlib.sha256(files[path]).hexdigest() == digest, path


def test_manifest_identity_and_design_counts() -> None:
    survey = _survey("20-worked-example")
    pkg = build_prereg_bundle(_inputs("20-worked-example", survey=survey))
    files = _files(pkg.content)
    m = json.loads(files["manifest.json"])
    assert m["format"] == "osp-prereg-bundle/1"
    assert m["survey"]["checksum"] == canonical_sha256(survey) and m["survey"]["checksumOk"]
    assert m["survey"]["surveyJsonId"] == survey["id"] and m["survey"]["id"] == "0123456789abcdef"
    assert m["plan"]["checksum"] == "p" * 64
    assert m["design"]["conditions"] == ["framing", "incentive"]
    assert m["design"]["quotas"] == 1 and m["design"]["consent"] is False
    assert m["design"]["saveMode"] == "every-page"
    assert m["files"] == pkg.files
    assert json.loads(files["survey/survey.json"]) == survey
    assert (
        files["survey/checksum.txt"].decode().startswith(canonical_sha256(survey) + "  survey.json")
    )
    wrong = build_prereg_bundle(_inputs("20-worked-example", survey_checksum="0" * 64))
    assert json.loads(_files(wrong.content)["manifest.json"])["survey"]["checksumOk"] is False


def test_codebook_is_the_m2_codebook() -> None:
    files = _files(build_prereg_bundle(_inputs("18-multi-language")).content)
    book = json.loads(files["codebook/codebook.json"])
    assert book["format"] == "osp-codebook/1" and book["variables"]
    assert files["codebook/codebook.md"].decode().startswith("# Codebook:")


# -- the design description ----------------------------------------------------------------


def test_flow_walk_outcomes_and_quota() -> None:
    d = _data("20-worked-example")
    types = [(n["depth"], n["type"]) for n in d["flow"]]
    assert types == [
        (0, "block"),
        (0, "branch"),
        (1, "end"),
        (0, "block"),
        (0, "quotaCheck"),
        (0, "assign"),
        (0, "branch"),
        (1, "block"),
        (0, "else"),
        (1, "block"),
        (0, "block"),
        (0, "end"),
    ]
    qc = next(n for n in d["flow"] if n["type"] == "quotaCheck")
    assert (
        "limit 150" in qc["text"] and "`screenout`" in qc["text"] and "`quota_full`" in qc["text"]
    )
    assign = next(n for n in d["flow"] if n["type"] == "assign")
    assert assign["variables"] == ["framing", "incentive"]
    assert [o["outcome"] for o in d["outcomes"]] == ["complete", "declined", "quota_full"]
    complete = d["outcomes"][0]
    assert {s["kind"] for s in complete["sources"]} == {"end node", "end of flow"}
    assert d["structure"]["unplacedBlocks"] == ["screenout"]
    assert d["structure"]["questions"] == 5 and d["structure"]["notes"] == 3
    assert d["randomisation"]["quotas"][0]["when"] == 'age_band == "40+"'
    assert d["randomisation"]["assignment"]["conditions"][0]["levels"] == ["gain", "loss"]
    assert [o["kind"] for o in d["randomisation"]["orders"]] == ["items"]


def test_randomisers_with_pick_and_shuffles() -> None:
    survey = _survey("13-randomiser-blocks")
    rnd = next(n for n in survey["flow"] if n["type"] == "randomiser")
    rnd["pick"] = 2
    d = _data("13-randomiser-blocks", survey=survey)
    (r,) = d["randomisation"]["randomisers"]
    assert r["pick"] == 2 and len(r["children"]) >= 2 and r["column"] == f"_order.blocks.{r['id']}"
    node = next(n for n in d["flow"] if n["type"] == "randomiser")
    assert "show 2 of them" in node["text"]
    assert next(n for n in d["flow"] if n["depth"] == 1)["type"] == "block"
    md = _files(build_prereg_bundle(_inputs("13-randomiser-blocks", survey=survey)).content)
    text = md["design/randomisation.md"].decode()
    assert f"| `{r['id']}` |" in text and "| 2 of " in text
    choices = _data("15-choice-order-shuffle")
    assert any(o["kind"] == "choices" for o in choices["randomisation"]["orders"])
    assert any(q["choiceOrder"] == "shuffle" for q in choices["questions"])


def test_exclusions_follow_settings_and_design() -> None:
    d = _data("20-worked-example")
    rules = {r["id"]: r for r in d["exclusions"]}
    assert [r["id"] for r in d["exclusions"]] == [
        "incomplete",
        "late",
        "after_close",
        "outcome",
        "quota_full",
        "declined",
        "withdrawn",
        "conflict",
        "missing",
        "retention",
    ]
    assert rules["quota_full"]["applies"] and "`q_old`: limit 150" in rules["quota_full"]["text"]
    assert rules["declined"]["applies"] is False  # no consent page in this fixture
    assert rules["outcome"]["applies"] and "`declined`" in rules["outcome"]["text"]
    assert "30 idle day" in rules["late"]["text"] and rules["late"]["evidence"] == "`_late` column"
    assert "drop-outs exist as partial sessions" in rules["incomplete"]["text"]
    assert rules["retention"]["applies"] is False  # fixture has none; publishing would add one

    consent = _data("40-consent")
    rules = {r["id"]: r for r in consent["exclusions"]}
    assert rules["declined"]["applies"] and "`declined`" in rules["declined"]["text"]
    assert any(o["outcome"] == "declined" for o in consent["outcomes"])

    survey = _survey("33-end-only-save")
    survey["settings"]["retention"] = {"kind": "days-after-close", "days": 90}
    survey["settings"]["resumeExpiryDays"] = 1
    end_only = _data("33-end-only-save", survey=survey)
    rules = {r["id"]: r for r in end_only["exclusions"]}
    assert "drop-outs are invisible" in rules["incomplete"]["text"]
    assert rules["conflict"]["applies"] is False
    assert "1 idle day." in rules["late"]["text"]
    assert rules["retention"]["applies"] and "90 days after" in rules["retention"]["text"]
    assert end_only["settings"]["retention"] == {"kind": "days-after-close", "days": 90}


def test_markdown_documents() -> None:
    survey = _survey("20-worked-example")
    survey["settings"]["retention"] = {"kind": "indefinite"}
    files = _files(build_prereg_bundle(_inputs("20-worked-example", survey=survey)).content)
    structure = files["design/structure.md"].decode()
    assert "- Blocks: 6; pages: 6; questions: 5" in structure
    assert "    - End `end_declined`: outcome `declined`" in structure
    assert "Not placed in the flow" in structure
    assert "| `quota_full` | quota full `q_old` |" in structure
    rand = files["design/randomisation.md"].decode()
    assert "| `framing` | `gain`, `loss` | `assign_design` |" in rand
    assert "| `q_old` |" in rand and "Park-Miller" in rand
    excl = files["design/exclusions.md"].decode()
    assert "### Consent declined (does not apply to this design)" in excl
    assert "kept until the researcher deletes it" in excl
    assert "Evidence: `_after_close` column." in excl
    readme = files["README.md"].decode()
    assert "no participant data" in readme and "sha256sum -c checksums.sha256" in readme


class _Check(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.open: list[str] = []
        self.max_depth = 0
        self.scripts = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("meta", "br"):
            return
        if tag == "script":
            self.scripts += 1
        self.open.append(tag)
        self.max_depth = max(self.max_depth, len(self.open))

    def handle_endtag(self, tag: str) -> None:
        assert self.open and self.open[-1] == tag, (tag, self.open[-3:])
        self.open.pop()


def test_summary_html_is_self_contained_and_escaped() -> None:
    survey = copy.deepcopy(_survey("20-worked-example"))
    q = survey["blocks"][1]["pages"][0]["items"][0]
    q["label"] = {"en": "<script>alert(1)</script> & co", "de": "Alter"}
    survey["metadata"]["title"] = {"en": 'A "quoted" <title>', "de": "Titel"}
    pkg = build_prereg_bundle(_inputs("20-worked-example", survey=survey))
    html = pkg.summary_html.decode("utf-8")
    assert html == _files(pkg.content)["summary.html"].decode("utf-8")
    assert (
        html.startswith("<!DOCTYPE html>")
        and "<title>Preregistration summary: A &quot;quoted&quot; &lt;title&gt;</title>" in html
    )
    assert "<script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt; &amp; co" in html
    assert "<link" not in html and "src=" not in html  # self-contained: no external resources
    for needle in (
        "<h2>Randomisation and assignment</h2>",
        "<h2>Planned exclusions and data handling</h2>",
        "<code>framing</code>",
        "<code>q_old</code>",
        "sha256sum -c checksums.sha256",
        "<code>" + canonical_sha256(survey) + "</code>",
        "<code>reproducibility-package.zip</code>",
    ):
        assert needle in html, needle
    check = _Check()
    check.feed(html)
    assert check.open == [] and check.scripts == 0 and check.max_depth > 4


def test_consent_and_hooks_sections() -> None:
    html = build_prereg_bundle(_inputs("40-consent")).summary_html.decode()
    assert "<h2>Consent</h2>" in html and "<dt>Declines counted</dt>" in html
    assert "This version runs no custom code." in html


# -- hostile input ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "survey",
    [
        "not an object",
        {},
        {"specVersion": "osp-survey/0.1", "id": "x"},
        {"specVersion": "nope/9", "id": "x", "metadata": {"title": "t", "languages": ["en"]}},
    ],
)
def test_invalid_survey_is_a_diagnostic(survey: Any) -> None:
    with pytest.raises(ExportError):
        build_prereg_bundle(_inputs("20-worked-example", survey=survey))


def test_dangling_references_never_crash() -> None:
    """A flow that names a block, quota or variable that does not exist (a draft that
    skipped validation) still describes itself."""
    survey = _survey("20-worked-example")
    survey["flow"].insert(0, {"type": "block", "id": "ghost", "block": "no_such_block"})
    survey["flow"].insert(1, {"type": "quotaCheck", "id": "qc_ghost", "quota": "no_such_quota"})
    survey["flow"].insert(2, {"type": "assign", "id": "as_ghost", "variables": ["no_such_var"]})
    d = _data("20-worked-example", survey=survey)
    texts = [n["text"] for n in d["flow"][:3]]
    assert texts[0] == "Block `no_such_block`: 0 pages, 0 questions"
    assert texts[1] == "Quota check `qc_ghost`: quota `no_such_quota`"
    assert "`no_such_var`" in texts[2]
    pkg = build_prereg_bundle(_inputs("20-worked-example", survey=survey))
    assert "summary.html" in pkg.files
