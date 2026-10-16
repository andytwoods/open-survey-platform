# Open Survey Platform — Critical Review of `overview.md`

**Date:** 16 October 2026
**Scope:** Answers §11 and produces the outputs requested in §12. No code is written yet.
**Labels used:** **[V]** = checked during this review (source given) · **[A]** = assumption / reviewer judgement · **[R]** = risk.

---

## 0. Headline conclusions

1. **Do not adopt Formspec as the canonical format.** It is a 7-month-old, mostly single-author project, has been relicensed twice, and its expression language explicitly excludes randomness (§1.2).
2. **Define a small, versioned, project-owned canonical JSON model** (call it `osp-survey` v0). Borrow semantics from XLSForm/ODK XForms (questions, relevance, constraints) and metadata concepts from DDI. Treat all other formats as adapters.
3. **Decided (16 Oct 2026, revised): own builder; participants run in Enketo (Apache-2.0) served by our own backend (§2.6).** We don't write a renderer: Enketo is it. One backend. LimeSurvey, SurveyJS, QSF, queXML and surveydown are export targets. XLSForm is both an export target and the path into Enketo.
4. **One engine, one semantics.** Write the flow/logic engine once, as a pure function over JSON. Run identical conformance fixtures against every runtime that executes it (§6).
5. **The MVP is smaller than Phase 1.** The real differentiators are seeded randomisation, the logic trace and path testing. Ship those on a thin builder rather than a broad builder without them (§4).
6. **Existing builders change the plan (§12).** SurveyJS Creator is commercial, so it can't sit in an open-source core. Form.io's builder is MIT and React-free, so it can. KoboToolbox, Formbricks and HeyForm are AGPL. **Outbound licence decided: MIT (16 Oct 2026).** So only permissive code is reusable. AGPL/GPL tools are design references only.
7. **The 12–15 month estimate is optimistic** for the full six phases. For a solo developer with AI assistance, a credible pilot-ready MVP is about 4–5 months, with LimeSurvey as the runtime. The full brief is about 2–3 years (§7).

---

## 1. Feasibility review

### 1.1 Verified facts

| Claim | Status | Evidence |
|---|---|---|
| Formspec exists, JSON-native, Apache-2.0 runtime | **[V]** | github.com/Formspec-Labs/formspec |
| Formspec repo created 2026-03-26, 4 stars, ~2,966 of ~2,995 commits by one author | **[V]** | GitHub API, 16 Oct 2026 |
| Formspec relicensed MIT → AGPL-3.0 → Apache-2.0 + BSL 1.1 (authoring tools BSL until 2030) | **[V]** | `LICENSING.md` in repo |
| Formspec expression language is "deterministic + sandboxed … no random" | **[V]** | `FORMSPEC-FEATURE-MATRIX.md` §2.15 |
| Formspec targets government/compliance forms (money types, signatures, audit) rather than research surveys | **[V]** | feature matrix |
| SurveyJS Form Library is MIT; Survey Creator (builder) needs a paid developer licence for commercial use | **[V]** | surveyjs.io/Licenses |
| SurveyJS ships a framework-free renderer (`survey-js-ui`) next to React/Angular/Vue | **[V]** | `packages/` in surveyjs/survey-library |
| pyxform (XLSForm) is BSD-2-Clause and actively maintained | **[V]** | GitHub API |
| Enketo (XForms renderer) is Apache-2.0 | **[V]** | GitHub API |
| jsPsych is MIT and active | **[V]** | GitHub API |
| LimeSurvey is GPL (v2+) | **[A]** — GitHub reports `NOASSERTION`; confirm from its `LICENSE` file | — |
| SAS v WPL: CJEU C-406/10 (2012) held functionality, programming languages and data-file formats are not protected as such by the Software Directive. SAS later lost again in England (High Court 2020, Court of Appeal 2022) and in the US (Fed. Cir. 2023 affirmed) | **[V]** partly: US outcome and UK loss confirmed. **[A]** exact UK citation not retrieved | managingip.com; cafc.uscourts.gov opinion 21-1542 |

### 1.2 Key assumptions in the brief that need challenge

- **[A] "Match most of the core Qualtrics builder"** is the main scope risk. Qualtrics' builder took a large team many years. Pick the ~20% of features used in ~80% of academic surveys and measure that. Use a sample of real QSF files from your own institution.
- **[A] "Text and GUI edit the same model, kept consistent."** This is achievable only if the text view is the canonical JSON (or a lossless YAML projection of it). A *friendlier* DSL with round-trip formatting (comments, ordering) is a project on its own. Defer it.
- **[A] "htmx/Alpine for a rich editor."** Resolved: the whole UI is Svelte (§9 Q2).
- **[A] "Server-side authoritative logic"** combined with a participant renderer meant logic running in two places. *Resolved:* no own renderer; the remaining split is our Python engine vs. LimeSurvey (§2.5).

### 1.3 Major risks (ranked)

1. **[R] Semantic drift** between our Python engine (debugger, simulator) and LimeSurvey (the real runtime). If they disagree, the debugger misleads researchers. Mitigation: a small supported feature set, the equivalence harness as a release gate, one pinned LimeSurvey version (§2.5).
2. **[R] Scope.** Six differentiators plus Qualtrics parity plus five interchange formats is too much for one developer.
3. **[R] QSF fidelity.** QSF is undocumented, and its JavaScript-in-questions, Loop & Merge and quota semantics will not map cleanly (§5).
4. **[R] Data protection.** A hosted instance holding research responses is a GDPR controller/processor question for every institution that uses it. It must pass IT security review before any pilot.
5. **[R] Plugin security.** Third-party JS running on participant pages can exfiltrate responses (§8).

---

## 2. Canonical specification recommendation

### 2.1 Comparison matrix

Scores: ● strong · ◐ partial · ○ weak/absent. **[A]** except where §1.1 verified.

| Criterion | Formspec | SurveyJS JSON | XLSForm / ODK XForms | DDI Lifecycle | queXML | Qualtrics QSF | LimeSurvey LSS | **Own `osp-survey`** |
|---|---|---|---|---|---|---|---|---|
| Open licence for spec | ● | ◐ (vendor-owned, MIT code) | ● | ● | ● | ○ proprietary | ◐ GPL tooling | ● |
| Independent governance | ○ one author | ○ vendor | ● ODK/XLSForm org | ● DDI Alliance | ◐ | ○ | ○ | ◐ you |
| Maturity / adoption | ○ | ● | ● | ● (archives) | ○ | ● | ● | ○ |
| Research question types (matrix, slider, rank) | ◐ | ● | ◐ | ◐ metadata only | ◐ | ● | ● | ● (by design) |
| Branching / display logic | ● | ● | ● | ◐ | ◐ | ● | ● | ● |
| Randomisation (items, blocks, conditions) | ○ excluded | ◐ order only | ◐ `randomize` on choices/repeats | ○ | ○ | ● | ◐ | ● |
| Experimental design / counterbalancing | ○ | ○ | ○ | ○ | ○ | ◐ randomiser elements | ○ | ● |
| Quotas | ○ | ○ | ○ | ○ | ○ | ● | ● | ● |
| Provenance / codebook metadata | ◐ | ○ | ◐ | ● | ◐ | ○ | ○ | ● (borrow DDI terms) |
| Ready runtime to reuse | ◐ (new) | ● MIT | ● Enketo | ○ | ○ | ○ | ○ | ○ (unless SurveyJS) |
| Fits "runtime model" role | ◐ | ● | ● | ○ | ○ | ○ | ○ | ● |

