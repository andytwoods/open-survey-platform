# Enketo spike: findings

**Date:** 2026-10-16 · **Plan:** `planning/spike-enketo.md` · **Rerun:** `make -C spikes/spike-enketo run` (clean checkout: about 48 s including `npm ci` and `uv sync`; the checks alone take about 37 s)

**Recommendation: GO WITH LIMITS.** Every go criterion passes: E1, E3, E4, E5 and E9 (with documented lowerings), E2 has a workable answer, and E11 has no copyleft-only dependency. The limits are:

1. Question and block order aren't native (E6). We lower them, and the lowering works.
2. Three behaviours differ from `semantics.md` (text trimming, choice-label piping, when non-relevant values are cleared). Two can be lowered. One needs a human decision.
3. The transform step depends on the browser's XSLT engine, and Chromium is phasing that out.

## Pinned versions

| What | Version | Source |
|---|---|---|
| enketo-core | 9.0.1 (exact) | npm, published 2025-02-25 |
| enketo-transformer | 4.2.0 (exact) | npm |
| openrosa-xpath-evaluator | 3.2.0 | transitive dependency of enketo-core 9.0.1 |
| pyxform | 4.5.0 | PyPI |
| Browsers (Playwright) | Chromium 156.0.8078.4, WebKit 27.2, Firefox 157.0 | |

All npm versions are pinned exactly in `web/package.json` and `web/package-lock.json`.

**Surprise: npm lags the monorepo.** The `enketo/enketo` monorepo is active (last commit 2026-10-12, release tag `7.6.4` = `f0f974cd`, 2026-08-13). It contains enketo-core **9.0.6**, transformer **4.4.0** and xpath **3.2.3**, but none of these have been published to npm since March 2025. If we want current fixes we'll need to build from a pinned monorepo commit. For this spike, npm was enough.

## E1–E11

