# Media in surveys: images, audio and video (task MM1)

**Status:** plan, 17 Oct 2026, posted for the lead's review before coding · **Branch:** `agent/36`
**Depends on:** the spec model (`osp_spec.model`), the plan compiler (`osp_runtime.plan`), the browser engine (`web/engine`), the participant widgets (`web/ui-components/src/survey`), the property panel (B4) and the host page config (`docs/hosting.md`).
**Clean-room:** the idea (a stimulus on a question, image choices, a host-provided media library) is common to every builder. Nothing here is taken from any of them; the model is ours and the library contract is a thin JSON list.

## 1. What a researcher wants

1. Show a **stimulus** (picture, sound clip, video) above a question or as a note of its own.
2. **Image choices** ("which of these faces…") and image column headers in a matrix.
3. Add media **by URL** today; pick from the **university's media library** where the host has one.
4. Trust that participants on a phone, with a screen reader, or on a slow connection, can still take part.
5. Research controls: **must play to the end before Next**, and know *whether and how* the participant played the clip (counts, time to first play) in the data.
6. Exports that say honestly what the other platform can do with the media.

## 2. Data model (`osp_spec.media`, L1, pure)

A new sub-model `Media` (own module, like `theme.py`), strict and `extra="forbid"` like every spec model:

```yaml
kind: image | audio | video
url: "https://cdn.example.ac.uk/faces/01.jpg"      # Url, or {lang: Url} (a German clip for `de`)
alt: { en: "A smiling face", de: "Ein lächelndes Gesicht" }   # Text; required for images
caption: { en: "Figure 1" }                        # Text; shown under the media
transcriptUrl: "https://…/clip-01.html"            # Url or {lang: Url}; required for audio
captionsUrl: { en: "https://…/clip-01.en.vtt" }    # Url or {lang: Url}; required for video (WebVTT)
posterUrl: "https://…/clip-01.jpg"                 # video only, optional
width: 1280                                         # px hints, 1..8192; both or neither
height: 720
durationSeconds: 42.5                               # hint, 0 < d ≤ 86400
mimeType: "video/mp4"                               # hint, `type/subtype`
mustPlayToEnd: true                                 # audio/video on a question or note only
autoplay: false                                     # video only; always muted; off under reduced motion
```

| Field | Type | Rule |
|---|---|---|
| `kind` | literal | one of the three |
| `url` | `Url \| {LanguageTag: Url}` | `Url` is a string ≤ 2048 chars: `https://…` without userinfo, or a same-origin absolute path `/…` (not `//`). Pipes `${…}` are an error (`media.url_pipe`): a URL built from an answer would leak it. `http://localhost` / `http://127.0.0.1` is a warning (`media.url_insecure`) so local development works |
| `alt` | `Text` | **required and non-empty for `image`** (`media.alt_missing`; no decorative images: a stimulus is never decorative). Ignored for audio/video (`media.alt_kind` warning) |
| `caption` | `Text` | optional, any kind |
| `transcriptUrl` | `Url \| {lang: Url}` | **required for `audio`** (`media.transcript_missing`); recommended for `video` (warning `media.transcript_recommended`) |
| `captionsUrl` | `Url \| {lang: Url}` | **required for `video`** (`media.captions_missing`); error on image/audio |
| `posterUrl` | `Url` | video only |
| `width`, `height` | int | both or neither (`media.size_pair`); gives the aspect ratio so the page never shifts while loading |
| `durationSeconds`, `mimeType` | hints | validated for shape only |
| `mustPlayToEnd` | bool | audio/video only, and only on a question or note (`media.must_play_kind`, `media.must_play_choice`) |
| `autoplay` | bool | video only (`media.autoplay_kind`) |

Per-language URLs reuse the `Text` shape (`str | {lang: str}`), so the language rules already in `validate._text` apply (unknown language, missing translation falls back to the default language in the plan).

### 2.1 Where media attaches

| Place | Field | Cardinality | Kinds |
|---|---|---|---|
| Any question or note (`_QuestionBase`) | `media: list[Media]` | ≤ 3 (`media.too_many`) | image, audio, video |
| A choice (`Choice`), inline or in a shared `ChoiceList` | `media: Media \| None` | 1 | image, audio (`media.choice_kind` forbids video) |
| Matrix columns | = the matrix's `choices`, so `Choice.media` | 1 per column | image, audio |