### 2.2 Recommendation

- **Canonical:** a project-owned `osp-survey` JSON model with a published JSON Schema, a semantic validator, and a `specVersion` field from day one.
- **Design it as a superset of the XLSForm core semantics** (types, `relevant`, `constraint`, `required`, `calculate`, choice lists). XLSForm is the most mature open, independently governed survey model. Aligning with it makes XLSForm export near-lossless for the common subset.
- **Add research layers XLSForm lacks:** `flow` (blocks, branches, randomisers, end points), `design` (factors, conditions, allocation), `quotas`, `embeddedData`, and `metadata` (DDI-aligned: concept, universe, citation, licence).
- **Expressions:** a small, side-effect-free expression language stored as a **parsed AST in JSON** (JsonLogic-style), with a text surface syntax for the editor. Randomness never appears inside expressions. It enters only through the flow layer's seeded randomiser nodes. That keeps expressions pure and replayable, the same reason Formspec forbids it, while still supporting experiments.
- **Keep Formspec on a watch list.** Revisit in 12 months for governance, adoption and licence stability. Its cross-runtime parity-testing approach (Rust core → WASM + PyO3 + shared fixtures) is worth copying even if the format is not.
- **Other platforms are export targets, never dependencies.** `osp-survey` is the source of truth. Each target gets a one-way transpiler plus diagnostics (§2.4).

### 2.4 Transpilation to other platforms (decided goal)

Every survey must be exportable to other platforms, with honest reporting of what didn't survive.

**Architecture:**
```text
osp-survey ──► normalise (resolve choice lists, expand scores, inline defaults)
           ──► lower (rewrite features the target lacks into ones it has, where semantics are kept)
           ──► emit (target format)
           ──► diagnostics[]  {code, severity: info|warn|loss, sourcePath, target, message}
```
- **Capability table per target**, kept as data (`targets/surveyjs.yaml` etc.). Each feature is `native`, `lowered` (equivalent rewrite), `approximated` (behaviour differs; warn) or `unsupported` (dropped; `loss`). The builder reads this table to show live badges like "this randomiser won't export to XLSForm".
- **"Export-safe" mode:** the researcher picks target platforms up front. The builder then flags features those targets can't express *while they edit*, not at export time.
- **Lowering examples:** a seeded between-subjects assignment becomes, in SurveyJS, a hidden question set by a `random` expression. That's `approximated`, because SurveyJS's RNG isn't our seeded PRNG, so the stored seed no longer reproduces the run. In LimeSurvey it becomes an equation question plus randomisation groups. Quotas map natively to LimeSurvey and QSF and are `unsupported` in XLSForm.
- **Verification:** for each target, keep a corpus of `osp-survey` fixtures. Run behavioural equivalence (§5.3) where the target can be executed headlessly. The SurveyJS runtime and Enketo both can, in CI, as *test tools only*. LimeSurvey and Qualtrics need manual import checks per release.
- **Legal [A]:** writing files in another vendor's format is interoperability. Don't use their names or logos in our branding beyond plain "Export to SurveyJS / LimeSurvey" labels.

**Target priority [A]:**

| Order | Target | Why | Difficulty |
|---|---|---|---|
| 1 | SurveyJS JSON | JSON-to-JSON, documented, MIT runtime for automated equivalence tests | Low |
| 2 | XLSForm | Open, independently governed, huge field-research user base; pyxform validates output | Low–medium |
| 3 | LimeSurvey LSS | Main open-source academic platform; has quotas | Medium–high (ExpressionScript, SGQA naming) |
| 4 | Qualtrics QSF | Migration *back* to/from Qualtrics; undocumented | High |
| 5 | queXML | Documentation/paper; small user base | Medium |
| 6 | surveydown (R, `.qmd`) | Reproducibility-minded R users; text format is readable. MIT | Medium (logic becomes R code in `app.R`) |

Import (the reverse direction) is a separate, harder project per format (§5). Treat it as post-v1, except possibly QSF import for migration.

### 2.3 Worked complex example (abbreviated `osp-survey` v0)

Consent gate → demographics → 2×2 between-subjects design (framing × incentive), counterbalanced item order inside one block, a quota on age band, piped text, and a computed score.

```json
{
  "specVersion": "osp-survey/0.1",
  "id": "srv_7f3c",
  "version": 3,
  "metadata": {
    "title": "Framing and incentive study",
    "languages": ["en", "de"],
    "license": "CC-BY-4.0",
    "ddi": { "universe": "UK adults 18+", "studyUnit": "doi:10.xxxx/placeholder" }
  },
  "embeddedData": [
    { "name": "source", "from": "url", "param": "src", "default": "direct" }
  ],
  "choiceLists": {
    "yesno": [{ "value": 1, "label": { "en": "Yes", "de": "Ja" } },
              { "value": 0, "label": { "en": "No",  "de": "Nein" } }],
    "agree5": [{ "value": 1, "label": "Strongly disagree" }, { "value": 2, "label": "Disagree" },
               { "value": 3, "label": "Neutral" }, { "value": 4, "label": "Agree" },
               { "value": 5, "label": "Strongly agree" }]
  },
  "blocks": {
    "consent": { "items": [
      { "id": "consent", "type": "single", "choices": "yesno", "required": true,
        "label": { "en": "Do you consent to take part?" } }
    ]},
    "demo": { "items": [
      { "id": "age", "type": "integer", "required": true,
        "constraint": { "and": [{ ">=": [{ "var": "age" }, 18] }, { "<=": [{ "var": "age" }, 120] }] },
        "constraintMessage": "Please enter an age between 18 and 120." },
      { "id": "age_band", "type": "calculate",
        "expr": { "if": [{ "<": [{ "var": "age" }, 40] }, "18-39", "40+"] } }
    ]},
    "stim_gain":  { "items": [{ "id": "stim_g", "type": "note", "label": "Programme A saves 200 people…" }] },
    "stim_loss":  { "items": [{ "id": "stim_l", "type": "note", "label": "With Programme A, 400 people die…" }] },
    "attitudes": {
      "itemOrder": { "randomize": "shuffle" },
      "items": [
        { "id": "att1", "type": "single", "choices": "agree5",
          "label": "With the ${incentive} you were offered, the programme seems fair." },
        { "id": "att2", "type": "single", "choices": "agree5", "label": "I would support Programme A.",
          "reverseScored": false },
        { "id": "att3", "type": "single", "choices": "agree5", "label": "Programme A is too risky.",
          "reverseScored": true }
      ]
    },
    "screenout": { "items": [{ "id": "bye", "type": "note", "label": "Thank you. This study is now closed." }] }
  },
  "scores": [
    { "id": "att_score", "method": "mean", "items": ["att1", "att2", "att3"], "reverse": { "max": 5, "min": 1 } }
  ],
  "design": {
    "factors": [
      { "id": "framing",   "levels": ["gain", "loss"] },
      { "id": "incentive", "levels": ["£5 voucher", "charity donation"] }
    ],
    "between": ["framing", "incentive"],
    "allocation": { "runtime": "osp-redirect", "method": "balanced", "strata": ["age_band"], "fallback": "seeded-random" }
  },
  "quotas": [
    { "id": "q_old", "when": { "==": [{ "var": "age_band" }, "40+"] }, "limit": 150,
      "onFull": { "goto": "screenout" }, "countOn": "complete" }
  ],
  "flow": [
    { "block": "consent" },
    { "branch": { "if": { "==": [{ "var": "consent" }, 0] }, "then": [{ "end": "declined" }] } },
    { "block": "demo" },
    { "quotaCheck": "q_old" },
    { "assign": "design" },
    { "branch": { "if": { "==": [{ "var": "framing" }, "gain"] },
                  "then": [{ "block": "stim_gain" }], "else": [{ "block": "stim_loss" }] } },
    { "block": "attitudes" },
    { "end": "complete" }
  ]
}
```

