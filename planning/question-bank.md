# Question bank: lab bank, bundled instrument library, licence audit (task QB1)

**Status:** plan, 17 Oct 2026, for the lead to review. Planning only: no code in this task.
**Depends on:** the builder toolbox and drag (B16, B19), the structure menu (B20), lab libraries as built for themes (runtime-design §6a) and panel profiles (`property-profiles.md`).
**Clean-room:** a reusable question library is a common idea (Qualtrics, REDCap, KoboToolbox, formr, PsyToolkit all have one). Nothing here is taken from any of them: the bank is a collection of our own `osp-survey` fragments with metadata, and the instrument library contains only item text we are allowed to redistribute. Prior art was learned from public docs and terms pages only (§9).
**Cross-check with other LLMs:** not done from this worker (no GPT/Gemini/Qwen access on the Windows worker). §11 holds a ready brief and the specific questions to put to them; the audit tables say how confident each row is.

## 1. What the researcher gets

1. **Save anything to the lab bank.** From a question, a page or a block's context menu (B20's menu, the palette, or the properties panel): "Save to bank…". The dialog asks for a title, tags and a short description, shows what travels with it (shared choice lists, computed scoring variables, conditions) and warns about references that will be cut (a `showIf` pointing outside the saved part).
2. **Find it again.** A *Bank* tab beside the question-type toolbox in the editor: full-text search over title, abbreviation, item text and tags; filters for source (my lab / shared with my lab / bundled library), kind (question / page / block), language and licence class; a preview card with the items, the citation and the licence badge.
3. **Insert, keeping provenance.** Drag from the Bank tab onto the canvas or the outline (the insertion line of B19) or press Insert to place it at the selection. Insertion is **one op, one undo**. Every inserted question, page or block carries a small `source` record (which bank item, which version, which library), so the codebook can list "instruments used" with citations and the builder can show "a newer version exists".
4. **Versions.** Saving an item that already exists makes version *n+1*; old versions stay (a published survey must stay reproducible). A card inserted from version 2 shows a quiet "v3 available" marker with *Compare* and *Replace* (replace = delete + insert in one transaction; the reference warning of B20 applies).
5. **Share between labs.** Three levels: *private to this lab* (default), *every lab on this host* (read-only to the others), and a portable file (`*.osp-bank.json`, export / import) for other hosts, git and supplementary materials. No central registry in this plan (§10).
6. **A curated library of validated instruments**, bundled with the software, each with source, citation, licence, scoring notes and the translations we may ship. **Only instruments whose item text may be redistributed are bundled** (§7). The library is read-only; "Save a copy to my bank" makes an editable lab version that remembers where it came from.
7. **Bring your own licensed copy, privately.** For instruments we must not bundle (BDI-II, STAI, HADS, …) the bank offers a *stub* with the metadata, scoring recipe and a link to the rights holder, but no item text. A lab that holds a licence pastes or imports the items into a **private** bank item marked `licence: licensed-to-lab`; such items cannot be shared at host level or exported in a shared file (only in the lab's own backup), and every insert shows the licence note.
8. **Scoring travels with the instrument.** In `osp-survey/0.1` a scoring recipe is a set of computed variables (sum, reverse items via `if()`, as semantics.md's deferral note says); the bank inserts them with the items. When `scores` land in `osp-survey/0.2` the recipes migrate with everything else.
9. Works at 320 px, keyboard only, with axe clean, like every other builder page.

What it is not: a participant panel, a cross-survey analytics store or a marketplace (overview.md §5).

## 2. Data model

### 2.1 A bank item (`osp_spec.bank`, L1, pure)

A bank item is a JSON document, validated by a strict pydantic model like every spec model.

```yaml
bankVersion: osp-bank-item/0.1
id: 7f3c…                      # server-assigned (uuid), stable across versions
version: 3                     # immutable once saved; the store keeps every version
kind: block                    # question | page | block
title: "PHQ-9 (depression)"
abbreviation: PHQ-9
description: "Nine items over the last two weeks, 0–3 each; total 0–27."
tags: [depression, screener, phq]
languages: [en, es]            # the fragment's translations (Text maps)
licence:
  class: public-domain         # public-domain | cc0 | cc-by-4.0 | author-permission |
                               # free-noncommercial | licensed-to-lab | unknown
  holder: "Pfizer Inc."
  statement: "No permission required to reproduce, translate, display or distribute."
  url: https://www.phqscreeners.com/
  evidenceDate: 2026-10-17
citation:
  text: "Kroenke K, Spitzer RL, Williams JBW (2001). The PHQ-9… J Gen Intern Med 16:606–613."
  doi: 10.1046/j.1525-1497.2001.016009606.x
source:
  url: https://www.phqscreeners.com/
  note: "Items as published on the screeners site, English."
scoring:                       # free text for humans; the machine recipe is in `fragment.variables`
  text: "Sum items 1–9 (0–27). 5/10/15/20 = mild/moderate/moderately severe/severe. Item 9 is a safety item."
provenance:                    # where this item itself came from, if it was copied
  from: { library: bundled, id: phq9, version: 1 }
fragment:                      # the payload, see 2.2
  choiceLists: [ … ]
  variables: [ … ]             # computed only
  block: { … }                 # or `page` / `question`, by `kind`
```

| Field | Notes |
|---|---|
| `kind` | What `fragment` carries. A `block` item is the normal shape for an instrument (its pages, its shared choice list, its scoring variables). |
| `licence.class` | Drives the sharing rules (§4) and the badge. `licensed-to-lab` and `unknown` can never be shared at host level nor shipped in the bundled library. |
| `citation`, `source`, `scoring.text` | Human-facing; copied into the codebook's "Instruments used" section at export. |
| `languages` | Derived from the fragment at save (which languages every `Text` carries); a filter in the Bank tab. |
| `provenance.from` | Set when "Save a copy to my bank" copies a bundled or shared item. Lets the builder show "newer upstream version" for lab copies too. |

Limits: 256 KB body; 200 items per fragment; tags ≤ 20 of ≤ 40 chars.

### 2.2 The fragment

A fragment is the part of an `osp-survey` document that is self-contained around one question, page or block:

- the object itself (`question`, `page` or `block`), with ids that are **local to the fragment**;
- `choiceLists`: every shared choice list the object refers to;
- `variables`: computed variables whose `expr` refers only to things inside the fragment (the scoring recipe), with `name`s that become export columns (`phq9_total`);
- no flow nodes, quotas, embedded or assigned variables, consent or hooks. A `showIf`, `constraint` or `${pipe}` that points outside the fragment is **cut at save** and reported (`bank.external_ref`, warning, listing what was dropped).

`extract_fragment(survey, target_id) -> (fragment, diagnostics)` and `check_fragment(fragment) -> diagnostics` are pure functions in `osp_spec.bank`; the fragment is validated by building a one-block throwaway survey from it and running the ordinary validator, so a fragment can never be something a survey could not hold.

### 2.3 Provenance on inserted items: `source` on question, page and block

One new optional field on `_QuestionBase`, `Page` and `Block`:

```python
class Source(Model):
    bank: StrictStr            # bank item id (uuid) or the bundled library id ("phq9")
    version: StrictInt         # the item version that was inserted
    library: Literal["lab", "host", "bundled", "file"]
    item: StrictStr | None     # the fragment-local id this object had ("phq9_q3")
    checksum: StrictStr | None # of the inserted fragment, so "edited since insert" is detectable

source: Source | None = None
```

- The runtime, the engine and the participant never see it (`osp_runtime.plan` builds its own item structure, as for `custom`).
- Golden rule 6: the field is handled by the serialiser (it is an ordinary model field), gets an `unsupported` capability row in the XLSForm and LimeSurvey targets ("provenance annotation, not part of the form"), and the codebook prints it (§5).
- It is not settable through `set_property` (reserved like `custom`); only `insert_bank_item` writes it and `clear_source` removes it (for a researcher who edits an instrument heavily and no longer wants it listed as that instrument).
- A matrix row inherits its matrix's source.

Alternative considered: a survey-level `metadata.instruments` list that names the inserted ids. Rejected: it goes stale as soon as a question is moved or deleted, and it cannot say which of two PHQ-9 blocks a question belongs to. The per-object field is the one the duplicate ops already know how to carry (a duplicated block keeps its `source`, so the codebook lists the instrument twice, correctly).

### 2.4 Scoring recipes in `osp-survey/0.1`

semantics.md defers `scores` and reverse scoring to `osp-survey/0.2` and says to use computed variables with `if()` meanwhile. Bundled instruments therefore ship their recipes as computed variables:

- a **total** (`phq9_total = q1 + q2 + …`): null when any item is unanswered, which is the behaviour the deferred `scores` rule also specifies ("null unless every item is answered");
- **reversed items** as `min + max − value` inline (`rses_total = … + (4 − rses_q3) + …`), spelled out so the codebook shows exactly what was computed;
- **subscales** as further variables (`dass_depression`, `dass_anxiety`, `dass_stress`);
- cut-off **bands** are *not* computed (they are documentation in `scoring.text`); a researcher who wants a categorical can add an `if()` variable.

When `scores` arrive, a migration (`bank.scoring_to_scores`) rewrites recipe variables into `scores` for items that opt in; nothing in this plan depends on it.

## 3. Storage, permissions, API

**Store** (`osp_store.bank`, mixed into `Store` like `ThemeLibrary`; migration `0011_question_bank`, additive):

| Table | Columns |
|---|---|
| `bank_items` | `id` PK, `tenant_id` → `tenants`, `visibility` (`lab` / `host`), `licence_class`, `title`, `abbreviation`, `kind`, `tags` (JSON), `languages` (JSON), `current_version`, `created_by/at`, `updated_by/at`, `deleted_at` (soft delete: inserted surveys keep pointing at it) |
| `bank_item_versions` | (`item_id`, `version`) PK, `body` JSON (the whole document of §2.1), `checksum`, `created_by/at`; **immutable** |
| `bank_search` | SQLite FTS5 / Postgres `tsvector` over title, abbreviation, tags, item labels (default language); rebuilt on save. Falls back to `LIKE` when FTS is unavailable (tests cover both) |

Everything tenant-scoped through `TenantContext`; a host-visible item is readable by any tenant on the host (one query path, `visibility = 'host' OR tenant_id = :me`) but writable only by its owner lab. Audited: `bank.save`, `bank.share`, `bank.delete`, `bank.import`, `bank.insert` (survey id, item id, version; never the item text).

**Bundled library**: not in the database. A new workspace package `osp-instruments` (L2: imports `osp-spec` for validation in tests, nothing else, no I/O beyond reading its own package data) holding one JSON document per instrument under `osp_instruments/library/<id>.json`, a `LICENCES.md` with the evidence for every row of §7, and `load_library()`. Tests: every file validates as a bank item; every `licence.class` is in the bundle allow-list (`public-domain`, `cc0`, `cc-by-4.0`, `author-permission` with a `permission` file reference); every item has `citation.text`, `source.url`, `licence.url`, `scoring.text`; English item count matches the audit row. `make licence-check` gains a step that lists the bundled instruments and their licence classes (same policy file, a new `[instruments]` table in `licence-policy.toml`), so a non-permissive instrument cannot land unnoticed.

**Permissions** (`osp_app.auth.permissions`): `BANK_VIEW` (viewer, editor, owner: browse, search, insert); `BANK_MANAGE` (editor, owner: save, new version, tag, delete, import, export); `BANK_SHARE` (owner: set host visibility, add a `licensed-to-lab` item). Inserting into a survey additionally needs the survey's edit permission, as any op.

**App commands** (`osp_app.bank`, registered like the theme commands): `bank.list` (search + filters, paged), `bank.get` (one version or current), `bank.save` (from a survey target: `extract_fragment`, validate, new item or new version), `bank.put` (metadata edits without a new version: title, tags, description; the fragment is version-bound), `bank.share`, `bank.delete`, `bank.export`, `bank.import` (a file: validated, licence class preserved, `licensed-to-lab` items refused unless the importer is an owner and attests), `bank.library` (the bundled list), `bank.copy` (bundled or host item → a lab item with `provenance.from`).

**API** (`/api/bank`, thin; `make contract` regenerates the client):

| Route | Who | Notes |
|---|---|---|
| `GET /api/bank?q=&kind=&source=&lang=&licence=&page=` | member | lab + host-shared + bundled, one list, `source` says which |
| `GET /api/bank/{id}` `?version=` | member | the document |
| `POST /api/bank` `{surveyId, targetId, title, tags, description}` | editor | save from a survey; 422 with `bank.*` diagnostics |
| `POST /api/bank/{id}/versions` | editor | new version from a survey target |
| `PATCH /api/bank/{id}` | editor | metadata only |
| `POST /api/bank/{id}/share` `{visibility}` | owner | |
| `DELETE /api/bank/{id}` | editor | soft delete |
| `GET /api/bank/{id}/export`, `POST /api/bank/import` | editor | the portable file |
| `GET /api/bank/library` | member | bundled instruments (cacheable) |

## 4. The ops

New module `osp_ops/bank_ops.py` (no shared file grows):

```text
insert_bank_item(fragment, source: Source, destination)
  destination for kind=question: {page, index?}
                  kind=page:     {block, index?}
                  kind=block:    {index?, flow?: {after: node id} | null}
```

- Claims fresh ids for everything in the fragment with the item's abbreviation as a prefix (`phq9_q1`, `phq9_total`; `claim_id` / `fresh_id` from `osp_ops.doc` keep them unique; on a clash the usual `_2` suffix), remaps every ref and `${pipe}` inside the fragment the way `duplicate_ops._remap` does (the same helper, moved to `doc.py` so both modules use it), appends the choice lists (an identical list already in the survey is reused rather than duplicated, by canonical content) and the computed variables, writes `source` on the inserted objects, and for a block optionally adds a `block` flow node after the given node (as B20's add block does).
- Validates the resulting document; anything wrong is a `Rejected` with a pointer, never a half-insert.
- **Inverse**: one transaction of `delete_question` / `delete_page` / `delete_block force` plus `delete_variable` and choice-list removals for what was added (the choice list stays if it was reused). The whole insert is one undo step.
- Tests: insert each kind, id clashes, choice-list reuse, external refs refused, the inverse round-trips, Hypothesis fuzz on the fragment (hostile input: cycles in `expr`, 10 000 items, ids at the 64-char limit, a fragment that is a flow node).

```text
clear_source(target)            # drops `source` (inverse: puts it back)
```

Saving to the bank is **not a survey op** (the survey does not change): it is the app command `bank.save`, built on `extract_fragment`.

Existing ops need one touch each: `add_question` / `add_page` / `add_block` already accept full objects (undo path) and therefore carry `source` unchanged; `duplicate_*` keep `source` (a duplicate is still that instrument); `set_property` refuses `source` (as it refuses `custom`).

## 5. Exports and the codebook

- **Survey JSON**: `source` is an ordinary field, so it is simply there; the fragment's choice lists and variables are ordinary survey content.
- **Codebook** (`osp_targets.data.codebook`): each variable from a bank item gets `source: {bank, version, library}`; a new top-level **"Instruments used"** section lists each distinct (bank item, version) with title, citation, licence class and the variable names it produced (including the scoring variables), from the bank metadata captured **at insert** into `metadata.ddi.instruments` (so a published version stays self-describing even if the bank item is later deleted; the lead may prefer a dedicated `metadata.instruments` field: see §10).
- **CSV / JSON responses**: unchanged; scoring variables are ordinary computed columns.
- **XLSForm / LimeSurvey**: `source` dropped with an `unsupported` capability row; the items and computed variables export as they do today.
- **Golden fixtures**: `01-all-types` gains one bundled instrument (a short one, e.g. the PHQ-2) so the codebook goldens prove the section.

## 6. Builder

- **Bank tab** in the toolbox (`lib/bank/BankPane.svelte`, pure logic in `lib/bank/logic.ts` with vitest): search box, filter chips (source, kind, language, licence), result cards (title, abbreviation, kind, item count, licence badge, "v3" and a "newer than inserted" dot when the current survey holds an older version), expand for a preview (items rendered read-only with the ordinary field components, citation, scoring text, licence statement and link). *Insert* places at the selection; drag uses B16/B19's `TypeDrag` with a new resolver kind (`bank`), the same insertion line and announcements.
- **Save to bank…** in B20's context menu and the palette for question / page / block: title, abbreviation, tags, description, licence class (default `unknown` for the lab's own questions, with a one-line explanation of why a shared item should have a known licence), and the preview of what will be cut. For a page or block, *Save as new version of…* lists bank items the selection came from (by `source`).
- **Cards** with `source` show a small provenance line ("PHQ-9 · bundled · v1") with *Details*, *Replace with v2*, *Detach* (`clear_source`).
- **Bank page** (new page entry `bank`, host link `bank` in `OPTIONAL_LINK_NAMES`, dev-host `/bank`): manage the lab's items (edit metadata, versions with diff, share toggle, delete, export), import a file, browse the bundled library with its licence evidence, and the **"Add a licensed instrument privately"** wizard: pick a stub (§7.3) or start blank; paste items one per line or import a file; the wizard builds the matrix / single questions and the scoring recipe from the stub; the owner ticks "Our lab holds a licence for this instrument; it stays private to this lab" (recorded in the audit log, never shown to participants).
- **Insert-time notice**: inserting a `free-noncommercial` item shows the holder's condition once per survey ("Free for non-commercial research; cite …"); a `licensed-to-lab` item shows "licensed to this lab; do not share this survey's JSON outside the lab".
- **Docs**: `docs/question-bank.md` (Guide: saving, inserting, versions, sharing, the bundled library and its licences, adding a licensed instrument), a link from `docs/building-a-survey.md`; `docs/hosting.md` gains the optional `bank` link.

