# Spike 1 findings: LimeSurvey (stopped early, 16 Oct 2026)

Stopped when Enketo was chosen as the runtime (`planning/review.md` §2.6). LimeSurvey is now an **export target** only. Answers come from one full run. The last two `.lss` edits (assignment latch, JS order capture) were never run.

**Recommendation: go-with-limits** as an export target.
**Pinned:** `martialblog/limesurvey:6.17.18-260831-apache` + `mariadb:11.4.13`, both native arm64. RemoteControl is enabled by writing one settings row.

| # | Answer |
|---|---|
| Q1 Deploy via API | Yes. Import, activate, participants and tokens all work. Survey ID is kept, but group and question IDs are renumbered, so map by question code |
| Q2 Response export | Yes. JSON keys by our question codes. Codes that clash with built-in columns (e.g. `seed`) get renamed in JSON and duplicated in CSV, so the transpiler must reserve those names |
| Q3 Version via API | Yes: `get_site_settings('versionnumber')` returns `6.17.18` |
| Q4 Realised order stored? | Partly. Per-response `seed` is exported; realised question order is not (PHP session only) |
| Q5 URL prefill | Works and survives back/reload, but **not sticky**: re-entering with the same token and a different `cond` overwrote it mid-survey |
| Q6 Irrelevant answers | Cleared to NULL, even before final submit |
| Q7 Order stability | Stable across reload, resume in a new browser, back/forward. An unguarded `rand()` equation re-rolls, so native assignment must be latched |
| Q8 Logic matches plan | Yes: required, range, integer, relevance, consent-no end, re-entry blocking. Piping is HTML-escaped. `{q}` inserts the code, `{q.shown}` the label |
| Q9 Harness time | 53 s from fresh containers to export |

## Implications for the LSS exporter (later)
- Reserve LimeSurvey built-in column names.
- Use `{q.shown}` for piping labels.
- Latch any random assignment. Never trust URL-prefilled conditions without signing and stickiness.

## Needs human (deferred until LSS export work)
1. Target LimeSurvey 6.x (security fixes only) or 7.x (7.5.1 current)?
2. Is recording question order with in-survey JavaScript acceptable? Some university instances strip scripts.
3. LimeSurvey exports can't distinguish "irrelevant" from "not reached". OK to compute that with our engine for the codebook?

## Rerun
`make -C spikes/spike-1 run` · LimeSurvey alone: `docker compose -f spikes/spike-1/docker-compose.yml up -d` → http://localhost:8082
Evidence: `evidence/run/` (traces, raw exports, screenshots, `timings.json`).