Points this example forces the format to decide:
- `assign` writes `framing` and `incentive` into the response as **recorded variables**, so piping (`${incentive}`) and exports see them.
- `itemOrder.randomize` is resolved from the session seed. The realised order is **stored in the response** (`_order.attitudes = ["att3","att1","att2"]`).
- `allocation: balanced` needs **server state**. `seeded-random` does not. The format must say which is used, and the response must record which one actually ran.
- **Open problem (found in cross-LLM review):** stratifying on `age_band` needs the age *before* allocation, but in `osp-redirect` mode allocation happens at the entry redirect, before LimeSurvey collects age. Options: collect strata on our entry page, split into two LimeSurvey surveys, or call back to our server mid-survey. Unresolved; MVP uses unstratified allocation only.
- **Redirect integrity:** `cond`/`seed` in the URL can be tampered with or re-rolled by revisiting. Sign the parameters (HMAC) and make the allocation sticky per participant token.

---

### 2.5 Runtime: LimeSurvey by default (decided direction, 16 Oct 2026)

We don't build a participant renderer. Surveys are deployed to **LimeSurvey** (the researcher's own instance, their university's, or LimeSurvey Cloud). Other export targets stay available.

**Verified facts [V]:**
- LimeSurvey is **GPL-2.0-or-later** (`LICENSE` in repo). We only generate `.lss` files and call its RemoteControl JSON-RPC API. We don't link to or copy its code, so our MIT licence is unaffected **[A — confirm with counsel]**.
- LimeSurvey stores a per-response `seed` column (added in update 290) and shuffles with its own Mersenne Twister helper (`RandomizerHelper.php`). So a LimeSurvey run's question order is stable for that response, but **it follows LimeSurvey's algorithm, not ours**.

**What we gain:**
- No renderer, participant sessions or response database. Probably 1.5–2.5 months off the MVP **[A]**.
- **We hold less participant data.** Responses live in the institution's LimeSurvey. But we *do* process them when pulling responses for codebooks and repro packages (and see IPs in `osp-redirect` mode), so we are still a processor for that step. Pulled data must have retention/deletion rules.
- Mature question types, accessibility work, themes, multilingual, save/resume and quotas, already in LimeSurvey.
- Many universities already run LimeSurvey.

**What we lose or must work around (the important part):**

| Differentiator (brief §4.3) | Problem with LimeSurvey as runtime | Workaround |
|---|---|---|
| A. Debugger | Our engine's trace is a *model* of LimeSurvey, not LimeSurvey itself | Equivalence harness (MVP item 5) proves they match for each fixture. Plus "open in LimeSurvey preview" |
| B. Automated testing | Same: we test our model | Same harness. Restrict MVP features to ones the harness covers |
| C. Seeded assignment / experiments | LimeSurvey's RNG isn't seeded by us | **Decided: a per-survey option, settable in the builder and via the API** (`design.allocation.runtime`). `"limesurvey-native"` (**default**): LimeSurvey randomises; we store its `seed`; no participant-facing component of ours; can't be replayed independently; no balanced allocation. `"osp-redirect"`: our server allocates and redirects to LimeSurvey with `?cond=…&seed=…` filled into hidden questions; reproducible; enables balanced allocation; needs our server reachable by participants (uptime, and we briefly see their IP). Transpiler lowers differently per mode; each response records which mode ran |
| C. Item/block order randomisation | Same | Use LimeSurvey's native randomisation, export the realised order if LimeSurvey records it **[A — check]**, otherwise lower to equation questions driven by our `seed` param |
| D. Reproducibility package | Runtime version is LimeSurvey's | Record LimeSurvey version (from API) + exact `.lss` deployed + our version in the package |
| Feature semantics | LimeSurvey ExpressionScript and `.NAOK` behaviour define truth | Design `osp-survey` v0 so that every MVP feature lowers to LSS as `native` or `lowered`. No `approximated` features in v0 |

**Other risks [R]:**
- LSS format changes between LimeSurvey versions (3.x, 5.x, 6.x). Support a narrow, stated version range.
- RemoteControl API must be enabled by the LimeSurvey admin. Some university instances disable it. Fallback: download `.lss` and import manually.
- LimeSurvey GmbH leads development. Unlike SurveyJS, the code is GPL and self-hostable, so vendor risk is lower but not zero.
- Researchers still use LimeSurvey's admin for some tasks (activation, tokens, response viewing). Be clear which tool owns what.

**Export target order (replaces the §2.4 table order):** LimeSurvey LSS → XLSForm → SurveyJS JSON → QSF → queXML → surveydown.

---

### 2.6 Runtime: Enketo (decided 16 Oct 2026, supersedes §2.5)

> **Superseded 16 Oct 2026** by `planning/runtime-design.md`: we build our own browser runtime. Enketo/XLSForm is an export target only. Kept for the spike lessons.


**Why:** Enketo is an Apache-2.0 browser form engine built on the open ODK XForms standard. It replaces both our own renderer and LimeSurvey as the runtime, so there's **one backend (ours)**. LimeSurvey stays an export target, and §2.5 is kept for reference.

**Pipeline:** `osp-survey` → XLSForm (our exporter) → `pyxform` (BSD-2) → XForm XML → `enketo-transformer` → HTML + model → `enketo-core` in the participant's browser → submission XML → our server → stored response.

**Verified facts [V]:**
- Licence Apache-2.0. Monorepo `enketo/enketo` (`enketo-core`, `enketo-express`, `enketo-transformer`, `openrosa-xpath-evaluator`), active in Oct 2026.
- **Governance:** ODK stepped away from maintaining Enketo in May 2024. The KoboToolbox team took over in March 2025 (README). One maintainer organisation, but XForms is an open standard with other implementations.
- ODK XForms spec defines `randomize(nodeset, seed)` precisely: inside-out Fisher–Yates with a seeded Park–Miller PRNG. Our Python engine can reproduce it exactly.

**What changes:**

