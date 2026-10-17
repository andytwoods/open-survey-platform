# Demo videos

Scripted, re-runnable videos of the builder and the participant app in use (task DM1).
Everything in them is invented: the "Coffee and sleep study", its questions and the answers.

| # | File (in `.build/demo/`) | Length | Shows |
|---|---|---|---|
| 1 | `01-building-a-survey.mp4` / `.gif` | 1:27 | Create a survey, add questions, choices, a grid, a display condition, undo/redo, command palette, a flow randomiser |
| 2 | `02-settings-and-publish.mp4` / `.gif` | 0:40 | Publish checks, retention, consent, a theme, publish, copy the participant link |
| 3 | `03-participant.mp4` / `.gif` | 0:37 | A participant on a laptop, a refresh mid-page, the resume link, finishing on a phone |
| 4 | `04-results.mp4` | — | Not recorded yet: the builder has no Results page (`results` entry) on main. Add `04-results.demo.ts` when it lands; `render.sh` already picks up `raw/04-results.webm` |

Each MP4 is H.264, 1920 × 1080, 30 fps, `yuv420p` with `faststart`. Each GIF is an 8 s loop,
960 px wide, under 6 MB, for a README. The videos are build output (`.build/` is
gitignored): regenerate them, don't commit them.

## Regenerate

```sh
make demo-videos                       # about 3 minutes on a quiet machine
make demo-videos OSP_DEMO_PACE=0.3     # quick dry run of the scripts (too fast to watch)
make demo-videos DEMO_ARGS=03          # one video (a Playwright file filter)
```

Needs Playwright Chromium (`pnpm -C web/builder exec playwright install chromium`) and
`ffmpeg` on the `PATH` (or `FFMPEG=/path/to/ffmpeg`). ffmpeg is a tool here, not a project
dependency. The target is not part of `make check`.

How it works:

- `web/builder/demo/playwright.config.ts` starts its own stack on two free ports: osp-api on
  a fresh, throwaway SQLite store (`web/builder/e2e/api_server.py`, which also serves the
  participant app at `/s/{slug}`) and the built builder pages behind `vite preview`. Nothing
  is reused, so two runs in a row give the same videos.
- `01-build.demo.ts`, `02-publish.demo.ts`, `03-participant.demo.ts` drive the real UI. They
  wait on real UI states ("All changes saved", dialogs open/closed, page headings); the only
  fixed waits are the deliberate pauses (`beat`, `caption`) that give a viewer time to read.
- `overlay.ts` injects the cursor, the click ripple and the captions into the page with
  `addInitScript`, in the demo browser only. Nothing of it is in an app bundle.
- Chromium runs with `--force-device-scale-factor=1.5`, so the 1280 × 720 desktop viewport
  records sharp 1920 × 1080 frames (the phone clip: 390 × 844 at 1.5×).
- `render.sh` turns the raw WebM files (`.build/demo/raw/`) into MP4 and GIF, joins the two
  parts of video 3 (the phone clip centred on a 1920 × 1080 canvas), and fails if a GIF is
  over 6 MB or the total is 6 minutes or more. GIFs: video 1 from 0:20 (toolbox and
  choices), video 2 from 0:04 (retention and consent), video 3 from the start of the phone
  part.
- Each run writes the caption times to `.build/demo/raw/*.captions.json`; the chapter
  tables below come from them (they move by a second or so between runs and machines).

Set-up done through the API rather than on camera: video 1 adds a second block
("Evening routine") through the API just before the flow view, because the builder has no
"add block" control yet; videos 2 and 3 start from the demo survey created through the API
(`seed.ts`); video 3's survey is published through the API.

## 1. Building a survey

| Time | Chapter (on-screen caption) |
|---|---|
| 0:00 | Building a survey in the Open Survey Platform builder |
| 0:01 | Create a survey |
| 0:05 | Outline on the left, the questions in the middle, properties on the right |
| 0:07 | Write the welcome note |
| 0:13 | Add a question with the type picker |
| 0:20 | …or click a type in the toolbox under the outline |
| 0:25 | Edit the answer choices |
| 0:35 | A grid: one row per thing to rate |
| 0:49 | The grid’s columns: paste a list |
| 0:56 | A follow-up question, shown only to heavy coffee drinkers |
| 1:10 | Every edit can be undone and redone |
| 1:14 | The command palette (Ctrl/⌘+K) reaches every command |
| 1:16 | Flow: add a randomiser so blocks come in random order |
| 1:21 | Move the first block into it (Alt+↓ on the handle, or drag) |
| 1:23 | Everything saves as you go |

## 2. Appearance, settings, consent, publish

| Time | Chapter (on-screen caption) |
|---|---|
| 0:00 | Settings, consent, a theme, then publish |
| 0:02 | Publish checks the survey first |
| 0:03 | Data retention must be chosen before publishing |
| 0:06 | Settings: how long to keep the answers |
| 0:08 | A consent page before the first question |
| 0:17 | The preview shows what participants will see |
| 0:19 | Appearance: pick a theme |
| 0:26 | Saved to the lab library and used for this survey |
| 0:28 | Publish |
| 0:30 | Published: the participant link, exports and a reproducibility package |
| 0:33 | Link copied |
| 0:34 | Open the link: consent first, in the chosen theme |
| 0:36 | Then the first page, in the Warm theme |

## 3. A participant, on a laptop and then a phone

| Time | Chapter (on-screen caption) |
|---|---|
| 0:00 | A participant opens the link on a laptop |
| 0:02 | Answer page 1 |
| 0:06 | Page 2: a slider and a grid |
| 0:12 | Refresh the page mid-way… |
| 0:13 | …and nothing is lost |
| 0:15 | Continue on another device: a private resume link |
| 0:20 | On a phone, the resume link opens the same answers |
| 0:23 | 4 cups: the follow-up question shows, with the answer piped in |
| 0:28 | A date |
| 0:33 | Submitted: one response, nothing lost or duplicated |

Video 3 is two recordings joined: the laptop part (1280 × 720) and the phone part
(390 × 844, mobile and touch emulation), which continues the same session through the resume
link.
