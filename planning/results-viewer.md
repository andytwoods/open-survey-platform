# Results viewer: charts per question, exportable figures (plan V)

Status: **decided** 17 Oct 2026. The owner asked for a results viewer like SurveyJS's (a chart per
question, chart type chosen per question) plus export of the charts, and asked the lead to
ideate with other LLMs and decide. GPT, Gemini and Qwen were consulted with the same brief
(review log at the end). Clean-room: SurveyJS Dashboard is commercial; we take the *idea* of
a per-question results page only. No code, assets or chart implementations are copied.

Scope note: `overview.md` §5 rules out "enterprise dashboards and analytics". A per-question
results page for the researcher's own survey is in scope (it is the simple operational view
that section allows); cross-survey BI, panels and AI analysis stay out.

## What the researcher gets

1. A **Results** page (its own builder page entry `results`, mounted by the host like the
   others, lazy-loaded so the chart library never slows the editor).
2. One **card per question**, in survey order: question text, variable name, chart, summary
   statistics, and the four response-state counts (answered / unanswered / irrelevant /
   not reached). Notes are hidden by default.
3. A **chart menu per card** offering only charts that suit the question type (table below).
   The choice is remembered in the saved layout.
4. Every card has a **Table view** with the exact numbers behind the chart (also the
   accessible alternative for screen-reader users).
5. A **filter bar**: survey version (default: latest published), completion status
   (default: complete only), submission date range, assigned condition, and answers to
   single/multiple-choice questions. Active filters are always shown above the cards and
   go into every export caption.
6. **Split by** one categorical question or the assigned condition per card (grouped bars,
   100 % stacked bars, or small multiples). Numeric bins as split groups come later.
7. **Denominator** shown on every chart. Default: answered. Toggle: shown (answered +
   unanswered). Never mixes in irrelevant or not reached.
8. **Saved layouts** per survey, shared in the lab: chart choices, filters, splits, order,
   hidden cards, bin widths, captions. Named; one is the default.
9. **Export** per card and for the whole page (below).
10. Works at 320 px (cards stack, controls collapse into a sheet), keyboard only, light/dark;
    charts never rely on colour or hover alone.

## Chart menu per question type

| Question type | Default | Alternatives | Statistics |
|---|---|---|---|
| Single choice | Horizontal bars, declared option order | Sorted bars, donut, table | counts, % of answered, n, mode; median only for ordered scales |
| Multiple choice | Horizontal bars, % of respondents who answered | Counts, dot plot; co-selection heatmap later | per option count and %, answering n, mean options chosen; label "% of respondents (can sum > 100 %)" |
| Whole number, decimal | Histogram (shared bin edges, edges shown) | Box plot (no individual points), cumulative distribution | n, mean, SD, median, quartiles, min, max |
| Slider | Frequency bars when ≤ 21 steps, else histogram | Box plot, cumulative | as numbers |
| Date | Counts per month (bin size labelled) | Per day / week / year | n, earliest, latest |
| Grid (matrix), ordered columns | Diverging stacked bars, one per row, neutral centred | 100 % stacked bars, heatmap rows × columns, table | per row n, counts, %, median category, top-2 / bottom-2 box |
| Grid (matrix), unordered columns | Grouped bars per row | Heatmap, table | per row n, counts, % |
| Text | Response-state counts + paginated verbatim table (owner/editor only, audited) | Word frequency later (stop words, PII redaction) | answered n, mean length |
| Note | Hidden | Shown as a heading | none |

No matrix-wide mean or scale score in the MVP: that needs a scoring scheme (reverse-coded
items, missing-item rules). "Ordered" is a question setting (Likert); default true when the
columns are numeric codes in ascending order.

Optional 95 % intervals: Wilson for proportions, t for means (off by default; caption says so).

## Decisions

- **V-D1 Library: Vega-Lite (vega-embed), BSD-3.** All three reviewers chose it. A chart is a
  declarative JSON spec, so the exported spec re-renders in Python (Altair) or R (vegawidget):
  the strongest reproducibility story. SVG and PNG export are built in. Wrapped in one Svelte
  component (`$effect` on spec, dispose the old view). Whole dependency tree goes through
  `make licence-check`. Bundle cost accepted because the results page is its own lazy entry.
- **V-D2 Aggregation on the server.** A new endpoint returns aggregate tables only; the browser
  never downloads response rows for charts. Answers are encrypted at rest, so the server
  streams and decrypts in one pass per request and computes every requested card together.
  No plaintext analytics copy, no DuckDB. Aggregates are cached in memory per (survey,
  versions, response watermark, normalised query), invalidated by new responses.
  Targets: 10 k responses, first view < 2 s; 100 k < 15 s with a progress state.
- **V-D3 Access.** MVP: the `survey.export` permission (owner, editor), like the data export.
  Viewers get nothing yet; an aggregate-only viewer role needs its own disclosure design
  (repeated overlapping queries can rebuild a cell) and is phase 3. Every query and every
  export is audited (`results.read`, `results.export`: actor, query, versions; no values).
- **V-D4 Small cells.** In the app, owners/editors see exact counts (they can download the raw
  data anyway, so hiding them protects nothing). Exports get **"Hide counts below k"**
  (k = 5 default, editable), off by default, and the export dialog warns when any shown cell
  is below 5. Hidden cells look different from zero and their percentages are hidden too.
  The viewer role (phase 3) will always have suppression on.