| Area | Before (LimeSurvey) | Now (Enketo) |
|---|---|---|
| Servers we depend on | Ours + LimeSurvey | **Ours only** |
| Condition assignment | `limesurvey-native` or `osp-redirect` | **Server-side at session start** (our server injects `cond` + `seed` into the form). Reproducible by default. `limesurvey-native` applies only to LSS exports |
| Randomised choice order | LimeSurvey's RNG | `randomize(…, seed)`, replayable by our engine |
| Question/block order randomisation | Native in LimeSurvey | Not native in XForms **[verify: Enketo spike E6]** |
| Quotas, balanced allocation | LimeSurvey quotas | Ours, server-side (post-MVP) |
| Equivalence harness | Docker LimeSurvey + Playwright | Playwright against our own pages. Faster, no Docker |
| Participant data | Held by the institution's LimeSurvey | **Held by us** → retention, deletion, encryption, consent and DPIA are back in the MVP |
| Server-side validation | LimeSurvey's | Our Python engine re-checks each submission against the survey |

**Enketo spike result (16 Oct 2026): go with limits.** Details: `spikes/spike-enketo/FINDINGS.md`. Decisions taken:
- **Source:** build Enketo from a **pinned commit** of `enketo/enketo` (npm releases stopped in March 2025; the repo has core 9.0.6).
- **Transform:** XForm → HTML runs **once per published version in headless WebKit** (Node `libxslt` fails on Node 24; Chromium injects an XSLT deprecation banner). Try a Node 22 container later as a lighter option.
- **Our additions around Enketo:** server-computed question/block order (reordered before form start), server autosave/resume, clearing irrelevant values on every page change, `jr:choice-name` for piped labels.
- **Accessibility:** Enketo emits invalid `role="page"` and tabindex > 0. Upstream a fix or patch at build time before the pilot.

**Risks [R]:**
- Single maintainer organisation (Kobo). Mitigation: pin versions; the XForms standard leaves an exit to other XForms engines.
- `enketo-transformer` may need Node on the server or at publish time **[verify: E2]**.
- Field-data-collection look. Mitigation: theme work post-MVP.
- XForms semantics (relevance, non-relevant data removal) become the truth our engine must match. Mitigation: the harness, plus aligning `semantics.md` to the XForms spec.

---

## 3. Lean architecture

### 3.1 Module boundaries (revised)

See §3.4 for the full layered package list (it replaces the earlier seven-package sketch). Each package is pure (no I/O) unless it sits in L4 or above.

Plugins and the instrument library are *interfaces inside these modules* until Phase 5. They are not separate packages.

### 3.2 API contracts (sketch)

**Engine (pure, deterministic):**
```text
start(survey, seed, context)                     → State
step(survey, state, answersForCurrentPage)       → { state, page | end, trace[] , errors[] }
allocate(designSpec, seed, counters | null)      → assignment        # counters=null ⇒ seeded random
```
`State` is a JSON-serialisable value: current flow position, answers, realised orders, assignments, seed, and engine version. Same inputs ⇒ byte-identical output. That property *is* the debugger and the test harness.

**Participant side:** served by LimeSurvey. Our only optional participant endpoint is the allocation entry point (§2.5, `osp-redirect` mode):
```text
GET /go/{publicId}  → allocate (seed, condition) → 302 to LimeSurvey URL with ?cond=…&seed=…   # only when runtime = osp-redirect, else 404
```

**Server REST (researcher side):**
```text
GET/PUT  /api/surveys/{id}/draft             osp-survey JSON (ETag for concurrency)
POST     /api/surveys/{id}/validate          → diagnostics[]
POST     /api/surveys/{id}/export?target=lss|xlsform|surveyjs|…  → file + diagnostics[]
POST     /api/surveys/{id}/deploy            → { version, checksum, limesurveyId }   # immutable version
POST     /api/surveys/{id}/versions/{v}/pull → fetch responses from LimeSurvey
GET/PUT  /api/surveys/{id}/allocation        { runtime: "limesurvey-native" | "osp-redirect", method, strata }
POST     /api/surveys/{id}/simulate          { n, seed, strategy } → coverage report
GET      /api/surveys/{id}/versions/{v}/package   → reproducibility zip
```

**Embedding:** use LimeSurvey's own survey URL (or an iframe of it). Django integration is an optional `osp-client` Python package wrapping our REST API.

---

### 3.3 Reference design: PhotoCraft

**PhotoCraft** (github.com/storytold/photocraft) is our model for software structure. It's a clean-room, MIT/Apache Rust reimplementation of Photoshop by the ArtCraft team. It is very new (repo created 2026-09-30, v0.7 alpha), so we copy its *structure and process*, not its maturity claims. **[V]** from its `AGENTS.md` and README, read 16 Oct 2026.

| PhotoCraft does | How it enforces it | Our equivalent |
|---|---|---|
| **Numbered layers L0–L6** across 24 crates. A crate may depend only on lower layers | `cargo xtask layers` fails the build. Every new crate must be registered with a layer | Numbered layers (below), enforced by an `import-linter` *layers* contract in CI. A new package must be registered |
| **Standalone format crates** (`psd`, `codecs`) at L0 with no workspace dependencies, publishable alone. The mapping to the document model lives separately in `io` (L4) | Layering check | Each external format gets **two** packages: `osp-fmt-lss` (read/write LSS as plain data, no knowledge of our model) and the mapping `osp-targets/lss` (our model ↔ LSS). The format packages are publishable alone |
| **Pure-data document model** (`doc`, L1) | No I/O deps allowed | `osp-spec` |
| **Everything is a command.** 500+ commands in one registry. UI, CLI, JSON control channel and MCP server all dispatch by id | Checklist for "add a command"; menu items go live automatically from the id | `osp-ops` registry. The builder, a CLI, the REST API and an **MCP server** all dispatch by op id, so AI agents can build surveys from day one |
| **Thin, data-driven UI.** UI state is serialisable so the control channel can read and drive it | Rule in `AGENTS.md` | Builder holds no logic. Its state is JSON. Property panels come from the property schema |
| **Reference oracle.** A simple CPU compositor is the truth; the fast GPU compositor is tested against it | Cross-tests | Our Python engine is the oracle. **LimeSurvey is tested against it** by the equivalence harness |
| **Model completeness guard.** The native format crate fails to compile if the document model gains a field it doesn't save | Compile error | A test fails if any `osp-spec` field is missing from (a) the native serialiser and (b) **every target's capability table**. Nothing is silently dropped from an export |
| **Real-file corpora**, pinned by commit + sha256, with **floors that may only go up** | `cargo xtask corpus`, parity `FLOOR` constant | Corpus of real `.lss`/`.qsf`/XLSForm files, pinned and hashed. Export/import pass-rate floors in CI, never lowered |
| **Measured parity, not claimed.** Generated parity checklist + scorecard. "Wiring is not behaviour" | `cargo xtask parity`, `scorecard` | Generated Qualtrics/LimeSurvey feature checklist: each feature is *modelled*, *exported*, or *behaviour-verified* (harness-tested). Only the last counts as done |
| **Never crash.** No panics in non-test code. `panic_hunt` fuzzes every command with adversarial params | Clippy denies, fuzz test in CI | Hypothesis fuzzes **every op** and every importer with hostile input. Must return a diagnostic, never raise an unhandled exception |
| **Clean-room rule.** Study behaviour and look only; implement from public specs | `AGENTS.md` rule | Same for Qualtrics, SurveyJS Creator and LimeSurvey (GPL) code |
| **Built for AI agents.** `AGENTS.md` first, `docs/`, a dev log, parallel-agent rules (own target dir, new commands in new modules) | Docs + process | `AGENTS.md`, `docs/architecture.md`, `docs/gaps.md`, `log/devlog.md`. New ops go in new modules to avoid merge conflicts between agents |