## 7. Licence audit of common instruments

**How to read this audit, and its limit.** "Bundle" means: ship the English item text and response options inside an MIT-licensed program that anyone can install. That is **redistribution to the public**, so "free for research use" alone is not enough; we need public-domain status, an open licence, or a statement that reproduction and distribution are permitted without permission. Where that is not explicit the row says *ask*, not *yes*, and the instrument ships as a **stub** (metadata + scoring, no items) until permission is on file.

The classification below was written on 17 Oct 2026 **from the worker's prior knowledge of each rights holder's published terms; the pages could not be fetched from this session** (web access is denied on the Windows worker, and the research sub-agents hit the same wall). Every row therefore names the page to check, and the first acceptance criterion of QB2 (§8) is: *before an instrument is bundled, the operative sentence of its current terms page is quoted, with URL and date, in `osp-instruments/LICENCES.md`, and a reviewer other than the author of the row has checked it.* Nothing is bundled on the strength of this table alone.

Confidence: *high* = the holder's terms are well known, explicit and unlikely to have changed; *medium* = an authoritative statement exists but is indirect (an author's "no permission needed" note, a journal's reuse policy) or may have changed; *low* = conflicting or missing statements, a human must write to the holder.

Classes used below: **A bundle** (public domain, open licence, or explicit "reproduce and distribute without permission"); **B verify, then bundle** (a permissive statement is believed to exist but must be read in full); **C ask** (free for non-commercial research but redistribution not explicit: ship a stub, write to the holder); **D do not bundle** (proprietary, per-user registration or an explicit ban on electronic redistribution: stub + private licensed copy, §1.7).

