"""Response data export (task M2): CSV, JSON, codebook.

Inputs are real engine output: ``tests/data/records/<fixture>/<script>.json`` is
``result(state)`` after playing that fixture script through ``web/engine``
(``tests/data/dump_records.ts`` regenerates them). Golden files live in
``tests/data/golden/<fixture>/``; regenerate with ``OSP_UPDATE_GOLDEN=1 uv run pytest
python/osp-targets/tests/test_data_export.py`` and review the diff.
"""

from __future__ import annotations

import copy
import csv
import io
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from osp_targets.data import (
    CsvOptions,
    ExportError,
    Hook,
    JsonOptions,
    StoredResponse,
    SurveyVersion,
    codebook,
    codebook_combined,
    escape_formula,
    export_csv,
    export_csv_combined,
    export_json,
    export_json_combined,
)

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "fixtures"
DATA = Path(__file__).resolve().parent / "data"
RECORDS = DATA / "records"
GOLDEN = DATA / "golden"
UPDATE = os.environ.get("OSP_UPDATE_GOLDEN") == "1"
T0 = datetime(2026, 10, 16, 9, 30, tzinfo=UTC)

GOLDEN_FIXTURES = [
    "01-all-types",
    "05-showif-null",
    "11-end-nodes",
    "13-randomiser-blocks",
    "15-choice-order-shuffle",
    "16-assign",
    "18-multi-language",
    "20-worked-example",
    "27-unicode-text",
    "38-matrix",
    "39-slider",
    "40-consent",
]
ALL_FIXTURES = sorted(p.name for p in RECORDS.iterdir() if p.is_dir())
MISSING_CODES = {"-99", "-98", "-97", "-999", "-9", ".a", ".b", ".c", "NA", "N/A"}


def _survey(fixture: str) -> dict[str, Any]:
    return json.loads((FIXTURES / fixture / "survey.json").read_text(encoding="utf-8"))


def _version(fixture: str, **kw: Any) -> SurveyVersion:
    s = _survey(fixture)
    return SurveyVersion(
        s,
        number=kw.pop("number", s.get("version") or 1),
        checksum=kw.pop("checksum", f"sha256:test-{fixture}"),
        save_mode=kw.pop("save_mode", "every-page"),
        **kw,
    )


def _responses(fixture: str) -> list[StoredResponse]:
    out = []
    for i, path in enumerate(sorted((RECORDS / fixture).glob("*.json"))):
        rec = json.loads(path.read_text(encoding="utf-8"))
        out.append(
            StoredResponse(
                response_id=f"resp-{path.stem}",
                record=rec,
                session_id=f"sess-{path.stem}",
                allocation_mode="server",
                session_seed=rec["sessionSeed"],
                engine_version=rec["engineVersion"],
                started_at=T0 + timedelta(minutes=i),
                submitted_at=T0 + timedelta(minutes=i, seconds=30, milliseconds=250),
                late=False,
            )
        )
    return out


def _rows(data: bytes) -> list[dict[str, str]]:
    text = data.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text, newline="")))


def _golden(path: Path, content: bytes) -> None:
    if UPDATE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    assert path.exists(), f"{path} missing: run with OSP_UPDATE_GOLDEN=1"
    assert content == path.read_bytes(), f"{path.relative_to(REPO)} differs from the export"


