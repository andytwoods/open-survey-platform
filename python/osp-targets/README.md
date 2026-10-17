# osp-targets

**Layer:** L3. Imports only packages in lower layers (enforced by `uv run lint-imports`). No I/O: no network, database, clock or global randomness.

**Job:** Mappings from our model to external formats (XLSForm first) plus per-target capability tables. Pure.

## XLSForm (ODK / Enketo / KoboToolbox)

```python
from osp_targets import export_xlsform

xlsx_bytes, diagnostics = export_xlsform(survey)  # Survey model or JSON dict; never raises
```

- **Capability table:** `osp_targets/capabilities/xlsform.py`. One row per `osp-survey` schema field (`"<Def>.<field>"`), value refinements (`"Page.itemOrder=shuffle"`) and target behaviours (`"$pipe.choiceLabel"`), each `native | lowered | approximated | unsupported` with a note. `tests/test_capabilities.py` fails when a schema field has no row, or a row names a field that is gone.
- **Diagnostics:** `ExportDiagnostic {target, severity, code, feature, level, pointer, message}`. Severity follows the level: lowered → `info`, approximated → `warning`, unsupported → `loss`; `error` means nothing was exported. Every non-native feature the survey uses gets one, with an RFC 6901 pointer into the survey JSON.
- **Lowerings:** pages → `field-list` groups inside one group per block (`style: pages`); the flow tree → `relevant` on block groups (branches, end nodes, randomiser `pick`); expressions → XPath with null guards (§3); piped single-choice answers → `jr:choice-name()` calculates (§8); choice shuffles → `randomize(..., ${osp_seed_<q>})`; `assign` → a seed calculate plus the same Park–Miller draw as `osp_engine.random.assign`; end outcomes → `osp_outcome`.
- **Seeds** are drawn in the form (`once(random())`) and recorded in the data, so every order and assignment replays with `osp_engine`, but they are not derived from a session seed with `node_seed()`.
- **Not exportable:** quotas, quota checks, turning Back off, question and block order shuffles (approximated: document order), survey description, licence and DDI metadata.
- Output is deterministic (fixed zip and document timestamps). Tests convert every fixture and the valid spec cases with `pyxform` (BSD-2, test-only).

## Importers (`osp_targets.imports`, task IM1)

```python
from osp_targets.imports import detect_format, import_survey

result = import_survey("study.qsf", content)   # never raises
result.format, result.survey, result.diagnostics, result.summary, result.validation
```

- **Formats:** Qualtrics `.qsf` (`qsf.py`), LimeSurvey `.lss` (`lss.py`, with a small Expression Manager parser in `em_expr.py`) and SurveyJS JSON (`surveyjs.py`, `visibleIf` parser in `sjs_expr.py`). Clean-room: written from the public formats and our own invented samples (`tests/data/imports`), never from their code.
- **Diagnostics:** `ImportDiagnostic {format, severity, code, feature, pointer, message, target}`; `info` carried over with a note, `warning` carried over but behaves differently, `loss` not carried over, `error` nothing imported. Every unsupported feature is one; nothing is dropped silently.
- **Safety net:** `common.finish()` validates the built document and drops any condition or computed variable the validator refuses (forward references, type mismatches) as a reported loss, so a file that parses always yields a draft. Bad input never raises (`guarded`).
- **Round trip:** every fixture exported with `export_lss` imports back with its question names, types, labels, required flags, choice values, bounds, sliders, assignments and conditions (`tests/test_imports.py`).

## Response data (`osp_targets.data`, task M2)

```python
from osp_targets.data import CsvOptions, StoredResponse, SurveyVersion, codebook, export_csv

v = SurveyVersion(survey_json, number=3, checksum="…", save_mode="every-page")
csv_bytes = export_csv(v, [StoredResponse("r1", record=engine_record)], CsvOptions.excel())
book = codebook(v)  # book.markdown, book.data (JSON)
```

- **Missing values** (semantics §1): CSV = empty cell + `<var>__state` (switchable off); JSON = `null` + `state`. Never `-99`.
- **Columns:** `_`-prefixed meta (response/session id, version + checksum, plan checksum, engine version, allocation and save mode, seed, UTC timestamps, `_late` = the server's flag for a submit accepted after the session expired (S-2), `_after_close`, end, language), one column per condition, questions in plan order (multi: `<var>_<code>` 0/1, or codes in one cell), embedded/computed variables (each with `<var>__state`, C3a-5 / C2-6), then `_order.{blocks,items,choices}.<id>` realised orders.
- **CSV:** RFC 4180 (CRLF), optional BOM, formula-injection escaping (`'` before `= + - @`, tab, CR; plain numbers untouched).
- **Versions:** `export_csv_combined` / `export_json_combined` / `codebook_combined` union the columns with `_version`; a question whose type or choice codes changed between versions is split into per-version `<var>_v<N>` columns (M2-3), and the codebook says so.
- **Tests:** golden files in `tests/data/golden/` from engine records in `tests/data/records/` (regenerate those with `node --experimental-transform-types python/osp-targets/tests/data/dump_records.ts` after `make engine-fixtures`; goldens with `OSP_UPDATE_GOLDEN=1`).

## Reproducibility package (`osp_targets.repro`, task M3)

```python
from osp_targets.repro import ReproData, ReproInputs, ReproKit, build_repro_package

pkg = build_repro_package(ReproInputs(survey, survey_id, 3, checksum, plan, kit, data=None))
pkg.content, pkg.filename, pkg.files  # deterministic zip bytes (same inputs, same bytes)
```

- **Contents:** `README.md` (versions, checksums, verify/replay steps, methods text), `LICENSE.md` (platform code MIT; survey content under `metadata.license`), `manifest.json`, `checksums.sha256` (every other file; `sha256sum -c`), `survey/{survey,plan,runtime-config}.json`, `exports/survey.{xlsx,lss}` + diagnostics JSON, and `replay/`. With `data`: `data/codebook.{md,json}`, `data/responses.{csv,json}` (JSON with event logs).
- **Replay kit** (`repro/kit/`, copied verbatim): `replay.py` (stdlib + the vendored `osp_engine/random.py`) recomputes every recorded order and assignment from the seed and plan; `replay.mjs` replays every event log through `engine.js` (`make engine-bundle`) and compares the final state with the stored response. Both exit 1 on any mismatch.
- Pure: the caller (`osp_app.repro`) reads the kit, the PRNG source and the bundle and passes bytes. Endpoint: `GET /api/surveys/{id}/versions/{v}/repro-package[?data=true]`.

Internal package; not published.