### 3.4 Our layers and rules

```text
L0  osp-fmt-lss, osp-fmt-xlsform, osp-fmt-qsf …   standalone format I/O, no workspace deps
    osp-expr                                       expression parser/evaluator, no deps
L1  osp-spec          survey model, JSON Schema, property schema, migrations, validator
L2  osp-engine        pure flow state machine + trace (the oracle)
    osp-ops           edit operation registry: (survey, args) → (survey', inverse)
L3  osp-targets       model ↔ format mappings + capability tables (uses L0 + L1)
    osp-qa            simulator, coverage, static checks, repro package
L4  osp-runtime       publish to XForm, serve Enketo pages, sessions, submissions (edge: network)
    osp-limesurvey    optional LimeSurvey API client (post-MVP)                  (edge: network)
    osp-store         database persistence                                       (edge: DB)
L5  osp-app           session layer: auth, drafts, versions, deploy; dispatches ops by id
L6  osp-web, osp-cli, osp-mcp                    thin shells: Svelte SPA (static files), CLI, MCP server
```

1. **A package may import only lower layers.** CI fails otherwise (`import-linter` layers contract). Nothing below L6 imports the web framework.
2. **L0–L3 do no I/O**: no network, database, clock or global randomness. Effects live in L4+.
3. **Every user-visible behaviour is an op** with id, label, params schema, `enabled(survey)` and `run`. It comes with tests and a hostile-input fuzz case.
4. **Each question type is declared once** in the property schema. Builder panels, validation, docs and capability badges are generated from it.
5. **Completeness guard:** a model field that a serialiser or capability table doesn't mention fails CI.
6. **Floors only go up** for *behaviour*: corpus pass rates and the harness-verified feature count. Not raw test counts, which would reward quantity and block cleanup.
7. **Two workspaces, one repo, one contract (decided 16 Oct 2026: core stays Python).**
   ```text
   python/   uv workspace: osp-spec, osp-engine, osp-ops, osp-targets, osp-qa,
             osp-limesurvey, osp-store, osp-app, osp-cli, osp-mcp
             → layers enforced by import-linter
   web/      pnpm workspace: builder app (SvelteKit, adapter-static),
             api-client (generated from OpenAPI), ui-components
             → layers enforced by dependency-cruiser
   contract/ openapi.json (generated from Python, committed, diffed in CI)
   ```
   The halves meet only at `contract/`. CI regenerates the OpenAPI file and the TS client and fails if either is stale. Packages are internal modules with clear public APIs. Publish them to PyPI/npm only if outside demand appears (cross-LLM review: separate published packages are too much overhead for one developer).

**Cost:** about one week of scaffolding before the first feature (workspace, layer contracts, op registry, completeness guard, `AGENTS.md`). It pays back from the second question type and second export target onwards.

---

## 4. Prioritised MVP backlog

> **Revised 16 Oct 2026 (twice):** no own renderer. Participants run in **Enketo**, served by our backend (§2.6). Data protection items (retention, deletion, encryption, consent) are back in scope because we store responses.

**MVP goal:** a pilot researcher builds one real, ethics-approved, two-condition study in our builder, deploys it to their LimeSurvey, collects data there, and gets a reproducibility package from us.

| # | Item | Acceptance criteria |
|---|---|---|
| 1 | `osp-survey` v0 schema + validator | JSON Schema published. Validator reports broken references, cycles, unreachable blocks and type errors with JSON-pointer paths. 30+ fixture surveys pass/fail as expected. |
| 2 | Engine (headless): pages, blocks, branch, display logic, end, piping, seeded shuffle/assignment | Shared conformance fixtures pass. Identical trace for identical (survey, seed, answers). Used by the debugger and simulator only; it does not serve participants. |
| 3 | XLSForm exporter + Enketo capability table | Exported XLSForm passes `pyxform`, renders in Enketo. Every non-native feature produces a diagnostic. |
| 4 | Participant runtime: publish → XForm → Enketo page served by us | Participant URL works on desktop and phone. Submissions stored, linked to survey version. Server re-validates every submission with our engine. |
| 5 | Equivalence test harness | Playwright plays scripted participants through our Enketo pages. Page sequences and stored answers match our engine's trace for every fixture. `randomize` orders match for 1,000 seeds. |
| 6 | Builder: add/reorder/edit questions and blocks, flow list editor, JSON view | Edit in GUI → JSON updates. Edit valid JSON → GUI updates. Invalid JSON shows errors and never corrupts the draft. Builder is keyboard-accessible. |
| 7 | Debugger: step through the survey headlessly | Shows each page's questions, why they appeared, and realised orders. "Open preview" renders the draft in Enketo. |
| 8 | Path simulator + coverage report | Blocks/branches never reached across N random-answer runs, plus static "definitely unreachable" findings. Labelled as *sampled* coverage. |
| 9 | Condition assignment | Server assigns condition + seed at session start, injected into the form. Sticky per session. Stored with each response. Reproducible from the stored seed. |
| 10 | Versioning | Each publish records survey version + checksum + Enketo/pyxform versions. Every response is bound to one version. |
| 11 | Responses + codebook + reproducibility package | CSV/JSON export with state columns (`semantics.md` §1). Codebook with labels and conditions. Repro zip: definition, exact XForm, diagnostics, tool versions, methods text. |
| 12 | Accounts: email/password + TOTP, per-survey owner/editor roles | Researchers cannot read others' surveys or responses (tested). |
| 12b | Data protection basics | Retention setting, response deletion, encryption at rest, no IP stored by default, consent-before-collection enforced. |
| 13 | Second exporter: LimeSurvey LSS | Proves the transpiler is not Enketo-specific. Imports cleanly into a pinned LimeSurvey (Docker in CI). |

**Explicit MVP non-goals:** own participant renderer (Enketo is the renderer), quotas, balanced allocation, within-subject/Latin-square designs, multilingual, save/resume across devices, themes beyond light/dark, QSF/LSS import, instrument library, plugins, friendly text DSL, SSO/SAML. *(Email distribution, panels, enterprise dashboards and AI analysis remain out of scope, as the brief requires.)*

**First post-pilot additions (in order):** balanced allocation + quotas (they share counter infrastructure) → save/resume → multilingual → XLSForm/SurveyJS polish → within-subject designs → QSF/LSS import for migration → QSF export.

---

## 5. Interoperability: hardest edge cases