- **V-D5 Semantics** (centralised in one Python module, mirrored by tests with hand-computed
  expectations):
  - Units are **responses**, never "participants".
  - Response states stay separate; denominator as in item 7 of "What the researcher gets".
  - Multiple choice: % = respondents who chose the option / respondents who answered; an
    unticked option inside an answered question is "no", an unanswered question is missing.
  - Choice codes are categories, never measurements; declared order is kept.
  - Versions: default one version. Combining versions is allowed only when the question and
    its option ids/codes match; otherwise the card shows per-version facets and says why.
    Matching is by ids, never by label text. "Not in this version" is its own state and
    is outside the denominator.
  - Languages: aggregate by ids, label in the chosen language (defaults to the survey's
    main language); free text is never translated.
  - Matrix: each row is its own variable with its own n.
  - Balanced assignment and quotas: no automatic weighting; split by condition instead.
  - Splits: shared bin edges and category order across groups; a missing split value is its
    own group unless excluded; each group shows its n.
  - Undefined statistics (SD with n < 2) show as "not available", not 0.
- **V-D6 Export formats.** MVP per card: **SVG**, **PNG** (width presets 85 mm single column /
  180 mm double / custom; 150, 300 or 600 DPI; real pixel size, DPI metadata), **CSV** of the
  aggregate table (counts, denominators, bin edges, hidden-cell markers), **Vega-Lite spec**
  with embedded aggregates plus a manifest (survey id, version(s), filters, split,
  denominator, platform + Vega versions). Whole page: **ZIP** of all of those.
  Phase 2: PDF (per figure and as a report, client-side SVG → PDF with permissive libraries,
  licence-checked) and a self-contained HTML report.
- **V-D7 Publication look.** Export theme separate from the app theme: white background,
  Okabe-Ito qualitative palette, ordered/diverging palettes for Likert, direct labels where
  they fit, ≥ 8 pt text at final size, a preview at final size before download. Fonts: a
  generic sans stack in MVP (no bundled font; OFL fonts are not on the licence allowlist
  yet; adding OFL-1.1 for font files only is a question for the owner, not blocking).
- **V-D8 Captions.** Auto-generated, editable: question text, variable, version(s), filters,
  split, denominator, n (and "k hidden" when suppression is on). Included under PNG/SVG and
  in the manifest.
- **V-D9 Saved layouts** stored server-side per survey (new table, migration 0009), lab-shared,
  edited by owner/editor; a layout never stores data, only settings.
- **V-D10 Contract first.** V1's first commit publishes the request/response schema in
  `contract/openapi.json` so V2–V4 can build against it (with a mock server) in parallel.

## API sketch (V1 owns the final shape)

`POST /api/surveys/{id}/results/query` (survey.export)
```json
{
  "versions": [3], "status": "complete", "submittedFrom": null, "submittedTo": null,
  "filters": [{"question": "gender", "in": [1, 2]}], "condition": null,
  "split": {"question": "arm"}, "denominator": "answered",
  "cards": [{"question": "q1"}, {"question": "age", "bins": {"width": 5}}],
  "language": "en"
}
```
Response: per card `{question, type, states: {answered, unanswered, irrelevant, notReached,
notInVersion}, groups: [{key, label, n, cells: [{key, label, count, pct}], stats: {...}}],
binEdges?, warnings: [...], versionsUsed}` plus `queryHash`, `watermark`, `generatedAt`.
`GET /api/surveys/{id}/results/text/{question}?cursor=` for the verbatim table (paginated,
audited). Layout CRUD under `/api/surveys/{id}/results/layouts`.

## Tasks (on the HubAI board; rows in `tasks.md`)

| id | what | depends on |
|---|---|---|
| V1 | Aggregation API: semantics module, endpoint, text endpoint, audit, cache, benchmark 10 k / 100 k | — |
| V2 | Results page: new builder page entry, filter bar, split, denominator toggle, cards with table view, chart menu wiring, 320 px, a11y | V1 contract |
| V3 | Charts: Vega-Lite component, spec builders per question type and chart, app and export themes, Likert diverging, a11y | V1 contract |
| V4 | Export: SVG / PNG presets / CSV / spec + manifest / page ZIP, captions, suppression option, preview | V3 |
| V5 | Saved layouts: migration 0009, CRUD API, page integration | V1, V2 |
| V6 | Phase 2: PDF (figure + report) and HTML report | V4 |
| V7 | Phase 2: combine compatible versions, numeric split bins, word frequency for text | V1–V3 |

## Review log (17 Oct 2026)
- GPT: Vega-Lite; server aggregation, no viewer access in MVP, enforce suppression, text
  separate; strict denominators; phases 8–12 / 4–6 / 6–10 engineer-weeks.
- Gemini: Vega-Lite (Altair/R reproducibility); server aggregation (suggested DuckDB: not
  taken, would mean a plaintext analytical copy); Okabe-Ito; Wilson intervals; virtualised
  cards; word frequency for text.
- Qwen: Vega-Lite; server aggregation; suppress < 5; word cloud with PII scrubbing (not
  taken for MVP); version mixing off by default.
- Where they differed: viewer access (Gemini: aggregates for viewers now; taken as phase 3
  with forced suppression), suppression for owners (GPT: always; decided off in app, option
  on export, see V-D4), text charts (decided: no word cloud in MVP).