# -- golden files ------------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", GOLDEN_FIXTURES)
def test_golden(fixture: str) -> None:
    v, rs = _version(fixture), _responses(fixture)
    out = GOLDEN / fixture
    _golden(out / "responses.csv", export_csv(v, rs))
    _golden(
        out / "responses-excel-codes.csv",
        export_csv(v, rs, CsvOptions.excel(multi="codes")),
    )
    _golden(out / "responses.json", export_json(v, rs, JsonOptions(events=True)))
    book = codebook(v)
    _golden(out / "codebook.md", book.markdown.encode("utf-8"))
    _golden(
        out / "codebook.json",
        (json.dumps(book.data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def test_fixture_01_header() -> None:
    header = export_csv(_version("01-all-types"), []).decode("utf-8").split("\r\n")[0]
    assert header == (
        "_response_id,_session_id,_version,_version_checksum,_plan_checksum,_engine_version,"
        "_allocation_mode,_save_mode,_seed,_started_at,_submitted_at,_late,_after_close,_end,"
        "_language,"
        "n_int,n_int__state,n_dec,n_dec__state,t_text,t_text__state,s_single,s_single__state,"
        "m_multi_red,m_multi_green,m_multi_blue,m_multi__state,d_date,d_date__state"
    )


@pytest.mark.parametrize("fixture", ALL_FIXTURES)
def test_columns_follow_the_plan_order(fixture: str) -> None:
    """Our survey order is the runtime plan's ``questions`` order (the engine's answers)."""
    from osp_targets.data.layout import build_layout

    lay = build_layout(_version(fixture))
    for path in sorted((RECORDS / fixture).glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        assert [q.id for q in lay.questions] == list(rec["answers"])


# -- states and missing values -----------------------------------------------------------------


def _expected_answers(fixture: str, script: str) -> dict[str, Any] | None:
    path = FIXTURES / fixture / "expected" / f"{script}.json"
    if not path.exists():
        return None
    exp = json.loads(path.read_text(encoding="utf-8"))
    resp = exp.get("response")
    if exp.get("pending") or not isinstance(resp, dict):
        return None
    answers = resp.get("answers")
    return answers if isinstance(answers, dict) else None


def _variables(survey: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Variable id -> export name and type, read straight from the survey (not the export).

    A matrix holds no value itself: row ``r`` of matrix ``m`` is the ``single`` variable
    ``m_r``, exported as ``<matrix name>_r`` (semantics.md §2, C2c-1).
    """
    names: dict[str, str] = {}
    types: dict[str, str] = {}
    for b in survey.get("blocks", []):
        for p in b["pages"]:
            for q in p["items"]:
                if q["type"] == "note":
                    continue
                name = q.get("name", q["id"])
                if q["type"] == "matrix":
                    for row in q["rows"]:
                        names[f"{q['id']}_{row['id']}"] = f"{name}_{row['id']}"
                        types[f"{q['id']}_{row['id']}"] = "single"
                else:
                    names[q["id"]], types[q["id"]] = name, q["type"]
    return names, types


@pytest.mark.parametrize("fixture", ALL_FIXTURES)
def test_states_match_engine_and_expected_traces(fixture: str) -> None:
    v = _version(fixture)
    names, types = _variables(_survey(fixture))
    rows = {r["_response_id"]: r for r in _rows(export_csv(v, _responses(fixture)))}
    as_json = json.loads(export_json(v, _responses(fixture)))
    by_id = {r["responseId"]: r for r in as_json["responses"]}
    checked = 0
    for path in sorted((RECORDS / fixture).glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        row, jrow = rows[f"resp-{path.stem}"], by_id[f"resp-{path.stem}"]
        expected = _expected_answers(fixture, path.stem) or {}
        for qid, ans in rec["answers"].items():
            name = names[qid]
            state = row[f"{name}__state"]
            assert state == ans["state"], (fixture, path.stem, qid)
            assert jrow["answers"][name]["state"] == ans["state"]
            if isinstance(expected.get(qid), dict):
                assert state == expected[qid]["state"], (fixture, path.stem, qid)
                checked += 1
            if types[qid] == "multi":
                cells = [row[k] for k in row if k.startswith(f"{name}_") and k != f"{name}__state"]
                if state == "answered":
                    assert set(cells) <= {"0", "1"}
                else:
                    assert set(cells) <= {""}
            elif state != "answered":
                assert row[name] == "", (fixture, path.stem, qid)
                assert jrow["answers"][name]["value"] is None
            else:
                assert jrow["answers"][name]["value"] == ans["value"]
        # the record's own CSV companion columns agree with ours
        for col, st in rec["csvState"].items():
            assert row[col] == st
    if any(_expected_answers(fixture, p.stem) for p in (RECORDS / fixture).glob("*.json")):
        assert checked > 0


@pytest.mark.parametrize("fixture", ALL_FIXTURES)
def test_no_numeric_missing_codes(fixture: str) -> None:
    v, rs = _version(fixture), _responses(fixture)
    for opts in (CsvOptions(), CsvOptions(state_columns=False), CsvOptions.excel(multi="codes")):
        for row in _rows(export_csv(v, rs, opts)):
            assert not (set(row.values()) & MISSING_CODES), row


def test_state_columns_off_and_multi_codes() -> None:
    v, rs = _version("01-all-types"), _responses("01-all-types")
    rows = _rows(export_csv(v, rs, CsvOptions(state_columns=False, multi="codes")))
    assert not any(k.endswith("__state") for k in rows[0])
    by = {r["_response_id"]: r for r in rows}
    assert by["resp-answered"]["m_multi"] == "red blue"
    assert by["resp-empty"]["m_multi"] == ""
    book = codebook(v, CsvOptions(state_columns=False))
    assert "switched off" in book.markdown


# -- determinism -------------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", ["13-randomiser-blocks", "20-worked-example"])
def test_byte_identical_and_order_independent(fixture: str) -> None:
    v, rs = _version(fixture), _responses(fixture)
    for fn in (export_csv, export_json):
        first = fn(v, rs)
        assert fn(v, list(reversed(rs))) == first
        assert fn(_version(fixture), _responses(fixture)) == first
    assert codebook(v).markdown == codebook(_version(fixture)).markdown


def test_columns_stable_without_responses() -> None:
    v = _version("20-worked-example")
    empty = export_csv(v, []).split(b"\r\n")[0]
    full = export_csv(v, _responses("20-worked-example")).split(b"\r\n")[0]
    assert empty == full


# -- formula injection and RFC 4180 ------------------------------------------------------------


def _with_text(text: Any, n_int: Any = 3) -> StoredResponse:
    rec = json.loads((RECORDS / "01-all-types/answered.json").read_text(encoding="utf-8"))
    rec = copy.deepcopy(rec)
    rec["answers"]["t_text"]["value"] = text
    rec["answers"]["n_int"]["value"] = n_int
    return StoredResponse("r1", record=rec)


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ('=HYPERLINK("http://x","y")', '\'=HYPERLINK("http://x","y")'),
        ("+1+2", "'+1+2"),
        ("-1+2", "'-1+2"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tcmd", "'\tcmd"),
        ("-", "'-"),
        ("plain", "plain"),
        ("-3", "-3"),
        ("-2.50", "-2.50"),
        ("a=b", "a=b"),
    ],
)
def test_formula_escaping(raw: str, escaped: str) -> None:
    assert escape_formula(raw) == escaped
    v = _version("01-all-types")
    row = _rows(export_csv(v, [_with_text(raw)]))[0]
    assert row["t_text"] == escaped
    off = _rows(export_csv(v, [_with_text(raw)], CsvOptions(escape_formulas=False)))[0]
    assert off["t_text"] == raw


def test_negative_numbers_are_not_mangled() -> None:
    row = _rows(export_csv(_version("01-all-types"), [_with_text("x", n_int=-4)]))[0]
    assert row["n_int"] == "-4"


def test_rfc4180_quoting_round_trips() -> None:
    text = 'He said "hi", then\r\nleft; ünïcödé ☂'
    data = export_csv(_version("01-all-types"), [_with_text(text)])
    assert b'"He said ""hi"", then\r\nleft; \xc3\xbcn' in data
    assert data.endswith(b"\r\n") and b"\n" not in data.replace(b"\r\n", b"")
    assert _rows(data)[0]["t_text"] == text


def test_excel_bom() -> None:
    v, rs = _version("01-all-types"), _responses("01-all-types")
    assert export_csv(v, rs, CsvOptions.excel()).startswith(b"\xef\xbb\xbf_response_id,")
    assert export_csv(v, rs).startswith(b"_response_id,")


# -- meta columns ------------------------------------------------------------------------------


def test_meta_columns() -> None:
    v = _version("16-assign", save_mode="end-only")
    rows = {r["_response_id"]: r for r in _rows(export_csv(v, _responses("16-assign")))}
    r = rows["resp-treatment"]
    assert r["_started_at"].endswith("Z") and r["_started_at"].startswith("2026-10-16T09:3")
    assert r["_submitted_at"].endswith(".250Z")
    assert r["_save_mode"] == "end-only"
    assert r["_late"] == "false"
    assert r["_allocation_mode"] == "server"
    assert r["_plan_checksum"].startswith("sha256:")
    assert r["_version_checksum"] == "sha256:test-16-assign"
    assert r["_end"] == "complete"
    # the condition column holds the level in force
    rec = json.loads((RECORDS / "16-assign/treatment.json").read_text(encoding="utf-8"))
    for var, level in rec["conditions"].items():
        assert r[var] == str(level)


def test_realised_orders_are_compact_columns() -> None:
    v, rs = _version("13-randomiser-blocks"), _responses("13-randomiser-blocks")
    rows = _rows(export_csv(v, rs))
    rec = json.loads((RECORDS / "13-randomiser-blocks/main.json").read_text(encoding="utf-8"))
    for rid, order in rec["orders"]["blocks"].items():
        assert rows[0][f"_order.blocks.{rid}"] == " ".join(order)
    v15 = _version("15-choice-order-shuffle")
    rows15 = _rows(export_csv(v15, _responses("15-choice-order-shuffle")))
    assert any(k.startswith("_order.choices.") and rows15[0][k] for k in rows15[0])


# -- JSON --------------------------------------------------------------------------------------


def test_json_events_option() -> None:
    v, rs = _version("01-all-types"), _responses("01-all-types")
    without = json.loads(export_json(v, rs))
    assert "events" not in without["responses"][0]
    with_ev = json.loads(export_json(v, rs, JsonOptions(events=True)))
    assert with_ev["responses"][0]["events"][0]["type"] == "start"
    by = {r["responseId"]: r for r in with_ev["responses"]}
    a = by["resp-answered"]["answers"]
    assert a["m_multi"] == {"state": "answered", "value": ["red", "blue"]}
    assert a["n_dec"] == {"state": "answered", "value": "2.8"}  # exact decimal text


# -- multiple versions -------------------------------------------------------------------------


def _v2() -> SurveyVersion:
    s = _survey("01-all-types")
    s["version"] = 2
    s["choiceLists"][1]["choices"].append({"value": "pink", "label": "Pink"})
    page = s["blocks"][0]["pages"][0]
    page["items"] = [i for i in page["items"] if i["id"] != "d_date"]
    page["items"].append({"type": "integer", "id": "n_new", "label": "New in v2", "required": True})
    return SurveyVersion(s, number=2, checksum="sha256:v2", save_mode="end-only")


def _v2_response() -> StoredResponse:
    rec = json.loads((RECORDS / "01-all-types/answered.json").read_text(encoding="utf-8"))
    rec["answers"].pop("d_date")
    rec["answers"]["m_multi"]["value"] = ["pink"]
    rec["answers"]["n_new"] = {"state": "answered", "value": 7}
    return StoredResponse("v2-r1", record=rec, version=2, submitted_at=T0 + timedelta(days=1))


def test_combined_csv_unions_columns() -> None:
    v1, r1 = _version("01-all-types", number=1), _responses("01-all-types")
    v2 = _v2()
    data = export_csv_combined([(v2, [_v2_response()]), (v1, r1)])
    rows = _rows(data)
    header = data.decode("utf-8").split("\r\n")[0].split(",")
    # M2-3: m_multi's choices changed (pink added), so each version has its own columns
    assert "m_multi_red" not in header and "m_multi__state" not in header
    assert header.index("m_multi_v2_pink") > header.index("d_date__state")  # v2-only, appended
    assert header.index("m_multi_v1_red") < header.index("m_multi_v1__state")
    assert [r["_version"] for r in rows] == ["1", "1", "2"]
    v2row = rows[2]
    assert v2row["d_date"] == "" and v2row["d_date__state"] == ""  # not in version 2
    assert v2row["m_multi_v2_pink"] == "1" and v2row["m_multi_v2_red"] == "0"
    assert v2row["m_multi_v1_red"] == "" and v2row["m_multi_v1__state"] == ""
    assert v2row["m_multi_v2__state"] == "answered"
    assert v2row["n_new"] == "7"
    by = {r["_response_id"]: r for r in rows}
    assert by["resp-answered"]["m_multi_v1_red"] == "1"
    assert by["resp-answered"]["m_multi_v2_pink"] == ""
    assert rows[0]["n_new__state"] == ""
    # an unchanged question keeps one column across versions
    assert v2row["n_int"] == by["resp-answered"]["n_int"] != ""
    # one version combined == the single-version export
    assert export_csv_combined([(v1, r1)]) == export_csv(v1, r1)


def test_wording_change_keeps_one_column() -> None:
    """M2-3: only a type or choice-code change splits a variable; new wording does not."""
    v1 = _version("01-all-types", number=1)
    s = _survey("01-all-types")
    item = next(i for i in s["blocks"][0]["pages"][0]["items"] if i["id"] == "n_int")
    item["label"] = "Reworded"
    v2 = SurveyVersion(s, number=2, checksum="sha256:v2b")
    header = export_csv_combined([(v1, []), (v2, [])]).decode("utf-8").split("\r\n")[0]
    assert header == export_csv(v1, []).decode("utf-8").split("\r\n")[0]
    assert codebook_combined([v1, v2]).data["splitVariables"] == []


def test_type_change_splits() -> None:
    v1 = _version("01-all-types", number=1)
    s = _survey("01-all-types")
    item = next(i for i in s["blocks"][0]["pages"][0]["items"] if i["id"] == "n_int")
    item["type"] = "decimal"
    v2 = SurveyVersion(s, number=2, checksum="sha256:v2c")
    header = export_csv_combined([(v1, []), (v2, [])]).decode("utf-8").split("\r\n")[0]
    cols = header.split(",")
    assert "n_int" not in cols and {"n_int_v1", "n_int_v2", "n_int_v2__state"} <= set(cols)


def test_combined_codebook_and_json() -> None:
    v1, v2 = _version("01-all-types", number=1), _v2()
    book = codebook_combined([v2, v1])
    assert book.data["versions"] == [1, 2]
    assert "m_multi" in book.data["changedVariables"]
    assert book.data["splitVariables"] == ["m_multi"]
    assert "Split into per-version columns (type or choices changed): `m_multi`." in book.markdown
    v1_names = [x["name"] for x in book.data["codebooks"][0]["variables"]]
    assert "m_multi_v1" in v1_names and "n_int" in v1_names
    assert "not in this version" in book.markdown
    assert "## Codebook: All question types" in book.markdown
    assert len(book.data["codebooks"]) == 2
    doc = json.loads(
        export_json_combined([(v1, _responses("01-all-types")), (v2, [_v2_response()])])
    )
    assert [v["version"] for v in doc["versions"]] == [1, 2]
    last = doc["responses"][-1]
    assert last["version"] == 2 and "d_date" not in last["answers"]
    assert last["answers"]["m_multi_v2"] == {"state": "answered", "value": ["pink"]}
    assert codebook_combined([v1]).markdown == codebook(v1).markdown


# -- late flag and variable states (M2-1, M2-2) -------------------------------------------------


def test_late_is_the_server_flag() -> None:
    v = _version("01-all-types")
    rec = json.loads((RECORDS / "01-all-types/answered.json").read_text(encoding="utf-8"))
    rs = [
        StoredResponse("a", record=rec, late=True, after_close=False),
        StoredResponse("b", record=rec),  # no flag: not late; after-close not known
    ]
    rows = {r["_response_id"]: r for r in _rows(export_csv(v, rs))}
    assert (rows["a"]["_late"], rows["a"]["_after_close"]) == ("true", "false")
    assert (rows["b"]["_late"], rows["b"]["_after_close"]) == ("false", "")
    doc = {r["responseId"]: r for r in json.loads(export_json(v, rs))["responses"]}
    assert doc["a"]["late"] is True and doc["b"]["late"] is False


def _with_variables() -> SurveyVersion:
    s = _survey("05-showif-null")
    qids = [q["id"] for b in s["blocks"] for p in b["pages"] for q in p["items"]]
    a = qids[0]
    s["variables"] = [
        {"kind": "embedded", "id": "src", "param": "src"},
        {"kind": "embedded", "id": "src_d", "param": "srcd", "default": "direct"},
        {
            "kind": "computed",
            "id": "a2",
            "expr": {
                "kind": "arith",
                "op": "*",
                "left": {"kind": "ref", "id": a},
                "right": {"kind": "int", "value": 2},
            },
        },
        {
            "kind": "computed",
            "id": "a4",
            "expr": {
                "kind": "arith",
                "op": "*",
                "left": {"kind": "ref", "id": "a2"},
                "right": {"kind": "int", "value": 2},
            },
        },
    ]
    return SurveyVersion(s, number=1, checksum="sha256:vars")


def _answers(state: str) -> dict[str, Any]:
    s = _survey("05-showif-null")
    qids = [
        q["id"] for b in s["blocks"] for p in b["pages"] for q in p["items"] if q["type"] != "note"
    ]
    return {q: {"state": state, "value": None} for q in qids}


@pytest.mark.parametrize(
    ("record", "want"),
    [
        # the record's own variableStates win
        (
            {
                "answers": _answers("unanswered"),
                "embedded": {"src": None},
                "variableStates": {
                    "src": "unanswered",
                    "src_d": "answered",
                    "a2": "irrelevant",
                    "a4": "irrelevant",
                },
            },
            {"src": "unanswered", "src_d": "answered", "a2": "irrelevant", "a4": "irrelevant"},
        ),
        # derived for an older record: inputs not reached -> not-reached (through a2)
        (
            {
                "answers": _answers("not-reached"),
                "embedded": {"src": None, "src_d": "direct"},
                "computed": {"a2": None, "a4": None},
            },
            {"src": "unanswered", "src_d": "answered", "a2": "not-reached", "a4": "not-reached"},
        ),
        (
            {"answers": _answers("irrelevant"), "computed": {"a2": None, "a4": None}},
            {"src": "unanswered", "src_d": "unanswered", "a2": "irrelevant", "a4": "irrelevant"},
        ),
        (
            {"answers": _answers("unanswered"), "computed": {"a2": None, "a4": None}},
            {"src": "unanswered", "src_d": "unanswered", "a2": "unanswered", "a4": "unanswered"},
        ),
        (
            {"answers": _answers("unanswered"), "computed": {"a2": "4", "a4": "8"}},
            {"src": "unanswered", "src_d": "unanswered", "a2": "answered", "a4": "answered"},
        ),
    ],
)
def test_variable_state_columns(record: dict[str, Any], want: dict[str, str]) -> None:
    v = _with_variables()
    row = _rows(export_csv(v, [StoredResponse("r", record=record)]))[0]
    assert {k: row[f"{k}__state"] for k in want} == want
    for k, st in want.items():
        if st != "answered":
            assert row[k] == ""
    doc = json.loads(export_json(v, [StoredResponse("r", record=record)]))
    assert {k: x["state"] for k, x in doc["responses"][0]["variables"].items()} == want
    assert not any(
        k.endswith("__state")
        for k in _rows(
            export_csv(v, [StoredResponse("r", record=record)], CsvOptions(state_columns=False))
        )[0]
    )
    other = {x["name"]: x for x in codebook(v).data["otherVariables"]}
    assert other["a2"]["csvColumns"] == ["a2", "a2__state"]
    assert "not-reached" in other["a2"]["missing"]


# -- codebook ----------------------------------------------------------------------------------


def test_codebook_contents() -> None:
    v = _version("20-worked-example", hooks=[Hook("h1", ["onSubmitted"], ["age"], ["redirect"])])
    book = codebook(v)
    md, data = book.markdown, book.data
    assert data["saveMode"]["mode"] == "every-page"
    assert {c["name"] for c in data["conditions"]} == {"framing", "incentive"}
    assert data["hooks"][0]["dataExports"] == ["redirect"]
    assert "| `h1` | onSubmitted | age | redirect |" in md
    assert "No numeric missing codes such as -99 are ever written" in md
    shown = {
        x["name"]: x["showIf"]
        for x in codebook(_version("05-showif-null")).data["variables"]
        if x.get("showIf")
    }
    assert shown["s_gt"] == "a > 5"
    # exports and conditions use the variable name, not the stable id
    s05 = _survey("05-showif-null")
    s05["blocks"][0]["pages"][0]["items"][0]["name"] = "first_a"
    assert s05["blocks"][0]["pages"][0]["items"][0]["id"] == "a"
    renamed = codebook(SurveyVersion(s05))
    gt = next(x for x in renamed.data["variables"] if x["name"] == "s_gt")
    assert gt["showIf"] == "first_a > 5"
    assert renamed.data["csv"]["columns"][15:17] == ["first_a", "first_a__state"]
    ml = codebook(_version("18-multi-language")).markdown
    assert "Label (en) | Label (de)" in ml and "Kaffee" in ml
    end_only = codebook(_version("01-all-types", save_mode="end-only")).markdown
    assert "Drop-outs and attrition are invisible" in end_only


def test_codebook_lists_lab_custom_properties() -> None:
    """Custom values (planning/property-profiles.md §5): per variable and as a key list;
    a matrix row carries its matrix's; never a data column."""
    s = _survey("38-matrix")
    items = s["blocks"][0]["pages"][0]["items"]
    matrix = next(q for q in items if q["type"] == "matrix")
    matrix["custom"] = {"construct": "satisfaction", "weight": 2.5, "prereg": True}
    plain = codebook(SurveyVersion(s))
    assert "customProperties" not in codebook(_version("38-matrix")).data
    assert plain.data["customProperties"] == [
        {"key": "construct", "types": ["matrix"]},
        {"key": "prereg", "types": ["matrix"]},
        {"key": "weight", "types": ["matrix"]},
    ]
    rows = [v for v in plain.data["variables"] if v.get("matrix") == matrix["id"]]
    assert rows and all(v["custom"] == matrix["custom"] for v in rows)
    md = plain.markdown
    assert "## Lab properties" in md and "| `construct` | matrix |" in md
    assert (
        '- Lab properties: `construct` = `"satisfaction"`; `prereg` = `true`; `weight` = `2.5`'
        in md
    )
    # No column carries them, and the stock codebook is unchanged without any.
    assert plain.data["csv"]["columns"] == codebook(_version("38-matrix")).data["csv"]["columns"]
    assert "Lab properties" not in codebook(_version("38-matrix")).markdown


def test_codebook_lists_media() -> None:
    """Media (planning/media.md §7): per variable and per choice, with the paradata note
    when a clip is present; never a data column; absent without media."""
    s = _survey("38-matrix")
    items = s["blocks"][0]["pages"][0]["items"]
    matrix = next(q for q in items if q["type"] == "matrix")
    matrix["media"] = [
        {"kind": "image", "url": "/media/grid.png", "alt": "A grid", "caption": "Fig. 1"},
        {
            "kind": "audio",
            "url": {"en": "/media/en.mp3"},
            "transcriptUrl": "/t.html",
            "mustPlayToEnd": True,
        },
    ]
    matrix["choices"][0]["media"] = {"kind": "image", "url": "/media/no.svg", "alt": "No"}
    plain = codebook(SurveyVersion(s))
    rows = [v for v in plain.data["variables"] if v.get("matrix") == matrix["id"]]
    assert rows and rows[0]["media"] == [
        {
            "kind": "image",
            "url": {"en": "/media/grid.png"},
            "alt": {"en": "A grid"},
            "caption": {"en": "Fig. 1"},
        },
        {
            "kind": "audio",
            "url": {"en": "/media/en.mp3"},
            "transcriptUrl": {"en": "/t.html"},
            "mustPlayToEnd": True,
        },
    ]
    assert rows[0]["choices"][0]["media"] == {
        "kind": "image",
        "url": {"en": "/media/no.svg"},
        "alt": {"en": "No"},
    }
    assert "media" not in rows[0]["choices"][1]
    assert "paradata" in plain.data["media"]
    md = plain.markdown
    assert "## Media" in md and "one `media` event per clip" in md
    assert "- Media: image /media/grid.png (alt: A grid; caption: Fig. 1)" in md
    assert "- Media: audio /media/en.mp3 (must play to the end)" in md
    assert "| Media |" in md and "| image /media/no.svg (alt: No) |" in md
    assert plain.data["csv"]["columns"] == codebook(_version("38-matrix")).data["csv"]["columns"]
    stock = codebook(_version("38-matrix"))
    assert "media" not in stock.data and "## Media" not in stock.markdown
    # An image-only survey gets the note but no paradata paragraph.
    matrix["media"] = matrix["media"][:1]
    assert "paradata" not in codebook(SurveyVersion(s)).data["media"]


# -- hostile input -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "record",
    [
        None,
        {},
        {"answers": "nope"},
        {"answers": {"n_int": {"state": "bogus", "value": 5}}},
        {"answers": {"n_int": {"state": "unanswered", "value": 5}}},
        {"answers": {"m_multi": {"state": "answered", "value": "red"}}, "orders": [1]},
        {"conditions": 3, "embedded": [], "events": {}, "startedAt": "x", "language": ["en"]},
    ],
)
def test_odd_records_never_crash(record: Any) -> None:
    v = _version("01-all-types")
    r = StoredResponse("odd", record=record, started_at=datetime(2026, 1, 1))  # naive = UTC
    row = _rows(export_csv(v, [r]))[0]
    assert row["n_int"] == ""  # never a value without an answered state
    assert row["_started_at"] == "2026-01-01T00:00:00.000Z"
    json.loads(export_json(v, [r], JsonOptions(events=True)))


def test_invalid_survey_and_clash_are_export_errors() -> None:
    with pytest.raises(ExportError) as err:
        export_csv(SurveyVersion({"specVersion": "nope"}), [])
    assert err.value.diagnostics
    s = _survey("01-all-types")
    s["blocks"][0]["pages"][0]["items"].append(
        {"type": "integer", "id": "m_multi_red", "label": "clash"}
    )
    with pytest.raises(ExportError) as err:
        export_csv(SurveyVersion(s), [])
    assert err.value.diagnostics[0].code == "export.column_clash"
    # the codes-in-one-cell option avoids it
    assert export_csv(SurveyVersion(s), [], CsvOptions(multi="codes"))


# -- matrix and slider (C2c; semantics.md §2) --------------------------------------------------


def test_matrix_rows_are_columns_and_slider_is_a_number() -> None:
    """Each matrix row is its own column `<matrix name>_<row id>` with its own state."""
    v = _version("38-matrix")
    rec = {
        "answers": {
            "taste_tea": {"state": "answered", "value": 3},
            "taste_coffee": {"state": "answered", "value": 1},
            "taste_cocoa": {"state": "unanswered", "value": None},
            "cups": {"state": "answered", "value": 2},
            "when_morning": {"state": "irrelevant", "value": None},
            "when_evening": {"state": "irrelevant", "value": None},
        }
    }
    header = export_csv(v, []).decode("utf-8").split("\r\n")[0].split(",")
    assert header[header.index("_language") + 1 :] == [
        "drink_tea", "drink_tea__state", "drink_coffee", "drink_coffee__state",
        "drink_cocoa", "drink_cocoa__state", "cups", "cups__state",
        "when_morning", "when_morning__state", "when_evening", "when_evening__state",
    ]  # fmt: skip
    row = _rows(export_csv(v, [StoredResponse("r1", record=rec)]))[0]
    assert (row["drink_tea"], row["drink_tea__state"]) == ("3", "answered")
    assert (row["drink_cocoa"], row["drink_cocoa__state"]) == ("", "unanswered")
    assert row["when_evening__state"] == "irrelevant"
    book = codebook(v)
    tea = next(x for x in book.data["variables"] if x["name"] == "drink_tea")
    assert tea["type"] == "single" and tea["matrix"] == "taste" and tea["required"] is True
    assert [c["code"] for c in tea["choices"]] == [1, 2, 3]
    cocoa = next(x for x in book.data["variables"] if x["name"] == "drink_cocoa")
    assert cocoa["required"] is False
    assert "Row of matrix `taste`" in book.markdown

    s = _version("39-slider")
    sleep = next(x for x in codebook(s).data["variables"] if x["name"] == "sleep")
    assert (sleep["type"], sleep["valueType"], sleep["step"]) == ("slider", "decimal", "0.5")
    rec = {"answers": {"pain": {"state": "answered", "value": 4},
                       "sleep": {"state": "answered", "value": "7.5"}}}  # fmt: skip
    row = _rows(export_csv(s, [StoredResponse("r1", record=rec)]))[0]
    assert (row["pain"], row["sleep"], row["mood__state"]) == ("4", "7.5", "")


def test_engine_records_for_matrix_slider_and_consent() -> None:
    """Fixtures 38-40 as the engine recorded them: row columns, slider numbers, consent."""
    rows = {
        f: {r["_response_id"]: r for r in _rows(export_csv(_version(f), _responses(f)))}
        for f in ("38-matrix", "39-slider", "40-consent")
    }
    main = rows["38-matrix"]["resp-main"]  # matrix id `taste`, export name `drink`
    assert (main["drink_tea"], main["drink_coffee"], main["drink_cocoa__state"]) == (
        "3",
        "1",
        "unanswered",
    )
    assert not any(k.startswith(("taste", "drink__")) or k == "drink" for k in main)
    assert main["when_morning__state"] == main["when_evening__state"] == "irrelevant"
    back = rows["38-matrix"]["resp-back-change-row"]
    assert (back["drink_tea"], back["cups__state"], back["when_morning"]) == (
        "1",
        "irrelevant",
        "daily",
    )

    slider = rows["39-slider"]
    assert (slider["resp-main"]["pain"], slider["resp-main"]["sleep"]) == ("8", "7.5")
    assert (slider["resp-off-step"]["sleep"], slider["resp-off-step"]["mood"]) == ("6", "-2")

    consent = rows["40-consent"]
    rec = json.loads((RECORDS / "40-consent/agree.json").read_text(encoding="utf-8"))
    agree = consent["resp-agree"]
    assert agree["_consent_version"] == rec["consentVersion"]
    assert agree["_consent_version"].startswith("sha256:")
    assert agree["_consented_at"] == "1970-01-01T00:00:03.000Z"  # the runner's clock
    # the server's record wins over the browser's (semantics.md §11)
    r = StoredResponse("srv", record=rec, consent_version="sha256:srv", consented_at=T0)
    srv = _rows(export_csv(_version("40-consent"), [r]))[0]
    assert (srv["_consent_version"], srv["_consented_at"]) == (
        "sha256:srv",
        "2026-10-16T09:30:00.000Z",
    )
    # a decline never agreed: no consent version, nothing reached
    declined = consent["resp-decline"]
    assert (declined["_end"], declined["_consent_version"], declined["_consented_at"]) == (
        "declined",
        "",
        "",
    )
    assert "_consent_version" not in rows["39-slider"]["resp-main"]
    book = codebook(_version("40-consent"))
    assert book.data["consent"] and "synthetic study about sleep" in book.markdown