### 7.1 Mental health, distress, stress, sleep

| Instrument | Citation | Rights holder, page to verify | Terms as understood | Class | Conf. | Scoring notes | Translations |
|---|---|---|---|---|---|---|---|
| PHQ-9, PHQ-2, PHQ-15, PHQ-SADS | Kroenke, Spitzer & Williams 2001, *J Gen Intern Med* 16:606; Kroenke et al. 2003 (PHQ-2); Kroenke et al. 2002 (PHQ-15) | Pfizer; phqscreeners.com | Site states no permission is required to reproduce, translate, display or distribute the PHQ and GAD-7 screeners | **A** | high | Sum of 9 items 0–3 (0–27); 5/10/15/20 bands; item 9 (self-harm) flagged as a safety item in the stub text; a 10th functional-impairment item is not scored | Dozens on the same site under the same statement: ship those we can validate structurally (QB6) |
| GAD-7, GAD-2 | Spitzer et al. 2006, *Arch Intern Med* 166:1092 | Pfizer; phqscreeners.com | As above | **A** | high | Sum 0–21; 5/10/15 bands; GAD-2 = items 1–2, cut-off 3 | As above |
| Perceived Stress Scale PSS-10 / -4 / -14 | Cohen, Kamarck & Mermelstein 1983, *J Health Soc Behav* 24:385; Cohen & Williamson 1988 (PSS-10) | Sheldon Cohen, CMU laboratory page | Permission not needed for non-profit academic research and educational use; commercial use needs permission (Mind Garden distributes commercially) | **C** | medium | PSS-10: items 4, 5, 7, 8 reversed (0–4), sum 0–40 | Many on the CMU page, contributed; same terms |
| Kessler K10 / K6 | Kessler et al. 2002, *Psychol Med* 32:959; Kessler et al. 2003, *Arch Gen Psychiatry* 60:184 | Harvard Medical School NCS site | Described as freely usable; often stated as public domain (developed under US federal funding) | **B** | medium | K10 sum 10–50 (1–5 scoring) or 0–40 (0–4); K6 ≥ 13 (0–24 scoring) serious distress | On the NCS site; several national variants |
| CES-D (20) and CESD-R | Radloff 1977, *Appl Psychol Meas* 1:385; Eaton et al. 2004 (CESD-R) | NIMH work (US government) / cesd-r.com | Original: US government work, public domain. CESD-R: site states it is in the public domain and free | **A** | high (CES-D), medium (CESD-R) | CES-D: items 4, 8, 12, 16 reversed, sum 0–60, ≥ 16; CESD-R: 0–3 recoding of the 5-point scale, sum 0–60 | CES-D: many, mostly in literature; none official |
| WHO-5 Well-Being Index | WHO Regional Office 1998; Topp et al. 2015, *Psychother Psychosom* 84:167 | Psychiatric Research Unit, Mental Health Centre North Zealand (who-5.org) | Free to use; translations controlled by the unit | **B** | medium | Sum 0–25 ×4 = 0–100; ≤ 50 screens for low mood; ≤ 28 depression | Over 30 official translations on the site; redistribution of translations to be confirmed |
| DASS-21 / DASS-42 | Lovibond & Lovibond 1995, *Behav Res Ther* 33:335 | UNSW Psychology DASS site | Site states the DASS questionnaires are public domain and permission is not needed | **A** | high | Three 7-item subscales ×2 (DASS-21) to compare with DASS-42 norms; bands per subscale | Many contributed translations on the site, listed per contributor; check each |
| PCL-5 | Weathers et al. 2013, National Center for PTSD; Blevins et al. 2015, *J Trauma Stress* 28:489 | US Department of Veterans Affairs (government work) | Public domain; the site asks for a download form but the measure is free to reproduce | **A** | high | Sum 20 items 0–4 (0–80); ≥ 31–33 probable PTSD; cluster scores B/C/D/E | VA lists some; others in literature |
| EPDS | Cox, Holden & Sagovsky 1987, *Br J Psychiatry* 150:782 | Royal College of Psychiatrists (journal copyright) with the authors' reproduction note | Authors permit reproduction without further permission provided the authors, title and source are cited | **B** | medium | Sum 10 items 0–3 (items 3, 5–10 reversed); ≥ 10–13 cut-offs; item 10 safety | Many validated; permission position per translation unclear |
| C-SSRS (screener) | Posner et al. 2011, *Am J Psychiatry* 168:1266 | Columbia Lighthouse Project / Research Foundation for Mental Hygiene | Free of charge; copyrighted; no modification; training encouraged; forms downloaded from Columbia | **C** | medium | Branching yes/no screener; severity by highest ideation + behaviour | 100+ via Columbia, same terms |
| Insomnia Severity Index | Bastien, Vallières & Morin 2001, *Sleep Med* 2:297; Morin et al. 2011 | Charles Morin; licensed through Mapi Research Trust (ePROVIDE) | Free for academic research after registration; distribution controlled | **D** | high | Sum 7 items 0–4 (0–28); 8/15/22 bands | Via ePROVIDE only |
| PSQI | Buysse et al. 1989, *Psychiatry Res* 28:193 | University of Pittsburgh | Free for non-commercial research; copyright retained; commercial licence through the university | **C** | medium | 7 components 0–3, global 0–21, > 5 poor sleeper; the component rules are the hard part and belong in the recipe | Pitt lists validated translations; terms per translation |
| Epworth Sleepiness Scale | Johns 1991, *Sleep* 14:540 | Murray Johns; licensed through Mapi | Licence required for any organisation or electronic use; no modification | **D** | high | Sum 8 items 0–3 (0–24); > 10 | Via Mapi only |
| BDI-II, BAI | Beck et al. 1996 (BDI-II); Beck et al. 1988 (BAI) | Pearson Clinical | Proprietary, per-form fee | **D** | high | BDI-II sum 0–63; 14/20/29 bands | Pearson |
| STAI (Form Y) | Spielberger 1983 | Mind Garden | Proprietary, per-administration licence | **D** | high | State and Trait, 20 items each, 20–80, 10 reversed items in each | Mind Garden |
| HADS | Zigmond & Snaith 1983, *Acta Psychiatr Scand* 67:361 | GL Assessment, distributed through Mapi Research Trust | Proprietary, per-use fee for research in most cases | **D** | high | Anxiety and Depression, 7 items each 0–3 (0–21); 8/11 | Mapi |
| GHQ-12 | Goldberg & Williams 1988 | GL Assessment | Proprietary | **D** | high | 0-0-1-1 scoring (0–12) or Likert 0–36 | GL Assessment |
| SDQ | Goodman 1997, *J Child Psychol Psychiatry* 38:581 | Robert Goodman / Youthinmind (sdqinfo.org) | Paper copies may be downloaded and photocopied free by non-profit users; **electronic versions may not be created or distributed without authorisation** | **D** | high | Five 5-item subscales 0–10, total difficulties 0–40, impact supplement | Over 80 on the site, same ban on electronic versions |

