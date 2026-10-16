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

## Response data (`osp_targets.data`, task M2)

```python
from osp_targets.data import CsvOptions, StoredResponse, SurveyVersion, codebook, export_csv

v = SurveyVersion(survey_json, number=3, checksum="…", save_mode="every-page")
csv_bytes = export_csv(v, [StoredResponse("r1", record=engine_record)], CsvOptions.excel())
book = codebook(v)  # book.markdown, book.data (JSON)
```

- **Missing values** (semantics §1): CSV = empty cell + `<var>__state` (switchable off); JSON = `null` + `state`. Never `-99`.
- **Columns:** `_`-prefixed meta (response/session id, version + checksum, plan checksum, engine version, allocation and save mode, seed, UTC timestamps, `_late`, end, language), one column per condition, questions in plan order (multi: `<var>_<code>` 0/1, or codes in one cell), embedded/computed variables, then `_order.{blocks,items,choices}.<id>` realised orders.
- **CSV:** RFC 4180 (CRLF), optional BOM, formula-injection escaping (`'` before `= + - @`, tab, CR; plain numbers untouched).
- **Versions:** `export_csv_combined` / `export_json_combined` / `codebook_combined` union the columns with `_version`.
- **Tests:** golden files in `tests/data/golden/` from engine records in `tests/data/records/` (regenerate those with `node --experimental-transform-types python/osp-targets/tests/data/dump_records.ts` after `make engine-fixtures`; goldens with `OSP_UPDATE_GOLDEN=1`).

Internal package; not published.