| # | Answer | Evidence |
|---|---|---|
| E1 | **Yes.** `enketo-core` renders on a plain page served by a 200-line stdlib Python server. No Enketo Express, Kobo or Central. Bundle (esbuild, minified): **930 KB / 264 KB gzip** for the full widget set; **572 KB / 169 KB gzip** with survey widgets only (`src/widgets-slim.js`, tested by P4s). CSS is 141 KB / 23 KB gzip. The biggest parts are node-forge (281 KB, needed by XPath `digest()`), leaflet with leaflet-draw (213 KB, geo widgets, dropped from the slim build) and jQuery (87 KB). | `web/dist/sizes.json`, `web/dist/app.meta.json`, P1–P9 |
| E2 | **Publish time, in a headless browser, cached per survey version.** The Node build of transformer 4.2.0 needs the native peer dependency `libxslt@0.10.2` (engines `node <23`), and that fails to compile on Node 24. Attempt 1 recorded. The transformer's **browser build** works and takes 15–19 ms. Chromium 156 **injects an `<h:xslt-warning-banner>` element into XSLT output**, which corrupts the model (2 occurrences). WebKit and Firefox are clean. WebKit's form HTML is byte-identical to Chromium's, and Firefox's differs only in `readonly="readonly"`. We now publish via headless **WebKit**. The Python server needs no Node at runtime. | `evidence/e2/`, `evidence/e2_publish.json`, `spike_enketo/publish.py` |
| E3 | **Yes.** `form.validate()` then `form.getDataStr()` (and `getDataStr({irrelevant:false})`) gives the instance XML. We `POST` it to `/s/<sid>/submit`, and the server writes the files. | `evidence/run/submissions/*.xml` |
| E4 | **Yes.** The server writes `cond`, `seed`, `order_att` and `order_blocks` as default values into the primary instance of `modelStr` (minidom) before render. P4 checks `cond=B` and `seed=123` in the model, stimulus B shown, and both values in the submission. | P4, `server.py:inject` |
| E5 | **Yes for integer seeds: 900/1,000 seeds exact at every length (3,600/3,600 orders, n = 3, 5, 10, 26).** The spec-only first attempt got 800/1,000: it matched for every non-negative seed and failed on negative seeds, because the spec doesn't define the modulo sign. Using JS/Java truncating remainder fixed all 400 negative-seed orders. The other 100 seeds (decimal and string) **throw in Enketo** (`Invalid seed argument. Integer required`), even though the spec says to truncate decimals and to sha256-hash non-numeric seeds. Our Python follows the spec there, so Enketo is the one out of line. The spec also omits the Park–Miller constants and the draw-to-index mapping. We assumed 16807 / 2^31−1 / `(s−1)/(2^31−2)` / `floor(u·(i+1))` with one draw per element including i=0, and every assumption held. The in-form choice order matched Python in P2, P4 and P6. | `evidence/e5_randomize.json`, `spike_enketo/xforms_random.py` |
| E6 | **Not native. Lowered, and it works.** XForms `randomize` only covers itemsets. Our server computes question and block orders with the Python randomize on per-node substreams (`semantics.md` §7) and stores them in hidden fields. `app.js` reorders the DOM slots *before* `Form.init()`. Enketo's pages and logic bind by name, so nothing breaks. Checked: the att question order, the block page order, the order recorded in the submission, and the same order after refresh (P2, P4, P6). | P2, P4, P6, `web/src/app.js:applyOrders` |
| E7 | **Yes for paging. Resume is ours.** `field-list` groups with XLSForm `style=pages` give one page at a time with Back/Next, page validation, and auto-skip of irrelevant pages. enketo-core has **no persistence**. We autosave `getDataStr()` and the current page to the server on every change and flip, and on reload pass `instanceStr` and call `pages.flipToPageContaining`. P6 shows the same page, values, order and condition after refresh, both mid-survey and on the colour page. | P6 |
| E8 | **Partly. The timing differs from our semantics.** On final `validate()`, Enketo clears non-relevant values (raw `<followup/>` empty), and `getDataStr({irrelevant:false})` removes the nodes entirely (P3, P5). But **before final submit, the value stays in the model**. If relevance comes back (go back and set att1 to 5 again), the old answer reappears. This happens by default and also with `excludeNonRelevant`, which only blanks the value while it's hidden (P5, P5b). Lowering: call `form.clearNonRelevant()` on every page flip. That matches §3 exactly (P5c passes). | P5, P5b, P5c |
| E9 | **Relevance, required, constraints: match. Piping and text: differ.** Relevance (P1, P3), required while relevant, and the 18–120 constraint all behave as `semantics.md` says. **Piping `${att1}` inserts the code (`5`), not the label** (ODK behaviour). A `jr:choice-name()` calculate gives "Strongly agree". **Text:** whitespace-only input becomes empty (the string type converts `^\s+$` to `''`), so it fails `required`. Leading and trailing spaces survive in raw `getDataStr()`, but are **trimmed** in `getDataStr({irrelevant:false})`, because it rebuilds the model and `FormModel.trimValues()` runs. Resume kept the spaces (P6). | P2, P3, P6 |
| E10 | **Keyboard: yes. Labels: yes. Two Enketo ARIA defects.** P9 completes the whole survey with Tab, arrow keys, Space and Enter. axe-core 4.14 on 7 page states found no label or name violations. It flagged: `aria-roles` (critical, WCAG 4.1.2), because enketo-core sets `role="page"`, which isn't a valid role; `tabindex` > 0 (serious), because Enketo sets tabindex 1 and 2 on pages and the Next button; and `page-has-heading-one` (moderate), which is our template's fault. All three can be fixed after init, or by an upstream patch. | `evidence/e10_axe.json`, P9 |
| E11 | **No copyleft-only package.** There are 105 production packages: 83 MIT, 8 BSD-2, 6 ISC, 4 Apache-2.0, 1 BSD-3. Dual-licensed (we choose the permissive option): `jquery-touchswipe` MIT/GPL-2 and `node-forge` BSD-3/GPL-2. Permissive but off our allowlist: `language-subtag-registry` CC0-1.0 and `leaflet.gridlayer.googlemutant` **Beerware** (geo only, not in the slim build). Dev-only (not shipped): `axe-core` MPL-2.0, and `spdx-*` CC-BY-3.0 (license-checker's own dependencies). Python: pyxform BSD-2, playwright Apache-2.0, the rest MIT/PSF/BSD. Also, `leaflet-draw` is fetched from a **GitHub git URL**, not npm. | `evidence/e11_licences.json`, `evidence/e11_license_summary_production.txt` |

### Scripted participants (last run)

| Script | Result | What failed (all are findings, not harness bugs) |
|---|---|---|
| P1 consent no | 5/5 | |
| P2 straight through, att1=5 | 22/25 | Label piping gives the code; whitespace-only answer blocked by required; pruned output trims |
| P3 att1=2 | 4/4 | |
| P4 server injects cond=B, seed=123 | 8/8 | |
| P4s P4 on the slim bundle | 9/9 | |
| P5 back, change att1, default config | 9/10 | Old value returns when relevance comes back |
| P5b P5 with `excludeNonRelevant` | 9/10 | Same |
| P5c P5 with `clearNonRelevant()` on page flip | 10/10 | |
| P6 refresh and resume | 11/11 | |
| P7 re-enter after finishing | 3/3 | |
| P8 / E5 1,000 seeds | 900/1,000 | The 100 decimal and string seeds throw in Enketo |
| P9 keyboard only | 12/12 | |

Per-check detail is in `evidence/run/P*.json`, and the overview is in `evidence/summary.json`.

## Enketo capability table (draft)

| Feature (`osp-survey`) | Enketo | How |
|---|---|---|
| integer, decimal, text, single, multi, date | native | XLSForm types |
| One page per block, Back/Next | native | `field-list` group + `style=pages` |
| Display logic (relevance) | native | `relevant` |
| Required while relevant | native | `required` |
| Constraints on answered values | native | `constraint` |
| Skip blocks with no relevant questions | native | pages auto-skip |
| Clear an irrelevant value on page submit (§3) | **lowered** | `form.clearNonRelevant()` on `pageflip` |
| States: irrelevant vs unanswered vs not-reached (§1) | **lowered** | pruned XML (node absent = irrelevant) + raw XML (values) + our engine on the server |
| Text exactly as typed (§2) | **approximated** | Leading and trailing spaces kept in raw `getDataStr()` only. Whitespace-only answers become empty: **unsupported** |
| Piping a value | native | `${q}` → `<output>` |
| Piping a choice label (§8) | **lowered** | hidden `calculate` with `jr:choice-name(${q}, '${q}')` |
| HTML-escaping piped text | not tested | |
| Choice-order randomisation (replayable) | native | `randomize(..., ${seed})`. Integer seeds only |
| Question order within a page | **lowered** | server order → hidden field → DOM reorder before init |
| Block (page) order | **lowered** | same |
| Condition assignment | **lowered** | server assigns and injects into the instance |
| Fixed at first reach; refresh and resume | **lowered** | server session + draft autosave + `instanceStr` |
| No re-entry after completion | ours | server returns "already completed" and a 409 on resubmit |
| End node / early termination | approximated | later pages irrelevant → submit shown (P1) |
| Turning Back navigation off | not tested | likely lowered (hide `.previous-page`) |
| Quotas, balanced allocation | ours (not tested) | server side |
| Submission capture | native + ours | `getDataStr()` → POST |
| WCAG basics | approximated | patch `role="page"` and `tabindex` after init |

## Proposed embed architecture (1 page)

```text
 PUBLISH (once per survey version)                       RUNTIME
 osp-survey ──our exporter──▶ XLSForm                    participant ──GET /start──▶ osp-runtime (Python)
   └─ pyxform ──▶ XForm XML                                │  assign cond, sessionSeed; compute every
       └─ enketo-transformer (browser build,               │  realised order with osp-engine randomize
          headless WebKit via Playwright,                  │  (substream per node); persist session
          or a Node-22 build container) ──▶                ▼
          {form.html, model.xml, transformerVersion,     GET /s/<sid>: published form.html
           xform sha256}  ──stored with the version──▶     + model.xml with cond/seed/orders injected
                                                           + draft instance (resume) + our app.js bundle
                                                         browser: enketo-core Form; app.js applies the
                                                           orders, clears non-relevant on page flip,
                                                           autosaves {xml, page} → POST /s/<sid>/draft
                                                         Submit: validate() → POST raw + pruned XML
                                                           → osp-store: files/DB, bound to version +
                                                             checksum; osp-engine re-checks the answers
                                                             and derives the §1 states
```

- **Where the transform runs:** at publish time, never per request. The output is cached with the survey version and its checksum, alongside `transformerVersion` and the browser it ran in. The Python server needs no Node at runtime. Node is only needed for the JS bundle build (esbuild + sass), which happens once per release. Today the transform runs in headless WebKit via Playwright, a tool we already depend on for the harness. The fallback is a pinned Node 22 container with `libxslt` (see "Needs human").
- **How a session starts:** the server assigns everything random: condition, `sessionSeed`, and question and block orders computed by our own randomize. It stores all of it in the session and injects it into the instance as hidden fields. The browser only *applies* orders and never generates randomness, apart from choice shuffles, which Enketo's `randomize(..., seed)` produces identically to our Python. So every order is recorded *and* reproducible (§7).
- **How responses are stored:** on submit the page POSTs two forms of the instance. The raw one, after `validate()`, keeps exact text. The pruned one has non-relevant nodes removed. The server stores both against the session, survey version and checksum. `osp-engine` replays the survey against the answers, which validates them server-side and labels each question `answered` / `unanswered` / `irrelevant` / `not-reached`. Drafts are kept server-side, keyed by session, and deleted on completion. All of this is participant data, so the retention, encryption and DPIA work in `review.md` §2.6 applies.
- **Our JS is thin glue:** about 100 lines in `web/src/app.js` (order application, autosave and resume, submit, clearing non-relevant values on page flip). It contains no survey logic.

## Needs human

1. **Text whitespace (§2, decided "no trimming").** Enketo turns whitespace-only input into empty (so it fails `required`) and trims in pruned output. We can keep leading and trailing spaces by storing raw values, but **"whitespace-only = answered" can't be done in Enketo** without patching enketo-core. Options: amend §2 to the ODK behaviour (whitespace-only = unanswered; edge spaces kept), or carry an enketo-core patch.
2. **Piping labels (§8).** ODK pipes codes. Should our XLSForm exporter always generate a `jr:choice-name` calculate per piped choice question (works, P2)? Or should §8 change?
3. **Licence allowlist (AGENTS rule 5).** Do we accept dual-licensed MIT/GPL-2 and BSD/GPL-2 packages (choosing the permissive side), CC0-1.0, and Beerware (geo only, droppable via the slim widget set)? Also an MPL-2.0 dev-only tool (axe-core). CI needs an explicit policy for these.
4. **Transform host.** Should publish-time transform run in headless WebKit (works today), in a pinned Node 22 container with native `libxslt` (Node 22 is the last line inside the transformer's `engines`), or should we wait for or contribute a non-XSLT transformer? Chromium is phasing out XSLT (banner observed in 156) [A: Chrome's public removal timeline not checked in this spike].
5. **npm vs monorepo.** Stay on npm `enketo-core@9.0.1` (Feb 2025), or build pinned monorepo packages (9.0.6) ourselves?
6. **Seeds.** Enketo only accepts integer seeds. We should make "sessionSeed and substream seeds are positive 31-bit integers" a rule in §7. Our generator already does this.

## Attempts recorded (3-strikes rule)

- Node transformer: (1) `npm install libxslt@0.10.2` on Node 24 failed with libxmljs compile errors. We didn't install Node 22 globally, because that's outside the spike directory. Switched to the browser build: works.
- Transformer ESM entry: `import 'enketo-transformer'` fails (`dist/enketo-transformer/enketo-transformer.js` is missing from the 4.2.0 package). The CJS entry needs libxslt (above).
- E5: (1) the harness used `ORDERED_NODE_SNAPSHOT_TYPE`, which re-sorts results into document order, so every order looked like identity. Fixed by using an unordered snapshot. (2) Spec-only Python: 800/1,000 seeds. (3) Truncating remainder: 900/1,000. The remaining 100 are Enketo errors, not ours.
- The sass build needed an importer, because enketo-core's published SCSS imports monorepo-absolute paths (`/packages/enketo-core/node_modules/...`).

## Layout

`survey/spike_enketo.md` (XLSForm as markdown) · `spike_enketo/` (publish, server, xforms_random, e5, participants, runner) · `web/` (package.json, build.mjs, src/: app.js, config.js, widgets-slim.js, entries) · `evidence/` · `Makefile`. Generated (rebuilt by `make run`): `build/`, `web/dist/`, `data/`, `evidence/run/`.