### 5.1 QSF (Qualtrics)
- **Undocumented and versioned by Qualtrics.** **[R]** Expect structure changes. Build from a corpus of real exports, not from guesswork.
- **Question-level JavaScript** (`Qualtrics.SurveyEngine.addOnload…`). It cannot be converted. Detect it, preserve it as an opaque annotation, and warn.
- **Loop & Merge**: per-iteration variable naming and piping (`${lm://Field/1}`).
- **Randomizer elements** with "evenly present" (balanced) vs plain random. That semantic must survive.
- **Quotas** with cross-quota logic and "end survey vs. skip block" actions.
- **Carry-forward choices, display logic on individual choices, recode values vs. choice IDs.** Exports use recode values, so mapping errors silently corrupt data. **[R]**
- **Piped text** syntax variety (`${q://QID12/ChoiceGroup/SelectedChoices}`).
- **Survey flow** nesting (branches inside groups inside randomizers) and embedded-data set points.
- **Rich-text/HTML labels** with inline images hosted on Qualtrics servers.

### 5.2 LSS (LimeSurvey)
- **ExpressionScript** (`{if(Q1.NAOK > 3, …)}`) embedded in text. It needs its own parser, and `.NAOK`/`.relevanceStatus` semantics are subtle.
- **Question codes vs. internal IDs**. Subquestion codes produce SGQA-style variable names in exports.
- **Array/dual-scale question types** with no clean equivalent.
- **Per-language rows** duplicated per field in the XML. Missing translations need explicit fallback rules.
- **Group-level relevance** combined with question-level relevance.

### 5.3 Measuring conversion loss
1. **Corpus:** 30–50 real surveys per format, anonymised, from collaborators.
2. **Structural score:** fraction of questions, choices, logic nodes and randomisers mapped (per category, not one number).
3. **Behavioural equivalence (the important one):** for each survey, generate K answer scripts. Run them through the source platform's behaviour (recorded manually or from a Qualtrics test-response export) and through the converted survey in `osp-engine`. Compare page sequences and recorded variables. Report % of scripts with identical paths.
4. **Round-trip:** `A → osp → A` diff, normalised for irrelevant ordering.
5. **Diagnostics are part of the contract:** each loss is emitted as `{code, severity, sourcePath, message}`. A conversion with zero diagnostics but behavioural mismatch counts as a test failure.

---

## 6. Sharing semantics between Python and JavaScript

> **Update 16 Oct 2026:** with LimeSurvey as the runtime, our engine no longer runs on participant pages. It only powers the debugger and simulator, so it can be **Python-only, server-side**. The builder calls it through the API. The drift problem moves: it's now *our engine vs. LimeSurvey*, handled by the equivalence harness (§2.5, MVP item 5). The options below matter again only if we ever add our own renderer.


**Options ranked for a solo developer:**

| Option | How | For | Against |
|---|---|---|---|
| **A. Engine in TypeScript; server runs it in-process via an embedded JS engine** (e.g. QuickJS bindings for Python) **or a small Node/Deno sidecar** | One implementation | Single source of truth; browser gets it for free | Extra runtime on server; Python devs debug TS |
| **B. Two small interpreters + one shared conformance fixture suite** | Python engine + JS engine, same JSON test vectors | Each side idiomatic; no exotic runtime | Two codebases; drift possible but caught by fixtures |
| C. Rust core → WASM (browser) + PyO3 (server) | Formspec's approach | Strongest guarantee | Heavy toolchain for one person; slows iteration |
| D. Python engine in browser via Pyodide | One implementation | Python only | Multi-MB download on every participant page. Rule out. |

**Recommendation (superseded by the update above):** Python-only engine. If an own renderer is ever added, revisit options A/B, and keep the fixture suite as the specification either way.

Rules regardless of option:
- PRNG is specified, not "whatever `Math.random` does": e.g. a counter-based PRNG (SplitMix64 or PCG) seeded from `hash(surveyVersion, sessionSeed, nodeId)`. Then each randomiser is independent and stable even when other parts of the survey change.
- Number semantics: decimal vs. float, and integer division, written down and tested.
- Engine version is recorded in every response.

---

## 7. Testing and security strategy

### 7.1 Logic correctness
- **Conformance fixtures** (above) run in CI against every engine runtime.
- **Property-based tests** (Hypothesis / fast-check): random valid surveys + random answers ⇒ engine never crashes; never shows a non-relevant required question; always terminates (flow is a DAG, checked statically, so it terminates).
- **Static analysis:** unreachable blocks, contradictory conditions (small SMT/interval check for numeric conditions; full satisfiability is undecidable in general, so report "possibly unreachable" honestly).
- **Coverage:** branch coverage from simulation, always labelled *sampled* unless the path space was enumerated exhaustively (feasible only for small surveys; compute and say so).
- **Golden response tests:** export of a fixed simulated dataset must be byte-identical across releases unless a migration is declared.

### 7.2 Randomisation and allocation
- **Per-participant randomisation** (orders, seeded assignment): pure function of seed. Test with distribution checks (χ², 10k–100k sessions) and reproducibility (replay = identical).
- **Balanced allocation / quotas** require shared counters. Model as: `SELECT … FOR UPDATE` on a counter row per (survey version, design cell, stratum) in PostgreSQL, inside the same transaction that records the assignment. SQLite is single-writer, so it works for small installs but must be documented.
- **Define when a slot is consumed** (on assignment vs. on completion) and how abandoned sessions release slots (timeout). These are research-design decisions; expose them in the UI.
- **Concurrency test:** 200 parallel simulated participants against a quota of 50 ⇒ exactly 50 complete in the cell, never 51.
- Record in every response: allocation method actually used, seed, counters snapshot id, engine version.

### 7.3 Security
- Server re-validates every page; the client is never trusted.
- Researcher-authored HTML in labels: sanitise on save (allow-list, e.g. `nh3`) **and** serve participant pages with a strict CSP. Researchers are semi-trusted; participants must be protected from a compromised researcher account.
- Tenant isolation tests: every query path covered by an "other user cannot access" test.
- Rate limiting and bot protection on participant endpoints (configurable; no third-party CAPTCHA by default for privacy).
- Dependency scanning, SBOM, signed releases.

---

## 8. Plugin sandboxing (§11 Q7)

- **Tier 1 (MVP+):** *declarative* plugins only: JSON schema for the answer, existing primitives for rendering. No third-party code runs.
- **Tier 2:** code plugins for the **builder** (trusted, installed by the instance admin, like a WordPress plugin). Treat them as full trust and document it.
- **Tier 3:** code plugins on **participant pages** run in a **sandboxed cross-origin iframe** (`sandbox="allow-scripts"`, no `allow-same-origin`), talking to the host via a narrow `postMessage` protocol: `init(config, locale)` → `answer(value)` → `valid(bool)`. The host validates the answer against the plugin's declared JSON Schema. The plugin never sees other answers unless its manifest declares them and the researcher approves.
- Manifest: id, version (semver), `engineRange`, declared data schema, requested permissions, licence, integrity hash. Published surveys pin plugin versions by hash.

---

## 9. Answers to remaining §11 questions