Not in this cut (open questions, §10): matrix rows, pages, blocks, consent text, end messages, the survey title.

Rendering position: a question's media sits **between its label and its help**, in list order (the stimulus belongs to the question text; help describes how to answer). A note's media is its content, after the note text.

### 2.2 Model and guard impact

- `Media` is a new `$defs` entry, so every one of its properties needs a capability row in **both** target tables (the completeness guard, AGENTS.md rule 6; exact-count assertion in `test_lss_capabilities.py` updated).
- The property-panel YAML of every question type gets `media` (new panel kind `media`, §6); `Choice.media` is edited by the choices editor (no panel entry needed for `Choice`, which is not a panel type).
- Ops that rebuild objects from known fields must carry media, or the guard's inverse round trip fails: `add_choice` gains an optional `media` param (so `delete_choice`'s inverse restores it), `question_type_ops.IDENTITY_KEYS` gains `media`, duplicate ops deep-copy already. A new module `osp_ops/media_ops.py` holds `set_choice_media(owner, value, media | unset)` (inverse: the old media or `unset`). Question media is set as a whole list through the existing `set_property(target, "media", [...])`, which validates against the model, so no new op is needed there.
- `osp_ops.doc.text_sites` / `TEXT_KEYS_*` gain the media `alt` and `caption` texts, so language stripping and translation tools see them.
- `validate._question_sites` and `_choice_items` run `_text` on `alt`/`caption` (pipes allowed there, as in labels) and the `media.*` checks above. `tests/test_codes.py` gets one row per new code; valid/invalid case files; the Hypothesis mutator covers the new subtree for free.

### 2.3 Allowed origins (per deployment) and CSP

A media URL may point anywhere `https`, but a deployment decides which origins its participant pages may load from:

