# osp-instruments

**Layer:** L2 (imports `osp-spec` only). No I/O apart from reading its own package data.

**Job:** the bundled library of validated instruments for the question bank
(planning/question-bank.md §3, §7). Read-only; a lab copies an item into its own bank to
edit it (QB4).

| Path | What |
|---|---|
| `src/osp_instruments/library/<id>.json` | One `osp-bank-item/0.1` document per instrument: items, choice lists, scoring recipe (computed variables), citation, source URL and the licence evidence |
| `src/osp_instruments/__init__.py` | `load_library()`, `load_document(id)`, `library_ids()`, `lookup(source)` (for `osp_spec.bank.with_instruments` at publish), `licences_markdown()` |
| `LICENCES.md` | Generated from the library: holder, class, terms page, access date and the quoted statement for every instrument |
| `permissions/LETTER.md` | The standard permission request the project owner sends to rights holders; granted permissions are filed next to it |

## Rules for adding an instrument

1. Read the rights holder's **current** terms page. Bundle only what is public domain, CC0
   or CC BY 4.0 (or held under a written permission filed in `permissions/`), so that
   reproduction, distribution and adaptation inside an MIT-licensed program are all
   covered. Never bundle non-commercial-only, share-alike or registration-gated
   instruments (lead decision 4): they get a stub in QB5's private "licensed copy" path.
2. Put the operative sentence, word for word, in `licence.statement`, the page in
   `licence.url` and the date you read it in `licence.evidenceDate`; transcribe the item
   text from the holder's own form (`source.url`). Never reconstruct items from memory.
3. Add the row to the audit table in `planning/question-bank.md` §7.0.
4. Regenerate `LICENCES.md`: `OSP_UPDATE_GOLDEN=1 uv run pytest python/osp-instruments`.

`make licence-check` lists the bundled instruments and fails on any class outside
`licence-policy.toml` `[instruments] allowed`.