**Q2: UI stack. Decided: the entire UI is Svelte, no htmx (16 Oct 2026).** *Revised again 16 Oct 2026, after cross-checking with GPT, Gemini and Qwen (all three independently recommended the same thing):* **Svelte for the builder** (canvas, property panels, logic/flow editor, debugger, JSON view). The surrounding pages (survey lists, settings, accounts, exports) are Svelte too, so there is one UI stack and no server-rendered templates. Reason: the builder is a *document editor*, not CRUD. Under htmx-for-everything, fragment swaps fight focus, caret, IME, open panels and drag state. Every structural edit and debugger step waits on the network (100+ ms on remote institutional hosts). And the "small JS islands" grow into a home-made editor framework.
- **Backend independence: the UI is a static SPA behind one API contract.** Build with SvelteKit using `adapter-static` (SPA mode). The output is plain HTML/JS/CSS that any web server or CDN can serve. **Don't use SvelteKit server features** (server `load`, form actions, hooks): they'd tie the UI to a Node backend.
- **The contract is OpenAPI**, generated from the Python op registry and pydantic models (FastAPI does this natively). The TypeScript client is generated from it. A contract-test suite (e.g. Schemathesis plus our own op fixtures) is what makes "any backend" real: a backend counts as compatible when it passes it.
- **Be honest about the limit:** the UI is backend-independent, but survey *semantics* (ops, engine, simulation, LimeSurvey deploy) still live in Python. A non-Python backend would have to reimplement them and pass the fixtures. What we gain is that the Python *web framework* is swappable (FastAPI, Litestar, Django), and Django integration is just mounting the API and serving the static UI.
- **Auth** goes through the API: same-origin session cookie + CSRF token by default, OIDC/SAML later. No auth logic in templates.
- **No duplicated business logic:** the client sends ops (op id, params, stable entity ids, base revision) to the Python server, which stays authoritative. The server returns the new revision + a JSON patch, and a generic client patch applier updates the local snapshot. Local input buffers give instant typing feedback; only trivial structural gestures (move, rename) are predicted optimistically and reconciled. Op param types are generated from the Python (pydantic) definitions into TypeScript: shared *shapes*, not semantics.
- **JSON view:** edits are held in CodeMirror and applied with an explicit **Apply** action, not live two-way sync.
- **Undo** needs transaction grouping and revision rules, not just inverses.
- Rejected for now: running the Python ops in the browser via Pyodide (5–10 MB boot, extra complexity). It's possible later, since only researchers load the builder.

**Q3: reusable permissive projects (no React/Django).**
- SurveyJS Form Library (MIT): **test tool only**, to check our SurveyJS exports run. Not a dependency of the product (decided).
- pyxform (BSD-2): XLSForm parsing and validation for the XLSForm adapter.
- Enketo (Apache-2.0): reference for XForms semantics, and possibly a renderer.
- jsPsych (MIT): reaction-time and experiment plugins. A natural future "custom question" bridge for psychology users.
- SortableJS (MIT): drag-and-drop.
- LimeSurvey: GPL. **Read for format understanding; do not copy code** unless the project itself goes GPL.

**Q8: before any pilot.** Collect no IP address and no user agent by default. DPIA template for institutions. Data processing agreement template for hosted use. Encryption at rest and in transit. Backups with tested restore. Retention + deletion. Audit log of researcher access to responses. WCAG 2.2 AA audit of the participant runtime (the builder can follow). Consent-before-collection enforced by the engine (no answers stored before consent node). Ethics: participant withdrawal/deletion path, versioned consent text stored with response.

**Q9: phases and estimates.** See §11 below.

**Q10: smallest compelling MVP.** The §4 backlog. The pitch to a researcher is: *"Free, self-hostable, testable before launch, and every participant's condition is recorded."* Full **replay** of conditions and orders is only promised in `osp-redirect` mode; in the default `limesurvey-native` mode we record outcomes but cannot reproduce them from a seed.

---

## 10. Technical spikes (do these before substantial implementation)

| # | Spike | Question it answers | Time-box |
|---|---|---|---|
| 1 | Hand-write the §2.3 example as `.lss`, import into LimeSurvey 6 (Docker), deploy via RemoteControl API, play 3 scripted participants with Playwright | Can we drive LimeSurvey end to end from code? Does the API expose what we need (import, activate, responses, version)? Where is realised question order stored? | 3–4 days |
| 1b | Transpile the §2.3 example from `osp-survey` to LSS and XLSForm; write both capability tables | Is the normalise → lower → emit pipeline the right shape? What do the diagnostics look like? | 3 days |
| 2 | Engine prototype in Python: flow, branch, shuffle, seeded assignment, trace; 20 fixtures | Is the state-machine contract right? | 4–5 days |
| 3 | *(Dropped: engine is Python-only, so no cross-runtime question.)* | — | — |
| 4 | Svelte builder slice on real Python ops: 100-question fixture, reorder, property edit, one nested condition, CodeMirror with Apply, grouped undo/redo, one debugger step, one deliberately rejected op | Under 200 ms injected latency and rapid edit→reorder→undo: focus kept, GUI/JSON/server consistent after ops settle, rejections recover without losing other edits, debugger matches current revision | 5 days |
| 5 | Convert 5 real QSF exports to `osp-survey`; list every unmapped construct | Real scale of the QSF problem; informs §2 schema | 3 days |
| 6 | Balanced allocation under 200 concurrent sessions on PostgreSQL and SQLite | Counter design correctness | 1–2 days |

Total about 3–4 weeks. Its output is a go/no-go on the renderer and engine-runtime decisions, plus a revised schema.

---

## 11. Revised delivery estimate (solo developer, AI-assisted, part- vs. full-time not specified)

> **Superseded 16 Oct 2026** for an agent-driven build (Claude Max 20x, 3–5 parallel agents; see `automation.md`). The table below is a traditional solo estimate, kept for reference.
>
> | Milestone | Estimate | Limited by |
> |---|---|---|
> | Spike 1 (LimeSurvey end to end) | 1–2 days | LimeSurvey behaviour |
> | Working end-to-end prototype | a few days after spike 1 | Your review time |
> | Feature-complete MVP (§4) | ~2–4 weeks | Verification against LimeSurvey, UX iteration |
> | Pilot running with a real study | +1–3 months calendar time | Ethics/IT approval, researcher availability |


| Stage | Contents | Full-time estimate | Main uncertainty |
|---|---|---|---|
| Spikes | §10 | 3–4 weeks | — |
| MVP | §4 backlog: builder, LSS export + deploy, equivalence harness, 2nd exporter | 3–4 months | LSS semantics; equivalence harness effort; builder UX |
| Pilot | 1–2 real studies, fixes, IT/DP review | 1–2 months (calendar time longer: ethics + IT approval) | Institutional review lead times |
| Post-pilot v1 | Quotas, balanced allocation, save/resume, multilingual, XLSForm | 3–4 months | — |
| v1.x | Within-subject designs, QSF import, repro package, instrument library | 4–6 months | QSF fidelity |
| v2 | Plugin system, hardening, scale | 4–6 months | Security review findings |

**Overall: ~4–6 months to a pilot-ready MVP; ~18–30 months to the full brief.** AI assistance speeds code production most. It speeds UX iteration, accessibility auditing, institutional approvals and format reverse-engineering much less. **[A]**