- **`OSP_MEDIA_ORIGINS`** (osp-api `Settings.media_origins`, comma-separated exact `https://` origins, default empty). Same-origin paths (`/media/…`) are always allowed.
- **Validation knows the list.** `osp_spec.validate(data, *, media_origins: Iterable[str] | None = None)`: when a list is given, a media URL on another origin is the **error** `media.origin_not_allowed` (message names the allowed origins). The app passes its settings' list to every validation (draft diagnostics, publish, MCP, CLI), so the builder shows the problem live and publishing is blocked, and the preview frame (whose CSP would block the file anyway) agrees with the participant page. The spec stays pure: the list is a parameter. Fixtures and tests use same-origin paths.
- **Participant page CSP.** `web/runtime/vite.config.ts` gains `media-src 'self' blob:` (today media falls under `default-src 'self'`, which also blocks `blob:`). The baked `<meta>` policy cannot be loosened by a header, so `osp_api.static_files` rewrites the `img-src` and `media-src` directives of `index.html` **at serve time** from `OSP_MEDIA_ORIGINS` (one `re.sub` per directive, cached per process; tested). A host that serves `dist/index.html` itself edits the same two directives, as it already edits `data-api-base`; `GET /api/meta/media-policy` returns `{allowedOrigins, csp: {imgSrc, mediaSrc}}` so the host can copy the exact strings (and so the builder's media editor can show the allowed origins in its help).
- **Preview frame CSP.** `PREVIEW_FRAME_CSP` gains `media-src 'self' blob:`; `docs/hosting.md` §5 item 6 tells the host to append `OSP_MEDIA_ORIGINS` to `img-src` and `media-src` of `csp["preview-frame"]` (the dev host does this from the same variable). `manifest.json` is otherwise unchanged.
- `connect-src` stays `'self'`: media elements, posters and WebVTT `<track>` files are fetched by the browser under `img-src` / `media-src` (CSP 3 fetch directives), not by the page's script. An e2e test loads a same-origin track and checks the policy's `media-src`.

## 3. Participant rendering (`web/ui-components/src/survey/Media.svelte`)

One component renders a `Media` view (`MediaView`: kind, resolved url/caption/alt/track/transcript for the session language, hints, flags) inside `<figure>`:

| Kind | Markup | Rules |
|---|---|---|
| image | `<img src alt width height decoding="async" loading="lazy">` (eager on the current page) | `max-inline-size: 100%; block-size: auto; aspect-ratio: w / h` so nothing shifts; `alt` always set; `figcaption` from `caption` |
| audio | `<audio controls preload="metadata" src>` + **Transcript** link (`rel="noopener"`, opens in a new tab, announced as such) | never autoplays |
| video | `<video controls playsinline preload="metadata" poster [muted autoplay]>` with `<track kind="captions" src srclang label default>` for the session language (every language's track is listed) + Transcript link when given | `autoplay` only when `autoplay: true` **and** `prefers-reduced-motion` is not `reduce`, and then muted; a muted autoplaying video shows its controls so it can be paused |

- **Accessible name**: the figure is labelled by the caption (or the alt / "Audio" / "Video" + index); native controls stay native (keyboard, screen reader, pointer ≥ 44 px). Controls are the browser's; we do not draw our own player.
- **Must play to the end**: the element gets `data-must-play`; forward seeking is clamped to the furthest position played (`seeking` → `currentTime = maxPlayed`), and the Next button shows the engine's `media` error when the clip has not ended (§4). Backward seeking and replay are allowed.
- **Load failure** (`error` on the element, or `img` `onerror`): the figure shows the alt text (image) or "This clip could not be loaded" + **Retry** (re-sets `src`); a transcript link stays. A clip that failed cannot block the participant: the runtime records `failed: true` in the media paradata and the engine waives `mustPlayToEnd` for it (decision MM-D5). Network status is otherwise the existing offline handling: media are plain resources the browser caches; nothing is stored in IndexedDB.
- **Choice media**: `SingleChoice` / `MultiChoice` render `choice.media` inside the option label (image: `<img alt>` before the text, in `cards` style as a tile with the image on top; audio: a small `<audio controls>` after the label, which does not toggle the radio). `Matrix` shows a column image above the column text in the table layout and beside it in the cards layout. The `Choice` widget type gains `media?: MediaView`.
- **320 px**: images scale to the column; video keeps its aspect ratio; audio controls wrap. **Dark mode**: nothing to do (media are the researcher's). **Reduced motion**: no autoplay; no transitions added.
- **Preloading** (`web/runtime/src/lib/preload.ts`): after a page renders, in an idle callback, the runtime preloads the media of the *next page in document order* (same block, else the first page of the next block in the flow list), images with `new Image()` and clips with a detached `preload="auto"` element, one page ahead, and not at all when `navigator.connection.saveData` is on or the effective type is 2g/slow-2g. Branches may make the guess wrong; it is a hint, never a requirement.

## 4. Engine: plan, validation, paradata

**Plan** (`osp_runtime.plan`, `contract/runtime-plan.schema.json`, `web/engine/src/plan.ts`, kept in step): items gain `media?: PlanMedia[]`, choices gain `media?: PlanMedia`, where `PlanMedia = {kind, url: {lang: string}, alt?: Text, caption?: Text, transcriptUrl?: {lang}, captionsUrl?: {lang}, posterUrl?, width?, height?, durationSeconds?, mimeType?, mustPlayToEnd?, autoplay?}`; URL maps are filled for every language like text (fallback to the default language). Plans without media are byte-identical, so existing checksums and fixtures are unchanged. Matrix rows inherit nothing (rows have no media).

**View**: `ViewItem.media: ViewMedia[]` and `ViewChoice.media?: ViewMedia` with the session language resolved and `alt`/`caption` piped like labels (`RenderedText`).

**Paradata as one summarised event per clip.** The runtime keeps per-element counters while the page is shown and, when the participant presses Next (and on `back`), commits one `media` event per element that was touched or is `mustPlayToEnd`:

```ts
{ type: 'media', item, index, choice?, plays, pauses, seeks, firstPlayMs, playedMs, maxPositionS, ended, failed }
```

`firstPlayMs` is milliseconds from the page's `shownAt` to the first `play` (null if never played); `playedMs` sums playing time; `maxPositionS` is the furthest media time reached; `ended` is true once `ended` fired. `applyEvent` stores the latest summary in `Data.media[item][index]` (merged over revisits: counts add, flags stay true). One event per clip per page visit, so the log stays small and an in-flight hook result is not made stale by every click (the event is committed right before `next`, which bumps the revision anyway). Images record nothing.

**Validation**: `validate()` adds, after `invalid`/`required`/`range`/`constraint`, the check `media`: for every `mustPlayToEnd` clip of a visible item, `Data.media[item][index]` must have `ended || failed`, else `errors[item] = { kind: 'media', index }`. The runtime shows the message `ui.mediaMustPlay` ("Play the clip to the end before you continue", `en`/`de`) under the item and in the error summary. Replay is deterministic because the `media` events precede the `next` in the log; `replay()` compares `next` results as before.

**Record**: `ResponseRecord.media?: Record<Id, MediaSummary[]>` (present when any clip was recorded). The JSON response export writes it as `media` per response; the CSV export is unchanged (no new columns by default; a `_media_*` column set is a follow-up if wanted). The reproducibility package already carries `events`; its README names the `media` event. The codebook documents each variable's media (kind, URL, alt, mustPlayToEnd) and a top-level `mediaParadata` note describing the summary shape.

**Fixtures**: `41-media` (a note with an image, a `single` with image choices, an audio question with `mustPlayToEnd`): the script gains an optional per-action `media` list (`{item, index, ended, plays, …}`, applied before `do`, FORMAT.md §2 extensions table), and expected steps use `errors: { id: { "kind": "media" } }`. The engine runner applies it as `media` events; the harness player drives the real `<audio>` (seek to the end via `page.evaluate`, which fires `ended`). The test clip is a 0.3 s silent WAV generated by a committed script (no ffmpeg here) and served by the harness/e2e servers under `/media/`.

## 5. Builder

- **Property panel**: new kind `media` (python `KINDS`, TS `PropertyKind`/`EDITOR_KINDS`/`EXTERNAL_KINDS`, `editorButtonLabel`, `externalSummary` = "2 items: image, video"). Every question YAML lists `media` in group **Basics** after `help`. `PropertiesPane` registers the `media` opener → `MediaDialog`.
- **`lib/media/`**: `MediaEditor.svelte` (the list: add / remove / move, one form per item: kind, URL (or per-language URLs when the survey has several languages), alt, caption, transcript / captions URLs, poster, size, duration, must-play, autoplay), `MediaPicker.svelte` (the library tab, §7), `model.ts` (pure: form ⇄ `Media`, local problems mirroring the spec rules so the researcher sees "alt is required" before saving, `set_property` op builder), `library.svelte.ts` (fetching + paging state; errors become messages, never throws). Saving sends one `set_property` with the whole list (one undo step). The dialog is a `Dialog` (focus trap, Escape, focus return), axe-clean, fits 320 px.
- **Choices**: `ChoiceListEditor` rows get a media button (image/audio) opening the same form for one item, committing `set_choice_media`; the row shows a thumbnail or a kind badge. Matrix columns come for free (same editor).
- **Canvas cards**: question cards show a small media strip (thumbnail for images, a kind badge with the caption for clips) under the label; choice rows show the thumbnail. Read-only, no logic.
- **Diagnostics**: `media.*` codes map to the panel's `media` property (pointer `/…/media/i/…`) and to choice rows, as other codes do.
- **Allowed origins in the UI**: the editor loads `GET /api/meta/media-policy` once and shows "Allowed: this site, https://cdn.example.ac.uk" under the URL field; a URL outside it is flagged locally and by the server diagnostic.
- **Preview** renders the real widgets, so media show as participants see them (frame CSP, §2.3).

## 6. Host media library contract

The builder uses a library when the page config has **`links.mediaLibrary`** (a new optional link; no `{id}`; same-origin or in `allowedOrigins`, as every link). The endpoint is the host's own, behind the host's sign-in, exactly like the host's API proxy routes: the browser sends the host's session cookie (`credentials: 'same-origin'`, or `'include'` for an allowed cross-origin host), `Accept: application/json`, and no CSRF header (GET only). Nothing is signed: the host *is* the backend here, and `X-OSP-*` signing exists only for what the host forwards to osp-api. A host that keeps media in another service proxies this route to it the way it proxies the API (decision MM-D1).

```text
GET <links.mediaLibrary>?query=<text>&kind=image|audio|video&cursor=<opaque>
```

Response `200 application/json`:

```jsonc
{
  "version": 1,
  "items": [
    { "id": "faces/01",            // string ≤ 200, unique in the page
      "kind": "image",             // image | audio | video
      "url": "https://cdn.example.ac.uk/faces/01.jpg",   // what participants load: public, stable, on an allowed origin
      "thumbUrl": "https://…/01-thumb.jpg",               // optional, images/videos; shown in the picker
      "title": "Face 01, neutral",                        // optional, shown in the picker
      "alt": "A neutral face",                            // optional, pre-fills alt
      "caption": "…", "width": 1280, "height": 720, "durationSeconds": 12.5,
      "mimeType": "image/jpeg", "captionsUrl": "…", "transcriptUrl": "…", "sizeBytes": 183021 }
  ],
  "nextCursor": "eyJvZmZzZXQiOjUwfQ"   // or null on the last page
}
```

Rules: ≤ 100 items per page; strings ≤ 2048 chars; unknown keys ignored; a malformed page is reported as "The media library returned something unexpected" and the URL tab still works. The builder validates every item (`parseLibraryPage`) and greys out items whose `url` is not on an allowed origin. `401` → the page's `onUnauthenticated` handling; `403`/`404`/`5xx`/network → the library tab shows the message and a Retry. Query terms are passed through; the host decides matching and scoping (the user's labs). Selecting an item fills the media form (kind, url, alt, size, captions, transcript, duration) and the researcher completes what is missing (alt for images is still required).

Hosting duties documented in `docs/hosting.md` (new §"Media library (optional)" and `OSP_MEDIA_ORIGINS` in §1 and §5): media files are loaded by **participants without a session**, so `url`s must be public and cacheable; URLs end up in published versions, so they must stay stable while a survey runs (rename nothing, delete nothing live); the Django example gains `LINKS["mediaLibrary"]` and an `osp_media_library` view returning the shape above from the lab's model. The dev host serves a fixed list at `/dev-media` so the picker can be developed and tested without a host.

## 7. Exports

| Target | Question/note media | Choice / column media | alt, caption | transcript, captions, poster | size, duration, mime | mustPlayToEnd, autoplay |
|---|---|---|---|---|---|---|
| **XLSForm** | `approximated`: the first item's URL in `media::image::<lang>` / `media::audio::<lang>` / `media::video::<lang>` on the question row (XLSForm media columns expect form attachments; the deployer downloads the files and attaches them under those names). Further items: `loss` (`media.second`) | `approximated`: `media::image` / `media::audio` on the choices row, same caveat | caption `lowered` (appended to the hint); alt `unsupported` (no alt in XLSForm) | `unsupported` | `unsupported` | `unsupported` |
| **LimeSurvey** | `approximated`: an `<img src alt>` / `<audio controls src>` / `<video controls src>` tag appended to the question text HTML (LimeSurvey's XSS filter may strip media tags unless the admin allows them) | `approximated`: the tag appended to the answer / subquestion text | caption `lowered` (a `<p>` after the tag); alt `native` inside the `<img>` | `<track>` inside the video tag `approximated`; transcript `lowered` (a link after the tag); poster `approximated` | `unsupported` | `unsupported` |
| **Codebook** | listed per variable (kind, URL, alt, caption, mustPlayToEnd) and per choice | | | | | |
| **CSV / JSON** | unchanged / `media` summary per response | | | | | |

Every `Media.*` field has a row in both tables with the level above, so the diagnostics explain exactly what a deployer loses. Golden fixture `01-all-types` gets one image note and one image choice so the codebook and export goldens prove the fields.

## 8. Tests

- **spec**: valid/invalid case files (every `media.*` code in `test_codes.TABLE`), schema regenerated, property-schema YAML checks, round trip; Hypothesis mutator unchanged (covers the new subtree).
- **ops**: `set_choice_media` guard examples + fuzz; `add_choice` with media; `IDENTITY_KEYS` round trip through a type change; `text_sites` on alt/caption.
- **runtime (py)**: plan compile with media (per-language URL fallback), schema validation, `static_files` CSP rewrite, `media-policy` route + contract.
- **targets**: capability counts, export diagnostics per level, XLSForm columns, LSS tags, codebook golden.
- **engine**: `media` event apply/merge, `mustPlayToEnd` validation (ended, failed, not touched), replay, fixture `41-media`, schema test.
- **ui-components (DOM)**: `Media.svelte` per kind (alt present, track for the language, transcript link, no autoplay with sound, reduced-motion disables autoplay, error → fallback + retry, seek clamp), choice media, matrix column media.
- **runtime e2e**: a survey with image note + image choices + must-play audio (served from `/media/`): Next blocked with the message and the error summary, play to the end, Next passes, the stored record has the `media` summary; axe at desktop, Pixel 7 and iPhone SE; CSP meta includes `media-src`.
- **builder**: vitest (`media/model.ts`, `parseLibraryPage`), DOM (editor + picker, axe), e2e (`media.spec.ts`: add an image by URL from the panel, alt required, library picker against a routed fake host endpoint incl. paging and an error, choice image, 320 px + axe; `host.spec.ts` gains `mediaLibrary` in the config). A new dev page `/dev/media` holds the gallery (no changes to the existing widget gallery, so no snapshots are redrawn).
- **docs**: `docs/media.md` (guide), `question-types.md` cross-link, `hosting.md` (origins, CSP, library), `docs-check`.

## 9. Decisions proposed (for the lead; the build proceeds on these unless told otherwise)

- **MM-D1** The media library is the host's own session-protected endpoint next to its API proxy, not a route through osp-api (osp-api never sees host media). The "signed proxy" applies to osp-api calls only.
- **MM-D2** Allowed origins are a deployment setting (`OSP_MEDIA_ORIGINS`), enforced as a validation **error** in the builder and at publish, and as CSP on the participant page and preview frame. Same-origin paths are always allowed.
- **MM-D3** Accessibility fields are hard requirements: image `alt` (non-empty), audio `transcriptUrl`, video `captionsUrl`. A video without a transcript is a warning.
- **MM-D4** Paradata is one summarised `media` event per clip per page visit, committed at Next/Back (counts, first-play latency, played time, furthest position, ended, failed), not one event per click. It lives in the event log and as `media` in the response record / JSON export; CSV unchanged.
- **MM-D5** A clip that fails to load does not block a `mustPlayToEnd` page; the record says `failed: true` so the researcher can exclude the case. Forward seeking is clamped while `mustPlayToEnd`.
- **MM-D6** Choice and matrix-column media are image or audio; question/note media may be any kind, at most 3 per item. Matrix rows, pages, blocks, consent and endings get none in this cut.
- **MM-D7** Autoplay exists for video only, muted, and never under `prefers-reduced-motion: reduce`. Audio never autoplays.
- **MM-D8** Preloading looks one page ahead in document order and is skipped under Save-Data / 2G.
- **MM-D9** XLSForm media are `approximated` (URL in the media columns, attach by hand); LimeSurvey media are `approximated` HTML tags in the question/answer text.
- **MM-D10** `url`, `captionsUrl` and `transcriptUrl` may be per language (`{lang: url}`), reusing the text-translation rules.

## 10. Open questions (not blocking)

- Media on matrix rows, pages (a full-bleed stimulus page, runtime-design §6a) and the consent text: same mechanism, left out to keep the first cut reviewable.
- An upload path of our own (store + `/api/assets`, as `Theme.logoAssetId` anticipates) versus host libraries only. This plan is host-library-only; an osp-api asset store would be its own task (storage, quotas, retention, signed participant URLs).
- Per-question timing columns in the CSV (`_media_<name>_plays` …) for researchers who do not read the JSON.
- Whether `mustPlayToEnd` should also forbid pausing, or require a minimum watched fraction rather than `ended`.

## 11. Order of work

spec (model + validation + schema + YAML + codes) → ops (`media_ops`, `add_choice.media`, identity keys, text sites) → targets (capability rows, XLSForm/LSS, codebook, goldens) → runtime-py (plan, schema, `OSP_MEDIA_ORIGINS`, CSP rewrite, `media-policy` route, contract) → engine (plan types, `media` event, validation, record, fixture 41) → ui-components (`Media.svelte`, choice/matrix media) → runtime app (view map, counters, preload, messages, e2e) → builder (kind `media`, editor, picker, library link, dev host, cards, e2e) → docs → devlog.