### 7.2 Personality, affect, well-being, individual differences

| Instrument | Citation | Rights holder, page to verify | Terms as understood | Class | Conf. | Scoring notes | Translations |
|---|---|---|---|---|---|---|---|
| **IPIP** (whole pool): IPIP-NEO-120 / -300, Mini-IPIP (20), IPIP Big-Five Markers (50 / 100), Big Five Aspect Scales (100), plus 250+ other scales | Goldberg et al. 2006, *J Res Pers* 40:84; Donnellan et al. 2006, *Psychol Assess* 18:192 (Mini-IPIP); Johnson 2014, *J Res Pers* 51:78 (IPIP-NEO-120); DeYoung, Quilty & Peterson 2007, *JPSP* 93:880 (BFAS) | Oregon Research Institute, ipip.ori.org | Site states the items, scales and keys are in the public domain and may be freely used, copied, edited and translated | **A** | high | Keys published per scale on the site (which items are reversed, 1–5 Likert, "+"/"−" keyed); facet and domain means or sums | 40+ translations linked from the site; most contributed under the same public-domain statement, some hosted elsewhere with their own notes: check each (QB6) |
| BFI-2, BFI-2-S, BFI-2-XS | Soto & John 2017, *JPSP* 113:117; Soto & John 2017, *J Res Pers* 68:69 (short forms) | Christopher Soto (Colby College page) and Oliver John | Freely available for non-commercial research; permission not needed for that; redistribution in software not addressed | **C** | medium | 60 items 1–5; 5 domains × 3 facets; about half the items reversed (key published) | Many on the Colby page, same terms |
| BFI-44 | John, Donahue & Kentle 1991; John & Srivastava 1999 | Berkeley Personality Lab | Freely available for non-commercial research | **C** | medium | 44 items 1–5, 16 reversed | Lab page lists translations |
| TIPI | Gosling, Rentfrow & Swann 2003, *J Res Pers* 37:504 | Samuel Gosling (UT Austin page) | Page states the TIPI is free to use and no permission is needed; items are in the article | **B** | medium | 10 items 1–7; items 2, 4, 6, 8, 10 reversed; pairs averaged | 20+ translations on the page |
| HEXACO-PI-R (60 / 100 / 200) | Ashton & Lee 2009, *J Pers Assess* 91:340; Lee & Ashton 2018 | Kibeom Lee & Michael Ashton, hexaco.org | Free for non-commercial research with the authors' permission implied by the site; commercial use needs permission; items downloaded from the site | **C** | medium | 6 domains × 4 facets, 1–5, many reversed (key on site) | 20+ on the site |
| NEO-PI-R, NEO-FFI | Costa & McCrae 1992 | PAR | Proprietary | **D** | high | | PAR |
| Rosenberg Self-Esteem Scale | Rosenberg 1965, *Society and the Adolescent Self-Image* | Morris Rosenberg Foundation via University of Maryland Sociology | Page states the scale may be used without explicit permission; the family asks to be kept informed and for the citation | **A** | high | 10 items 0–3 (or 1–4); items 2, 5, 6, 8, 9 reversed; sum 0–30 | Many; none official |
| PANAS | Watson, Clark & Tellegen 1988, *JPSP* 54:1063 | American Psychological Association (journal copyright); PsycTests "may use for research/teaching" | APA permits reproduction of tests from its journals for non-commercial research and teaching without permission; **public redistribution in software is a different use** and needs APA Permissions | **C** | medium | 10 PA + 10 NA items 1–5, two sums 10–50 | Many in literature; I-PANAS-SF (Thompson 2007, *J Cross-Cult Psychol* 38:227, SAGE) same situation |
| SWLS, SPANE, Flourishing Scale | Diener et al. 1985, *J Pers Assess* 49:71; Diener et al. 2010, *Soc Indic Res* 97:143 | Ed Diener's lab page (eddiener.com) | Page states the scales are copyrighted but may be used without permission or charge by researchers and practitioners provided the authors are credited | **A** | high | SWLS 5 items 1–7, sum 5–35; SPANE 12 items 1–5, P, N, balance; FS 8 items 1–7, sum 8–56 | SWLS in 30+ languages on the page |
| WEMWBS, SWEMWBS | Tennant et al. 2007, *Health Qual Life Outcomes* 5:63 | University of Warwick (Warwick Medical School), with NHS Health Scotland and Edinburgh | Free for non-commercial use **after registration per user/project**; copyright notice must appear; no modification; commercial licence otherwise | **D** | high | 14 items 1–5, sum 14–70; SWEMWBS 7 items, metric conversion table | Via Warwick registration only |
| Grit-S | Duckworth & Quinn 2009, *J Pers Assess* 91:166 | Angela Duckworth (Character Lab page) | Free for non-commercial research and educational use | **C** | medium | 8 items 1–5; items 1, 3, 5, 6 reversed; mean | Several, on request |
| Brief Resilience Scale | Smith et al. 2008, *Int J Behav Med* 15:194 | Bruce Smith; Springer journal copyright | Authors say free for research; no formal statement on redistribution | **C** | medium | 6 items 1–5; items 2, 4, 6 reversed; mean | In literature |
| CD-RISC | Connor & Davidson 2003, *Depress Anxiety* 18:76 | cd-risc.com | Agreement and fee (waived for some student use); no redistribution | **D** | high | 25 / 10 / 2 items 0–4 | Via cd-risc.com |
| General Self-Efficacy Scale | Schwarzer & Jerusalem 1995 | Ralf Schwarzer (FU Berlin health page) | Free for non-commercial research and development; the page encourages use; redistribution not addressed | **C** | medium | 10 items 1–4, sum 10–40 | 30+ on the page |
| UCLA Loneliness Scale v3; 3-item short form | Russell 1996, *J Pers Assess* 66:20; Hughes et al. 2004, *Res Aging* 26:655 | Daniel Russell | Permission requested (granted freely for research); copyrighted | **C** | medium | 20 items 1–4, 9 reversed, sum 20–80; 3-item sum 3–9 | In literature |
| MSPSS | Zimet et al. 1988, *J Pers Assess* 52:30 | Gregory Zimet | Author states the scale is free to use and permission is not needed | **B** | medium | 12 items 1–7; family / friends / significant other; means | 40+ posted by the author |
| Brief COPE | Carver 1997, *Int J Behav Med* 4:92 | Charles Carver (University of Miami page) | Page states scales may be used freely without permission | **B** | medium | 28 items 1–4, 14 two-item subscales | Several linked from the page |
| MAAS | Brown & Ryan 2003, *JPSP* 84:822 | Kirk Brown; selfdeterminationtheory.org | Free for research after registering on the SDT site | **C** | medium | 15 items 1–6, mean | SDT site |
| Need for Cognition (18) and NCS-6 | Cacioppo, Petty & Kao 1984, *J Pers Assess* 48:306; Lins de Holanda Coelho et al. 2020 | Journal copyrights | Free for research by custom; no explicit redistribution right | **C** | low | 18 items −4..+4 or 1–5; 9 reversed | In literature |
| Short Dark Triad SD3; Dirty Dozen | Jones & Paulhus 2014, *Assessment* 21:28; Jonason & Webster 2010, *Psychol Assess* 22:420 | Authors (Paulhus posts SD3 freely); APA (Dirty Dozen) | SD3: free for research per the author's site; Dirty Dozen: APA journal rules as PANAS | **C** | medium | SD3 27 items 1–5, 3 subscales, 5 reversed; DD 12 items 1–9 | Some |
| Interpersonal Reactivity Index | Davis 1980 (*JSAS Catalog* 10:85); Davis 1983, *JPSP* 44:113 | Mark Davis (Eckerd College page) | Author's page states the IRI is free to use without permission | **B** | medium | 28 items 0–4, 4 subscales, 9 reversed | In literature |
| Brief Self-Control Scale | Tangney, Baumeister & Boone 2004, *J Pers* 72:271 | Wiley journal copyright; authors permissive | Free for research by custom | **C** | low | 13 items 1–5, 9 reversed, sum | In literature |