**Alternative strategies:**
1. **Own builder, LimeSurvey as default runtime, other platforms as export targets.** **Chosen (16 Oct 2026).** No renderer to build. Costs: our debugger and tests model LimeSurvey rather than being it, so an equivalence harness is required (§2.5).
2. **XLSForm-first:** researchers author in a spreadsheet, the platform adds flow/design/testing on top. Weeks to a usable tool, but it conflicts with "GUI first". Possible as a stop-gap only.
3. **Fork/extend LimeSurvey:** largest existing feature set, but PHP + GPL + its architecture constrain every decision. Not recommended given the brief's goals.

---

## 12. Existing survey builder GUIs: reuse or learn from

The brief assumes a from-scratch builder. Several mature builders exist. The deciding factor for each is **licence vs. our outbound licence**, now decided as MIT. Data from GitHub API, 16 Oct 2026 **[V]** unless marked.

### 12.1 Comparison

| Builder | Licence | Stack | Research fit | Can we ship it in an open-source product? |
|---|---|---|---|---|
| **SurveyJS Survey Creator** | **Commercial EULA** (Devsoft Baltic). Source on GitHub, not open source | TS; has a framework-free `survey-creator-js` package | ● richest drag-drop survey builder; JSON model; logic editor; translations | **No, not as part of the core.** Possible as an *optional adapter* that each institution licenses itself. Check whether academic/non-commercial use is free **[A]** |
| **SurveyJS Form Library** (runtime only) | MIT | TS, `survey-js-ui` vanilla | ● | Yes |
| **Form.io builder** (`@formio/js`) | MIT | Vanilla JS + templates (Bootstrap); no React | ◐ forms/workflow focus; no randomisation, quotas or experiments | **Yes.** Strongest permissive *builder* candidate. Its model would be a compile target, not canonical |
| **KoboToolbox Formbuilder** (`kobotoolbox/kpi`) | AGPL-3.0 | Python/Django + JS | ● XLSForm-native; used heavily in field research | Only if our licence is AGPL-compatible. Also Django-coupled. **Best UX reference for an XLSForm-aligned model** |
| **LimeSurvey** | GPL (confirm) | PHP | ● closest feature match to Qualtrics in open source | Code: only if GPL. **Main feature/UX benchmark** |
| **Formbricks** | AGPL-3.0 core + proprietary `ee/` + MIT SDKs | TS/React (Next.js) | ◐ product/UX surveys, not academic | React + AGPL. UX reference only |
| **HeyForm** | AGPL-3.0 | TS/React | ○ conversational forms | UX reference only |
| **OpnForm** | AGPL-3.0 + enterprise dir | PHP/Vue | ○ | UX reference only |
| ODK Build | Archived 2023 | JS | ◐ | No (unmaintained) |
| **surveydown** (R package, v1.3.0) | MIT | R + Quarto + Shiny + PostgreSQL; surveys written in Markdown | ● academic, reproducibility-focused; no GUI builder | Licence-compatible, but needs R + Shiny server, which the brief rules out. **Export target + idea source** (Markdown authoring) |
| **formr** | BSD-3-Clause | PHP + OpenCPU (R); spreadsheet-authored | ● longitudinal "runs", diaries, R-generated feedback | Not as a base (PHP, R). **Idea source** for multi-session studies later |
| Qualtrics, Gorilla, Typeform, Tally, Google Forms | Proprietary SaaS | — | varies | UX reference only. Do not copy assets or text |

### 12.2 What this changes

1. **Decided: the project is MIT-licensed.** Consequences:
   - **Reusable code:** SurveyJS Form Library (MIT), Form.io builder (MIT), pyxform (BSD-2), Enketo (Apache-2.0; keep its NOTICE file), jsPsych (MIT), SortableJS (MIT).
   - **Reference only, never copy code:** LimeSurvey (GPL), KoboToolbox, Formbricks, HeyForm, OpnForm (AGPL), Formspec authoring tools (BSL). The same applies to AI-assisted work: don't paste their source into prompts and then commit the output.
   - **SurveyJS Creator** may only appear as a separate, optional package that never ships the Creator itself. The institution installs and licenses it.
   - **Dependency policy:** allow MIT, BSD, ISC, Apache-2.0, CC0, Beerware/WTFPL-style permissive, and MPL-2.0 for **test-only** tools (e.g. axe-core). Dual-licensed packages are allowed when one option is permissive; record the chosen licence (e.g. `jquery-touchswipe`, `node-forge`: take the non-GPL option). Deny GPL, AGPL, LGPL, BSL, SSPL and "commons clause". Enforce in CI and fail on unknown licences.
   - Trade-off accepted: anyone can run a closed hosted fork. That's the price of easy adoption by universities and companies.
2. **Decided (16 Oct 2026): our own builder; LimeSurvey as default runtime (§2.5), no own renderer.** Rejected options, kept for the record:
   - Building on the SurveyJS runtime or Creator: vendor-controlled (Devsoft Baltic), so the project would depend on one company's roadmap and licensing.
   - Extending the Form.io builder: also company-led, and its form-centric model fights survey flow.
   - Small MIT *utilities* (SortableJS, a sanitiser, a PRNG) are still fine. The rule is: no vendor-owned survey model or UI at the core.
3. **Copy designs, not code, from the AGPL/GPL tools.** Catalogue their builder interactions now: Kobo's XLSForm-aligned question editor, LimeSurvey's question-group/logic screens, SurveyJS Creator's logic tab and translation grid. That gives us an evidence-based UX spec.

### 12.3 Extra spike

| # | Spike | Question it answers | Time-box |
|---|---|---|---|
| 7 | Build the §2.3 example in SurveyJS Creator (trial), Form.io builder, KoboToolbox and LimeSurvey. Record clicks, missing features and what can't be expressed | Which builder interactions to adopt for our own builder; UX spec input | 3 days |

---

## 13. Legal note (brief)

The SAS v WPL line (CJEU 2012; SAS also lost later in UK and US courts) supports the view that **functionality and file formats are not protected by software copyright as such**. It does not cover: copying Qualtrics documentation text or UI artwork, trade marks ("Qualtrics" in product names or marketing), patents, or **contractual terms** in an institution's Qualtrics licence that may restrict reverse engineering of exports. Have counsel check the QSF point specifically before shipping a QSF importer. **[A]** — not legal advice.

---

## Sources
- Formspec repository and licensing: https://github.com/Formspec-Labs/formspec · https://formspec.org/
- SurveyJS licensing: https://surveyjs.io/Licenses
- SAS v WPL: https://www.managingip.com/article/2a5bqo2drurt0bx8utrv2/judge-backs-own-judgment-in-software-copyright-case · https://www.cafc.uscourts.gov/opinions-orders/21-1542.OPINION.4-6-2023_2106573.pdf · https://www.eff.org/cases/sas-v-wpl
- Repository metadata (licence, activity) via GitHub API, 16 Oct 2026: XLSForm/pyxform, enketo/enketo, LimeSurvey/LimeSurvey, surveyjs/survey-library, jspsych/jsPsych
- PhotoCraft (structure reference): https://getartcraft.com/apps/photocraft · https://github.com/storytold/photocraft (`AGENTS.md`, `docs/architecture.md`)
- LimeSurvey licence and seed handling: https://github.com/LimeSurvey/LimeSurvey (`LICENSE`, `application/helpers/update/updates/Update_290.php`, `RandomizerHelper.php`)