### 7.3 Usability, UX, HCI, health, substance use, demographics

| Instrument | Citation | Rights holder, page to verify | Terms as understood | Class | Conf. | Scoring notes | Translations |
|---|---|---|---|---|---|---|---|
| System Usability Scale | Brooke 1996, in *Usability Evaluation in Industry* | John Brooke | Free to use for any purpose provided the source is acknowledged (Brooke's own statement, repeated by him since) | **A** | high | 10 items 1–5 alternating; odd items −1, even items 5−x, ×2.5 (0–100) | Many validated translations in literature |
| UMUX, UMUX-Lite | Finstad 2010, *Interact Comput* 22:323; Lewis, Utesch & Maher 2013, CHI | Elsevier / ACM article copyrights; the authors treat the items as free | Free to use by custom; the 2–4 items are short | **B** | medium | UMUX 4 items 1–7, 0–100; UMUX-Lite 2 items, regression to SUS scale | Few |
| PSSUQ / CSUQ | Lewis 1995, *Int J Hum-Comput Interact* 7:57; Lewis 2002 | James Lewis (IBM released the questionnaires for free use) | Author states free to use with citation | **B** | medium | 16 items 1–7 (v3), overall + 3 subscales | Some |
| UEQ, UEQ-S | Laugwitz, Held & Schrepp 2008; Schrepp, Hinderks & Thomaschewski 2017 | ueq-online.org (Schrepp) | Site states the UEQ is free for commercial and non-commercial use with citation; the analysis tool is also free | **B** | medium | 26 bipolar items −3..+3, 6 scales; UEQ-S 8 items | 30+ on the site |
| NASA-TLX | Hart & Staveland 1988 | NASA Ames (US government work) | Public domain | **A** | high | 6 subscales 0–100; optional pairwise weights | NASA distributes some |
| "Likelihood to recommend" 0–10 (NPS) | Reichheld 2003, *Harv Bus Rev* | Net Promoter and NPS are registered trademarks of Bain & Company, NICE Systems and Fred Reichheld; the question itself is a plain sentence | Bundle the question and the promoter/passive/detractor recipe; **name the item "Likelihood to recommend" and show the trademark attribution** in the description | **A** (with notice) | high | % 9–10 minus % 0–6 | n/a |
| Self-Assessment Manikin | Bradley & Lang 1994, *J Behav Ther Exp Psychiatry* 25:49 | Peter Lang, CSEA, University of Florida | Pictograms copyrighted; provided to researchers on request; not for redistribution | **D** (images); a text/slider variant of the three dimensions can be bundled as our own wording, not called SAM | high | Valence, arousal, dominance 1–9 | n/a |
| Intrinsic Motivation Inventory; Basic Psychological Need Satisfaction | Ryan 1982; McAuley et al. 1989; Deci & Ryan | selfdeterminationtheory.org | Free for academic research after registration; the site asks users to download from it | **C** | medium | IMI subscale means 1–7, some reversed | SDT site |
| Cognitive Reflection Test; CRT-2 | Frederick 2005, *J Econ Perspect* 19:25; Thomson & Oppenheimer 2016, *Judgm Decis Mak* 11:99 | Journal copyrights; CRT-2 in an open-access journal (JDM, CC BY) | CRT items are three short puzzles, now widely known; CRT-2 published under CC BY | **A** for CRT-2 (CC BY 4.0, cite); **B** for the original CRT | medium | Count correct (0–3 / 0–4); note item familiarity | Several |
| SF-36 / SF-12 | Ware & Sherbourne 1992 | QualityMetric (now part of a commercial PRO group) | Proprietary licence | **D** | high | | QualityMetric |
| RAND-36 | Hays, Sherbourne & Mazel 1993, *Health Econ* 2:217 | RAND Corporation | RAND's page grants permission to use free of charge with conditions (cite RAND, no changes, no fees); **check whether redistribution inside software is within the grant** | **B** | medium | 8 scales 0–100 per RAND's recoding table | RAND lists some |
| EQ-5D-5L / -3L | EuroQol Group | EuroQol Research Foundation | Registration and licence per study; free for non-commercial academic use but every use registered; no redistribution | **D** | high | 5 dimensions + VAS; index via country value sets | EuroQol only |
| PROMIS short forms | Cella et al. 2010, *J Clin Epidemiol* 63:1179 | HealthMeasures (Northwestern) terms of use | Free for individual research and clinical use; **incorporation into software products requires a licence** from HealthMeasures; no modification; copyright line must show | **C** | medium | T-scores via published tables | HealthMeasures |
| WHOQOL-BREF | WHOQOL Group 1998, *Psychol Med* 28:551 | WHO | Permission and a user agreement through WHO; free for non-commercial research | **D** | medium | 4 domains transformed 0–100 | WHO |
| AUDIT, AUDIT-C | Saunders et al. 1993, *Addiction* 88:791; Babor et al. 2001 (WHO manual); Bush et al. 1998 (AUDIT-C) | WHO (manual); AUDIT-C from US VA work | WHO manual permits reproduction for non-commercial use; AUDIT is treated as freely reproducible by national agencies (NIAAA, NHS); AUDIT-C is US government work | **B** (AUDIT), **A** (AUDIT-C) | medium | Sum 10 items 0–4 (0–40), ≥ 8; AUDIT-C 0–12, ≥ 4 men / ≥ 3 women | WHO + national agencies |
| ASSIST (WHO) | WHO ASSIST Working Group 2002, *Addiction* 97:1183 | WHO | Reproduction for non-commercial use permitted under WHO's terms; verify current CC BY-NC-SA IGO licence (non-commercial, share-alike: **not in our allow-list**) | **C** | medium | Substance involvement scores | WHO |
| FTND / Fagerström Test for Cigarette Dependence | Heatherton et al. 1991, *Br J Addict* 86:1119; Fagerström 2012 | Karl Fagerström | Author has stated the test is in the public domain | **B** | medium | 6 items, sum 0–10 | Many |
| DUDIT | Berman et al. 2005, *Eur Addict Res* 11:22 | Karolinska Institutet (Berman) | Free to use; manual downloadable | **B** | medium | 11 items, 0–44, ≥ 6 men / ≥ 2 women | KI |
| IPAQ short form | Craig et al. 2003, *Med Sci Sports Exerc* 35:1381 | IPAQ group (ipaq.ki.se / sites.google.com/view/ipaq) | Site states no permission is required to use the IPAQ | **B** | medium | MET-minutes per week; categorical low/moderate/high per the scoring protocol | 20+ on the site |
| ACE questionnaire (10 items) | Felitti et al. 1998, *Am J Prev Med* 14:245 | CDC-Kaiser ACE Study (US government work) | Public domain | **A** | high | Count of yes answers 0–10 | CDC; WHO ACE-IQ separately (**B**, WHO terms) |
| MacArthur Scale of Subjective Social Status | Adler et al. 2000, *Health Psychol* 19:586 | MacArthur Network on SES and Health (UCSF page) | Freely available; ladder image is theirs | **B** | medium | 1–10 rung | Several |
| Maslach Burnout Inventory | Maslach & Jackson 1981 | Mind Garden | Proprietary | **D** | high | | Mind Garden |
| Oldenburg Burnout Inventory | Demerouti et al. 2003 | Evangelia Demerouti | Free for research on request | **C** | medium | 16 items 1–4, 8 reversed, exhaustion + disengagement | Several |
| Copenhagen Burnout Inventory | Kristensen et al. 2005, *Work Stress* 19:192 | National Research Centre for the Working Environment, Denmark | Public and free | **B** | medium | 3 scales, 0–100 recoding | NFA lists several |
| TAM items; UTAUT items | Davis 1989, *MIS Q* 13:319; Venkatesh et al. 2003, *MIS Q* 27:425 | MIS Quarterly (journal copyright) | Academic reuse by custom; no redistribution right; items are usually adapted per system anyway | **C** | low | 7-point agreement; means per construct | n/a |

### 7.4 Standard demographic and background questions (bundle)

Not "instruments", but the most inserted questions of all, and clearly redistributable:

| Set | Holder, licence | Class | Notes |
|---|---|---|---|
| UK ONS harmonised standards (age, sex, gender identity, ethnic group, religion, disability, economic activity, education, household) | Office for National Statistics / Government Statistical Service, **Open Government Licence v3** (attribution; compatible with CC BY 4.0) | **A** | Country-specific wording per UK nation; ship with the OGL attribution line |
| US Census / ACS questions (age, sex, race, Hispanic origin, education, income bands) | US Census Bureau, US government work | **A** | Public domain |
| Eurostat / ESS core demographics (ESS source questionnaire) | European Social Survey ERIC; ESS data and documentation are free to use with citation (check the questionnaire licence: believed CC BY-NC-SA for documents, which is **not** in our allow-list) | **C** | Ask ESS, or write our own equivalents |
| Our own plain demographics (age in years, country, first language, handedness, vision correction, prior participation) | Written for this project, CC0 | **A** | The default set in the bundled library |

### 7.5 Verdict summary and what ships first

- **Bundle in QB2 (class A, after the source check):** PHQ-9 / PHQ-2 / PHQ-15 / GAD-7 / GAD-2; CES-D; DASS-21; PCL-5; IPIP (IPIP-NEO-120, Mini-IPIP, 50-item markers, BFAS, plus a mechanism to load any IPIP scale from its published key); Rosenberg; SWLS / SPANE / Flourishing; SUS; NASA-TLX; Likelihood to recommend (NPS notice); CRT-2; AUDIT-C; ACE-10; ONS / Census demographics; our own demographics.
- **Verify, then bundle in QB2 or QB6 (class B):** K10 / K6, WHO-5, EPDS, TIPI, MSPSS, Brief COPE, IRI, UMUX / UMUX-Lite, PSSUQ / CSUQ, UEQ, RAND-36, AUDIT, FTND, DUDIT, IPAQ, MacArthur ladder, CBI, original CRT.
- **Ask the holder; stub meanwhile (class C):** PSS, C-SSRS, PSQI, BFI-2 and BFI-44, HEXACO, PANAS and I-PANAS-SF, Grit-S, BRS, GSE, UCLA Loneliness, MAAS, NCS, SD3 / Dirty Dozen, Brief Self-Control, IMI / BPNS, PROMIS, ASSIST, OLBI, TAM / UTAUT, ESS demographics. The letter (one per holder, from the project, not a worker) asks for permission to include the English items and response options, unmodified, with the citation and the holder's conditions shown at insert, in an MIT-licensed survey tool whose users are mostly academic researchers; and records the answer in `osp-instruments/permissions/`. Several of these holders (Cohen, Soto, Gosling, Schwarzer, Zimet, Carver, Duckworth) are known to answer such requests favourably; PANAS (APA) and PROMIS are the ones most likely to say no.
- **Do not bundle; stub + private licensed copy (class D):** BDI-II, BAI, STAI, HADS, GHQ-12, MBI, NEO, CD-RISC, WEMWBS / SWEMWBS, SDQ, ISI, Epworth, SF-36 / SF-12, EQ-5D, WHOQOL-BREF, SAM pictograms. The stub carries title, citation, holder link, item count, response format and the scoring recipe as computed variables over placeholder ids, so that a lab's private copy gets scoring for free. Whether shipping the *recipe* of a proprietary instrument is itself a problem is a question for the lead and the other LLMs (§11 Q5); scoring rules are published in the literature and are facts, not expression, but the lead should decide.
- **Not in any allow-list, flag for a human:** GESIS ZIS instruments (CC BY-SA 4.0: share-alike), WHO documents under CC BY-NC-SA 3.0 IGO, ESS documentation. Our licence policy allows CC BY 4.0 but neither SA nor NC; treat as class C unless the lead adds a content-licence exception.

### 7.6 Attribution and notices that ship with the library

- Every bundled item shows its citation and licence statement in the Bank tab, on insert, and in the codebook's "Instruments used" section; a `NOTICES.md` generated from the library lists every instrument, holder, licence and URL, and the participant-facing survey can optionally print the citation line on the last page (off by default).
- Trademark notice for the NPS question; OGL attribution for ONS questions; "Reproduced with permission" for class C items that were granted, with the permission file name.
- Translations are listed per language with their own source and terms; a translation is never bundled on the strength of the English item's licence alone.

## 8. Order of work (proposed task split; the lead creates the rows)

1. **QB2 spec + instruments package**: `osp_spec.bank` (model, `extract_fragment`, `check_fragment`), `Source` on question/page/block (+ capability rows, codebook section, golden), `osp-instruments` with the first bundled set and its tests, licence-policy step. **Acceptance criterion 1:** for every bundled instrument, `osp-instruments/LICENCES.md` quotes the operative sentence of the holder's current terms page with URL and access date, checked by a second person; a test fails on any library file whose licence class is not in the bundle allow-list or whose `LICENCES.md` entry is missing.
2. **QB3 ops**: `insert_bank_item`, `clear_source`, the shared `_remap`, fuzz.
3. **QB4 store + app + API**: migration 0011, `osp_store.bank`, permissions, commands, routes, contract, import/export file, audit.
4. **QB5 builder**: Bank tab (search, preview, insert, drag), Save to bank, provenance line, Bank page, licensed-instrument wizard, docs, e2e + axe.
5. **QB6 translations**: ship the translations §7 allows (PHQ/GAD from the screeners site, IPIP translations where the translators placed them in the public domain), language filter, codebook language note.

Each is a normal task: `make check` green, acceptance criteria with tests, devlog entry.

## 9. Prior art (public docs and terms only; nothing copied)

As with §7, written from the worker's knowledge of public documentation; the pages were not fetched in this session. Nothing below was taken from any product's source code.

| Tool / catalogue | What a bank item is | Insert | Provenance, versions | Sharing | Licensing handling | What we take (idea only) |
|---|---|---|---|---|---|---|
| REDCap Shared Library | A whole data-collection instrument (form) with its data dictionary | Copied into the project, then editable | Library id kept in the project; no live link; new library versions are not pushed | Public library, curated; institutions submit | Some instruments are marked as requiring a licence; the user must accept the holder's agreement in a click-through before download; PROMIS is served through a separate licensed path | Per-instrument agreement screen; "licensed" flag that changes the insert flow |
| Qualtrics libraries | Questions, blocks, whole surveys, graphics, messages | Copied; "copy from library" | None kept after copy | Personal / group / organisation libraries | None (user's responsibility) | Three sharing levels; the toolbox-side library |
| KoboToolbox library | Questions, blocks ("question blocks"), templates, collections | Copied into the form | None after copy | Private, organisation, public, with collections | None | Collections as tags; public items with a licence field (Kobo asks for a licence on public sharing) |
| LimeSurvey | Question themes and survey templates; no question bank in the core product (community plugins only) | Import a survey structure file | None | File based | None | The file-based path (`*.lss`) as the portable fallback |
| SurveyJS Creator | Toolbox custom items defined by the integrator (JSON) | Copied | None | Per integration | None | The toolbox tab |
| formr.org | Item tables (spreadsheets) per survey; surveys reusable in runs | Reference by sheet | Git / spreadsheet history | Public runs can be copied | None | Spreadsheet import of item lists |
| PsyToolkit survey library | Whole questionnaires with scoring scripts | Copied into the experiment | None | Public | Each entry names the source paper and notes the copyright position; items of proprietary instruments are not hosted | The per-entry "copyright position" note; the scoring script shipped with the items |
| GESIS ZIS | A documented instrument (items, scoring, psychometrics, DOI) | Download | DOI per instrument version | Public, CC BY-SA 4.0 | The licence is uniform across the collection | The metadata record shape; **not** the content (SA) |
| PhenX Toolkit | A protocol (instrument + administration notes) | Download / REDCap export | Protocol id and release version | Public | A "requires permission / fee" marker per protocol pointing to the holder | The per-protocol licence marker |
| HealthMeasures (PROMIS) | Short forms and item banks | Download after accepting terms | Version per short form | Public with terms | Software integration needs a licence | The distinction between "use" and "integrate into software" |
| DDI-Lifecycle | `QuestionItem` / `QuestionGrid` in `QuestionScheme`s, with URN identifiers, versions, concepts, universes | Reference by URN | Versioned URNs, agency ids | Repositories (CLOSER, UKDS) | Per repository | The provenance record: agency + id + version; our `source` field is a tiny version of that; `metadata.ddi` already exists for a fuller mapping later |
| APA PsycTests | A test record with a permissions field ("may use for research/teaching", "contact publisher", "fee required") | n/a | n/a | Subscription database | The permissions taxonomy | Our `licence.class` vocabulary is the same idea in six values |
| Open-Source Psychometrics Project | Hosted public-domain tests with items and data | n/a | n/a | Public | Each test page states the copyright position; proprietary tests are not hosted | Same policy as ours |

Fields a well-formed bank record carries, drawn from DDI / ZIS / PhenX practice, all present in §2.1: stable id + version, title and abbreviation, construct tags, language(s), item text with response options, scoring, citation with DOI, source URL, licence class with the holder and the evidence date, provenance of copies, and psychometric notes (free text in `description` for now).

## 10. Open questions for the lead

1. **Provenance field name and placement.** `source` on question/page/block (§2.3) versus a survey-level list. The plan recommends the per-object field. Does the lead also want `metadata.instruments` as a dedicated field rather than the free-form `metadata.ddi`?
2. **Host-level sharing is read-only and opt-in per item.** Should a host admin be able to switch it off entirely (a `BANK_HOST_SHARING` host setting) for hosts that run unrelated labs?
3. **Default licence class for a lab's own questions.** `unknown` (safe, nags at share time) or `cc-by-4.0` (encourages sharing, but asserts something the researcher may not have thought about)? Recommended: `unknown` for lab items, with a one-click "these are our own words, CC BY 4.0" at share time.
4. **Free-for-non-commercial instruments** (§7.2) could be bundled behind a per-host switch ("this host is a non-commercial research host"), as some tools do. The plan does not recommend it: our licence policy treats "non-commercial only" as not permissive, and a stub plus a private copy keeps every host on the right side. Lead to confirm.
5. **Asking rights holders.** For the *ask* rows the project (not a worker) should write to the holders once with a standard letter (§7.4); permission letters would live in `osp-instruments/permissions/`. Who sends it?
6. **A community registry** (labs publishing items to a public index) is out of this plan. Worth a later row, or never?

## 11. Review brief for GPT / Gemini / Qwen (to be run by the lead)

Paste `planning/question-bank.md` and ask:

1. Is the bundle / ask / do-not-bundle classification of §7 right, instrument by instrument? Name any row where the rights holder's current terms contradict the table, with the URL.
2. Which widely used instruments in psychology, HCI and health research are missing from §7 and are clearly redistributable (public domain or an open licence)?
3. Is a per-object `source` field the right provenance design, or is there a cleaner one that survives moves, duplicates and version pins?
4. Fragment extraction cuts external references at save time. Is there a case where researchers would expect something else?
5. Is "stub + private licensed copy" an acceptable experience for BDI-II / STAI / HADS users, and is there a legal risk in shipping the *scoring recipe* and *item count* of a proprietary instrument without its text?
6. Anything in the sharing model (lab / host / file) that creates a licence or privacy problem?

Record their answers at the end of this file under "Review log" with what was changed as a result.
