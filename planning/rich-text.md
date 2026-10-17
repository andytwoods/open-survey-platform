# Rich text in every builder text field (plan RT)

Status: **proposed** 17 Oct 2026 (task RT1, plan only; nothing built). The owner wants a GUI
for text (bold, italic, links, lists…) instead of typing raw text into question text, help,
notes, choice labels, consent, endings and closed messages. This document fixes the editor
library and its licence, the rich-text model in the spec, piping chips, translations, paste
cleaning, rendering in the participant app and exports, and accessibility, then proposes
build tasks for the lead.

Related: `builder-design.md` (property kinds; `richtext` already exists as an editor hint),
`runtime-design.md` §text and CSP, `end-of-survey.md` (endings and closed messages will use
this model: EN1, EN3), `semantics.md` §8 piping, `tasks.md` rows RT1, MM1 (media embeds come
later as a block of this model).

## 1. What we have today (the constraints)

| Fact | Where | Why it matters here |
|---|---|---|
| Every participant-facing string is one type: `Text = StrictStr \| dict[LanguageTag, StrictStr]`. No length limit, no character rules. `LanguageTag` is `^[A-Za-z]{2,3}(-…)*$`. | `osp_spec/model.py:39-40` | A third variant must be impossible to confuse with a language map |
| `Text` fields: `metadata.title/description`, `Consent.text/agreeLabel/declineLabel`, `Choice.label`, question `label/help` (a note's content is its `label`), `constraintMessage`, `MatrixRow.label`, slider `minLabel/maxLabel`, `Page.title`, `EndNode.message`. `Block.title` is builder-only (`StrictStr`). Endings, closed and not-open messages do not exist yet (EN1, EN3). | `model.py:61-424` | The field list the editor must cover, and which ones are one-line by nature |
| Piping is `${id}` inline text, one regex everywhere (`\$\{([^}]*)\}`), validated only in `osp_spec/validate.py` (`pipe.invalid`, `ref.*`, `consent.pipe`). Pipes to matrix rows are `m_r`; built-ins `$trial`, `$position.*`, `$pagesDone`, `$language`, `$device`. | `validate.py:78-83, 394-425, 827-880`; `semantics.md` §8 | Chips must carry exactly these references; reference rules stay in Python |
| The plan compiler splits text into segments `string \| {pipe}` per language with fallback; the TS engine fills pipes at view time (`pipeText`), escapes values, and `toHtml` passes researcher text through "as is (sanitised at save)". **No sanitiser exists anywhere** (no DOMPurify, nh3, bleach). | `osp_runtime/plan.py:223-266`; `engine.ts:1206-1250`; `contract/runtime-plan.schema.json:293-313` | The "sanitised at save" promise is unimplemented; this plan replaces it with a model that needs no sanitiser |
| The participant UI renders text as **text nodes only**: `RichText.svelte` supports `{text, strong?, em?, lang?}` segments, never `{@html}` (zero uses in `web/`). The runtime's `segs()` drops `strong/em`, so formatting never reaches a participant today. End message, consent and titles are flattened with `plain()`. | `ui-components/src/survey/RichText.svelte`; `runtime/src/lib/view-map.ts:13-19`; `App.svelte:342`; `ConsentPage.svelte` | The renderer exists in miniature; it needs blocks, links and marks, and the flattening paths need it too |
| Fixture traces record `labels` as rendered HTML with piped values escaped; produced by `toHtml` in TS (fixture runner, debugger, harness). | `fixtures/FORMAT.md:139`; `engine/test/fixture-runner.ts:120` | A new model must keep plain-text traces byte-identical |
| The builder edits text in eight places, all `<input>`/`<textarea>`: `PropertyField` (`richtext` → `<textarea rows=3>`, `text` → `<input>`, 600 ms debounce, blur/Enter commit, Escape revert, caret kept across server echoes), `ChoiceListEditor`, `RowsEditor`, `ConsentEditor`, flow `NodeCard` end message, `FlowView` add-node, `SurveyList` title, raw JSON. No `${id}` picker; one static hint. Cards show `${id}` as token spans (`PipedText`). | `properties/PropertyField.svelte:136-148, 226`; `properties/logic.ts:36`; `choices/ChoiceListEditor.svelte:357`; `rows/RowsEditor.svelte:279`; `settings/ConsentEditor.svelte:105`; `flow/NodeCard.svelte:238`; `cards/logic.ts:62-78` | The buffering contract (debounce, echo-safe, Escape) is what the new editor must honour |
| The property schema already has `kind: richtext` for `label`, `help` and `metadata.description`; `text` for titles, slider labels, `constraintMessage`. Validation treats both as text. | `osp_spec/property_schema.py:68-78, 358-360`; `properties/*.yaml` | The builder can pick the editor per kind without new schema plumbing |
| Translations: the builder edits the **default language only** (the pane's `language` prop exists but is always the default); consent has its own language select, "Not translated yet" warning and plain preview. `text.missing_translation` is a validator warning. | `shell/PropertiesPane.svelte:55,181`; `ConsentEditor.svelte:91-97` | Per-language editing is new UI, not new model |
| Ops: `set_property` (any text field, whole value or `{lang: text}` map), `set_choice`, `add_choice`, `bulk_paste_choices`, `add/rename_matrix_row`, `set_consent` (whole object), `add_question`. `doc.py` `text_sites()` (pipes, `set_languages` cascade) misses page title, slider labels and consent. Every op needs `EXAMPLES` in `test_guard.py`. | `osp_ops/*_ops.py`; `doc.py:185-210` | Rich values flow through the same ops; the walker gaps are a bug to close on the way |
| Export targets are **XLSForm and LSS only** (`TargetId`); no importers exist (IM1 is planned). XLSForm writes text raw and warns `$text.markup` on `[*_#<>]`; LSS `html.escape`s and turns `\n` into `<br />`; pipes become `${name}` / `{code}`. Capability tables must cover every schema field (`test_every_schema_field_has_a_row`). | `xlsform/export.py:48-50, 387-410`; `lss/export.py:108-110, 545-581`; `capabilities/*.py` | Enketo/Collect labels are a Markdown subset; LimeSurvey labels are HTML: both are natural targets for a tree |
| Enketo's label transform supports `_ __ * **`, `[text](url)`, `#`…`#####`, `<span>`, `<sup>/<sub>`, single-level `-`/`1.` lists, `\n` → `<br>`, `\n\n` → paragraphs, backslash escapes; unsupported HTML is encoded. XLSForm docs say the same (plus Collect 1.4.9+). | enketo-transformer `markdown.ts` (read 17 Oct 2026); xlsform.org "Styling prompts" | Defines the XLSForm mapping and what is lost |
| Builder pages run under `script-src 'self'` and `style-src 'self' 'unsafe-inline'`; no eval. | `docs/hosting.md:348-349`; `dev-host/pages.ts:242-244` | ProseMirror needs no eval and only CSSOM/inline styles: fits |
| Licence policy: MIT/BSD/ISC/Apache etc.; MPL-2.0 dev-only; GPL family denied; `SEE LICENSE IN` is treated as unknown and fails. JS deps are read from `pnpm licenses list`. | `licence-policy.toml`; `scripts/licence_check.py:108-127` | TinyMCE and CKEditor fail twice over (GPL and `SEE LICENSE IN`) |
| ui-components has `Input`, `IconButton` (label + `aria-keyshortcuts` + tooltip), `Dialog` (focus trap), `Select`, `Tooltip`, `announce()`; no TextArea, Toolbar, Popover, Menu. bits-ui (MIT) is a dependency of both ui-components and the builder and ships Toolbar, Popover, Combobox, DropdownMenu. | `ui-components/src/index.ts`; `web/*/package.json` | The toolbar and pickers are assembled from what is already licensed |

## 2. Editor library

Requirements: permissive licence for the whole tree; headless (our toolbar, our theme tokens,
our a11y); a **schema-constrained document** so the editor cannot produce what the spec
cannot store; custom inline atom nodes (pipe chips); paste parsing through the schema;
JSON in and out; Svelte 5 without a wrapper package; no eval; maintained.

| | Tiptap 3 (ProseMirror) | ProseMirror direct | Lexical | Quill 2 | Milkdown | TinyMCE 8 / CKEditor 5 / Jodit |
|---|---|---|---|---|---|---|
| Licence (npm, 17 Oct 2026) | MIT (`@tiptap/*` 3.32.0; deps `prosemirror-*`, `orderedmap`, `w3c-keyname`, `rope-sequence`, `linkifyjs`, `@floating-ui/dom`: all MIT) | MIT | MIT (0.52.0) | BSD-3-Clause (2.0.3) | MIT (7.22) | `SEE LICENSE IN` + GPL-2.0-or-later (TinyMCE 7+, CKEditor 5): denied. Jodit MIT but HTML-centric, monolithic |
| Schema-constrained doc | yes (ProseMirror schema; unknown nodes/marks cannot exist) | yes | partly (node registry; HTML import needs its own filter) | Delta model, formats whitelist; block structure weaker | yes (Markdown-first, heavier) | no (HTML strings, sanitised after the fact) |
| Custom atom node for chips | `Node.create({atom: true})`; `@tiptap/suggestion` for a `${` trigger; Mention extension as a pattern | yes, more code | DecoratorNode | Embed blot, awkward with inline text | yes | plugins, HTML |
| Svelte 5 | `new Editor({element})` in `onMount`, `onTransaction` to drive `$state`; documented Svelte guide | same | vanilla core works; most tooling is React | vanilla | Svelte adapter exists | vanilla |
| Paste | ProseMirror `clipboardParser` through the schema + `transformPastedHTML` hook | same | `$generateNodesFromDOM` + filtering | own matchers | ProseMirror | own cleaners |
| Weight (editor chunk, lazy) | core + 12 extensions, roughly 45–60 kB gzipped (measure in RT3) | smaller by Tiptap's layer | similar | similar | larger | larger |
| Risk | Tiptap sells Pro extensions and a cloud; the open-source core is MIT and we use nothing else | more boilerplate to own (keymaps, input rules, list commands) | a11y/IME edge cases were a known weak point outside React; thinner Svelte ecosystem | less control over document shape; lists/headings as formats, not nodes | Markdown round-trip we do not want | licence |

**Decision proposed: Tiptap 3 open-source core on ProseMirror, as a builder-only
dependency** (`@tiptap/core`, `@tiptap/pm`, the node/mark extensions we allow,
`@tiptap/suggestion`, `@tiptap/extension-placeholder`, `@tiptap/extension-character-count`).
Not the StarterKit meta-package (it drags in blockquote, code, strike, horizontal rule,
drop/gap cursors we do not want), not `svelte-tiptap`, no Tiptap Pro or cloud, no bubble
menu. The whole tree goes through `make licence-check`. A `dependency-cruiser` rule keeps
`@tiptap/*` and `prosemirror-*` inside `web/builder/src/lib/richtext/`, so the participant
runtime and ui-components never carry the editor. The editor chunk is loaded with a dynamic
import on the first focus of a text field (the builder already lazy-loads Vega and
CodeMirror).

Clean-room note: we learn Tiptap's API from its docs (MIT code we depend on, not copy);
nothing is taken from CKEditor, TinyMCE, SurveyJS Creator, LimeSurvey or Qualtrics.

## 3. The rich-text model in the spec

### 3.1 Shape

A third `Text` variant, a small closed tree. A plain string stays a plain string; a
per-language map may mix plain and rich values.

```json
{
  "type": "rich",
  "blocks": [
    {"type": "p", "content": [
      {"text": "Thinking about "}, {"text": "last week", "marks": ["b"]},
      {"text": ", how often did "}, {"pipe": "name"}, {"text": " exercise?"}
    ]},
    {"type": "h", "level": 1, "content": [{"text": "Before you start"}]},
    {"type": "ul", "items": [
      [{"text": "Read the "}, {"text": "information sheet", "href": "https://example.org/info"}],
      [{"text": "Keep your "}, {"text": "participant code", "marks": ["i"]}, {"text": " handy"}]
    ]},
    {"type": "ol", "items": [[{"text": "First"}], [{"text": "Second"}]]}
  ]
}
```

- **Blocks:** `p` (paragraph), `h` (heading, `level` 1–3, relative to the page), `ul`/`ol`
  (single-level lists of inline runs). Nothing else: no blockquote, code, table, image,
  horizontal rule, alignment. Media embeds arrive as a new block kind from MM1.
- **Inline runs:** `{text, marks?, href?, lang?}` with `marks ⊆ {b, i, u}`; `href` is an
  absolute `https:` URL (≤ 2 000 characters) and makes the run a link (adjacent runs with the
  same `href` are one link); `lang` is a `LanguageTag` (the existing per-segment language
  span). `{pipe: id}` is a pipe node, same identifiers and built-ins as `${id}` today.
  `{br: true}` is a line break.
- **Why not Markdown or HTML strings:** a string would need two parsers (Python and TS) that
  agree on CommonMark edge cases, and existing plain text containing `*`, `_` or `#` would
  silently change meaning. The tree is validated by pydantic (`extra="forbid"`) and the JSON
  Schema, needs no sanitiser, renders as Svelte components, and exports by a walk. `type`
  and `blocks` are not valid language tags, so the union `StrictStr | RichText |
  dict[LanguageTag, StrictStr | RichText]` is unambiguous.
- **Levels per field** (enforced by the validator, declared in the property YAML as
  `rich: block | inline` on the existing `richtext` kind; `text` stays plain):

| Level | Allowed | Fields |
|---|---|---|
| **block** | all blocks, marks, links, pipes, breaks | question `label` and `help` (every type; a note's content is its label), `metadata.description`, `Consent.text` (no pipes, as today), `EndNode.message`, and later `Ending.body`, `closedMessage`, `notOpenMessage` (EN1, EN3) |
| **inline** | exactly one `p`; marks, links, pipes, breaks; no headings or lists | `Choice.label`, `MatrixRow.label`, slider `minLabel`/`maxLabel`, `Page.title`, `constraintMessage`, `Consent.agreeLabel`/`declineLabel` |
| **plain** | string only | `metadata.title` (used in `<title>`, lists, exports), `Block.title`, choice values, ids, hook strings |

  Headings in an answerable question's label are allowed by the model but the editor hides
  the heading buttons there (a heading inside a question stem is a layout smell); notes,
  description, consent and endings show them. Needs human: see §13 Q2.

### 3.2 Validation (osp-spec, all diagnostics, never exceptions)

- Structure: pydantic rejects unknown keys, unknown block types, `level` outside 1–3,
  nested lists (the shape has no nesting), marks outside `{b, i, u}`.
- `link.scheme` (error): `href` not `https:` (no `http:`, `mailto:`, `javascript:`, relative).
  `link.empty` (error): a link with no text. Rendering adds `rel="noopener noreferrer"`; it
  is never stored.
- `text.too_long` (error): more than **20 000** text characters per field per language
  (pipes count 0); `text.too_many_blocks` (error) above 200 blocks or 100 list items.
  Needs human: §13 Q4.
- `text.block_not_allowed` (error): headings or lists, or more than one block, in an
  inline field.
- Pipes: the same `_check_ref` path as `${id}` today (`pipe.invalid`, `ref.*`,
  `consent.pipe`), with the diagnostic pointer at the node
  (`/pages/2/items/0/label/en/blocks/0/content/3`).
- Empty rich text (no text, no pipes) is valid and equal to `""`.

### 3.3 Normalisation (RT-D3)

Rich text with **no formatting** (one paragraph, no marks, links, headings, lists, breaks or
`lang`) is stored as the plain string it is, with pipes written back as `${id}`. The text
ops (`set_property`, `set_choice`, `add_choice`, `add_question`, `add/rename_matrix_row`,
`set_consent`) call one `normalise_text()` in osp-spec before writing. So existing surveys,
fixtures, the AI drafter (AI1), bulk paste and the question bank (QB) keep plain strings,
diffs stay small, and a plain string compiles exactly as today. The builder converts plain →
rich on load (regex `${id}` → pipe nodes, the same regex as the validator) and rich → plain
through the op.

### 3.4 Registration (completeness guard)

`RichText`, `Block`, `Inline` become `$defs` with properties, so `schema_fields()` adds
`RichText.type`, `RichText.blocks`, `Block.*`, `Inline.*` keys: both capability tables get
rows (native for LSS; native/lowered/approximated for XLSForm per §8), plus behaviour rows
`$rich.bold`, `$rich.italic`, `$rich.underline`, `$rich.link`, `$rich.heading`,
`$rich.list`, `$rich.break`, `$rich.lang`. Property YAMLs gain `rich: block|inline`;
`export_schema.py` regenerates `survey.schema.json`; `fixtures/FORMAT.md` and
`docs/building-a-survey.md` document the subset. `doc.py` `text_sites()` learns to walk the
tree and to cover page titles, slider labels and consent (today's gap).

## 4. Piping chips

- In the editor a pipe is an **atom inline node** rendered as a chip: `contenteditable=false`,
  one caret stop, Backspace/Delete removes it, `aria-label="Piped answer: Age (age)"`. The
  chip shows the question's `name` or id and a type glyph; a chip whose reference the server
  flags (`ref.unknown`, `ref.forward`, `ref.no_value`…) gets the error style and the
  diagnostic text as its tooltip (the card diagnostics already carry pointers).
- **Insertion:** a toolbar button *Insert answer* opens a picker (bits-ui Combobox:
  `role=combobox` + listbox, typeahead, groups "Earlier questions", "Variables",
  "Built-ins"); typing `${` opens the same picker inline (`@tiptap/suggestion`), Escape
  cancels and leaves `${` as text. Candidates come from the survey JSON the client already
  holds, the way the condition editor's `questionsFromSurvey()` does (items with a value in
  document order before the edited item, matrix rows as `m_r`, embedded/assigned/computed
  variables, the six built-ins). That listing is a convenience; **the validator is the truth**
  and its `ref.*` diagnostics show on the chip, so rule 8 (no survey logic in Svelte) holds
  as it does for conditions.
- Consent fields and other no-pipe fields hide the button and the trigger; a pasted `${x}`
  there stays text and the server says `consent.pipe` as today.
- Pasted or typed `${id}` in a pipe-capable field becomes a chip when the inner text is an
  identifier or built-in (an input rule on `}`), otherwise it stays literal text, exactly as
  the plan compiler treats it.
- Plain-string fields keep `${id}`; the cards' `PipedText` tokens and the chips look alike.

## 5. Translations

- The properties pane gets an **Editing language** select (default language first; kept
  per survey in the URL `?lang=` and remembered), passed down to `PropertyPanel`,
  `ChoiceListEditor`, `RowsEditor`, `NodeCard` and the consent editor (which already has one;
  it joins the pane's). The existing per-field "Missing translation" hint, fallback
  placeholder and `withTranslation` map handling stay.
- When editing a non-default language, each rich field shows a **reference strip** above
  the editor: the default-language value rendered read-only with the ui-components
  renderer (formatting and chips visible), collapsible, with *Copy from <default>* that
  copies the tree (formatting, links and chips included) as the translation's starting
  point. Formatting may differ per language (a German heading may need two words).
- Chips are language-independent (they reference ids); the picker shows labels in the
  editing language with fallback.
- Character counts are per language. The validator's `text.missing_translation` is unchanged.
- A survey-wide translations table (every text × language, CSV/XLIFF round trip) is a
  separate later task (TR1), not RT.

## 6. Paste cleaning

ProseMirror parses pasted HTML **through the schema**, so anything the schema has no rule
for is dropped or unwrapped by construction; we add rules, not a sanitiser:

- `<b>`, `<strong>`, `font-weight: bold|600+` → `b`; `<i>`, `<em>`, `font-style: italic` →
  `i`; `<u>`, `text-decoration: underline` → `u` (Google Docs pastes styled `<span>`s; Word
  pastes `<b>`/`<i>` with `mso-` styles, which are ignored).
- `<h1>`–`<h6>` → `h` clamped to 1–3 in block fields, paragraphs in inline fields;
  `<ul>/<ol>` nested → flattened to one level (indent markers from Word's `mso-list` become
  plain items); `<li>` with blocks inside → one run.
- `<a href>` kept only when the href is `https:`; otherwise the text stays and the link is
  dropped (announced: "1 link removed: not https").
- `<p>`, `<div>`, `<br>` → paragraphs and breaks; in inline fields, paragraphs become
  breaks (or spaces, for choice labels: a choice label has no `br` button, Enter commits).
- Dropped: images, tables, comments, footnotes, `<o:p>`, `<style>`, scripts (never
  executed: parsing is DOM-only), colours, fonts, sizes, alignment, `&nbsp;` → space,
  whitespace collapsed. Plain-text paste: lines → paragraphs or breaks; `${id}` → chips.
- A status line after a paste that changed something: "Formatting simplified: colours and
  2 images removed" (polite live region), so the researcher is not surprised.
- Tests: `web/builder/src/lib/richtext/fixtures/paste/*.html` (hand-written samples in the
  style of Word, Google Docs, a web page, Outlook) with expected JSON; vitest in jsdom.
- The server re-validates every value (§3.2); the client cleaning is for the researcher,
  not for safety.

## 7. Rendering

- **Plan contract:** per-language text becomes `Block[]` instead of `Segment[]`; a plain
  string compiles to one `p` whose runs are today's segments. `runtime-plan.schema.json`
  changes with `make contract`; the engine's `RenderedText` becomes rendered blocks whose
  runs are `{kind: 'text'|'value', text, marks?, href?, lang?}` (values stay escaped data).
- **`toHtml` / `toPlain`:** `toHtml` emits only our tags (`p`, `h3`–`h5`, `ul`, `ol`, `li`,
  `strong`, `em`, `u`, `a href rel`, `br`, `span lang`) with every text escaped, from the
  tree: safe by construction. A **single paragraph emits no `<p>` wrapper**, so every
  existing expected trace stays byte-identical. `toPlain` flattens for accessible names,
  `document.title`, the error summary and the harness comparison (`player.ts:404`).
- **Participant UI:** ui-components `Text` type becomes blocks; `RichText.svelte` renders
  blocks and runs as components (`<strong>`, `<em>`, `<u>`, `<a>`, `<h3>`…, `<ul>`), still
  never `{@html}`; `RichInline.svelte` renders the inline level inside `<label>`/`<legend>`
  (block content is not valid there). Question labels with block content are rendered in a
  `<div id>` referenced by `aria-labelledby`, as `QuestionFrame` can already do for help.
  Headings map to `h3`–`h5` under the page's `h2`. Links open in a new tab
  (`target=_blank rel=noopener noreferrer`) with visually hidden "(opens in a new tab)";
  needs human §13 Q3. End message, consent and page titles stop using `plain()` and render
  rich. `svelte/no-at-html-tags` becomes an eslint **error** across `web/`.
- **Builder preview** is the runtime in an iframe, so it shows formatting as soon as the
  runtime does. Builder cards (`CardShell`, `PipedText`) render the same component read-only.
- **Fixtures:** `fixtures/41-rich-text/` (block and inline fields, every mark, links, lists,
  headings, pipes inside formatting, two languages, a missing translation), with expected
  traces; `27-unicode-text` gains an RTL rich label.

## 8. Exports and imports

| Node | XLSForm (Enketo / Collect Markdown) | LSS (HTML + Expression Manager) |
|---|---|---|
| `p` | paragraphs separated by a blank line | `<p>` |
| `br` | newline | `<br />` |
| `b` / `i` | `**text**` / `_text_` | `<strong>` / `<em>` |
| `u` | `<span style="text-decoration:underline">` (XLSForm allows styled spans; Enketo renders them; Collect: approximated, not verified) | `<u>` |
| link | `[text](https://…)` | `<a href rel="noopener noreferrer">` |
| `h` level L | `#` × (L+1), lowered (absolute heading sizes in the form) | `<h3>`–`<h5>`, lowered |
| `ul` / `ol` | `- item` / `1. item` (single level; native in Enketo, approximated in Collect) | `<ul>` / `<ol>` native |
| pipe | `${name}` / `${osp_label_q}` as today | `{code}` / `{code.shown}` as today |
| `lang` | lost: `$rich.lang` unsupported | `<span lang>` |
| literal `* _ # \` in text | **escaped with `\`** (the XLSForm rule), which replaces today's `$text.markup` warning on plain text: text shows as written. Behaviour change for existing surveys; needs human §13 Q5 | `html.escape` as today; `{` → `\{` as today |

Loss diagnostics come from the capability rows (§3.4) through the existing `note()` path
(once per feature and pointer). The codebook and preregistration writers flatten rich text
to Markdown-escaped plain text (they already escape).

No importer exists; when IM1 builds one, LSS HTML and XLSForm Markdown parse into this tree
with the standard library (`html.parser`, allow-list; anything else becomes a diagnostic and
plain text). The question bank (QB) and the AI drafter (AI1) accept the tree or plain
strings; the drafter's guardrails should reject links to anything but `https:`.

## 9. The editor in the builder

- **One component**, `RichTextEditor.svelte` in `web/builder/src/lib/richtext/`, props:
  `value` (plain or rich, one language), `level` (`block | inline`), `pipes` (candidate list
  or `none`), `referenceValue` (§5), `maxChars`, `label`/`description` ids, `onCommit`,
  `placeholder`. Files: `schema.ts` (the extensions and the pipe node), `convert.ts` (spec
  tree ↔ ProseMirror JSON, plain ↔ rich; property-based tests that `fromDoc(toDoc(x)) = x`),
  `paste.ts`, `Toolbar.svelte`, `LinkDialog.svelte`, `PipePicker.svelte`.
- **Buffering contract kept:** `onUpdate` → convert → compare with the last committed value
  → 600 ms debounce, commit on blur, Escape reverts to the committed value, server echoes
  never clobber a draft with focus (same rules as `BufferedInput`, registered with the
  `BUFFERS` context so `PropertyPanel.flush()` still works).
- **Edit on focus:** a field shows the read-only renderer styled as an input; focusing it
  (click, Tab, Enter) swaps in the editor, whose Tiptap instance is created once per pane
  and moved between fields (`editor.mount`/`setContent`). A choice list with 200 rows then
  costs 200 cheap renders and one editor, not 200 ProseMirror views, and visual snapshots
  stay stable.
- **Toolbar** (bits-ui Toolbar: `role=toolbar`, roving tabindex, arrow keys, Home/End;
  buttons are ui-components `IconButton`s with `aria-pressed`, labels and
  `aria-keyshortcuts`): Bold `Ctrl+B`, Italic `Ctrl+I`, Underline `Ctrl+U`, Link `Ctrl+K`
  (ui `Dialog` with URL field, https validation, Remove link), Bulleted list, Numbered list,
  Heading (block fields: a small `Select` Paragraph/Heading 1–3), Line break
  (`Shift+Enter`), Insert answer (§4), Clear formatting, Undo/Redo (`Ctrl+Z`/`Ctrl+Y`).
  Inline fields show only Bold, Italic, Underline, Link, Insert answer. Markdown input rules
  (`**x**`, `- `, `1. `) are on for people who type that way.
- **Keyboard:** Tab and Shift+Tab always leave the editor (never inserted); Escape in the
  editor reverts the draft (the existing contract); `Alt+F10` focuses the toolbar and
  Escape from the toolbar returns to the text (the WAI-ARIA toolbar pattern).
- **Accessible name and state:** the editor root is `role=textbox aria-multiline`
  (`true` for block, `false` for inline), `aria-labelledby` the field label,
  `aria-describedby` hint + count + error, `aria-invalid` on server errors,
  `aria-placeholder`. Mark toggles update `aria-pressed`; shortcut toggles announce
  ("Bold on") through the existing `announce()` (polite, deduplicated); link insertion and
  chip insertion announce too.
- **Character count:** `N / 20 000` below the field (text characters, per language), live
  region only from 90 % of the limit; above the limit the count turns into the error and
  the commit still happens (the server's `text.too_long` is what blocks publishing).
- **320 px:** toolbar wraps to two rows and collapses rarely used buttons into a *More* menu
  (bits-ui DropdownMenu) at `< 480 px`; chips wrap; link dialog is full-width; the
  properties pane is already a drawer at 320 px. Targets ≥ 44 px.
- **Theme:** tokens only (light/dark); chips use the existing `PipedText` token style;
  editor focus ring is the shared `focus-visible` 2 px outline.
- **Where it plugs in:** `PropertyField` (`richtext` block/inline per YAML; `text` kinds
  that are translatable and participant-facing use the inline editor; `metadata.title` stays
  an `Input`), `NodeCard` end message (block), `ConsentEditor` text (block, no pipes) and
  labels (inline), `ChoiceListEditor` and `RowsEditor` rows (inline, edit-on-focus; Alt+Arrow
  reorder and Enter-to-next-row keep working; `PastePanel` stays plain). `FlowView`'s
  add-node message and `SurveyList`'s title stay plain inputs.
- **Tests:** vitest (convert round trips, paste fixtures, normalisation parity with Python
  through the shared fixture), builder-dom tests for the toolbar states, e2e
  (`richtext.spec.ts`: type/format/link/list/chip/paste flows, keyboard-only, Escape revert,
  320/375/1440 snapshots on three platforms, axe light and dark), runtime e2e (rendered
  formatting, link attributes, no `{@html}`), harness fixture 41.

## 10. Security

- The model is closed and validated server-side; the client never sends HTML; the runtime
  never parses HTML. `{@html}` is banned by lint. Hrefs are `https:` only, length-capped,
  rendered with `rel="noopener noreferrer"`. No colours, fonts, sizes, classes or styles are
  storable, so no CSS injection surface. CSP is unchanged.
- Piped values stay `value` parts (escaped data), never parsed as rich text, including in
  `toHtml` for traces. Hook-set text stays plain and escaped (runtime-design §hooks).
- Paste parsing is DOM parsing in the builder tab under its own CSP; scripts in pasted
  HTML never run (ProseMirror uses `DOMParser`, not `innerHTML` on a live element).
- Size limits (§3.2) bound memory for ops, plan compilation and exports; the existing
  100 000-character paste cap stays for bulk choice paste.

## 11. Recommendation and decisions proposed

Build the model first and end to end (spec → plan → runtime → exports) with fixtures, then
the editor, then the per-row editors and translations. Phases:

| Phase | What | Effort |
|---|---|---|
| 1 | RT2 model end to end (spec, validator, normalisation, ops walker, plan contract, engine, runtime + ui-components renderer, fixtures, docs) | ~3 agent-days |
| 2 | RT3 the editor (Tiptap, converters, paste, toolbar, link dialog, chips + picker, counts, a11y, 320 px, e2e + axe + snapshots) wired into property fields, end message and consent | ~3 agent-days |
| 3 | RT4 exports (XLSForm Markdown writer + escaping, LSS HTML writer, capability rows, diagnostics) ∥ RT5 choice and row editors (edit-on-focus) | ~1.5 + ~1.5 agent-days |
| 4 | RT6 translations in the pane (editing language, reference strip, copy from default) | ~1.5 agent-days |
| later | TR1 translations table + CSV/XLIFF; EN1/EN3 use the model for endings and closed messages; MM1 adds a media block; IM1 parses LSS/XLSForm text into the tree | per their plans |

Decisions proposed (to be confirmed by the owner):

- **RT-D1 Editor:** Tiptap 3 open-source core on ProseMirror (MIT), builder-only, lazy
  chunk, our own toolbar from bits-ui + ui-components. No StarterKit, no Pro, no cloud.
- **RT-D2 Model:** a closed JSON tree (`{"type":"rich","blocks":[…]}`) as a third `Text`
  variant; never HTML or Markdown strings in the spec; plain strings stay valid everywhere.
- **RT-D3 Normalisation:** formatting-free rich text is stored as a plain string by the ops.
- **RT-D4 Subset:** paragraphs, line breaks, bold, italic, underline, `https:` links,
  single-level bulleted and numbered lists, headings 1–3, language spans, pipes. No colours,
  fonts, sizes, alignment, images, tables, code (media via MM1).
- **RT-D5 Levels:** block for question label/help, description, consent text, end message
  and future endings/closed messages; inline for choice and row labels, slider labels, page
  title, constraint message, consent button labels; `metadata.title` and builder-only
  strings stay plain.
- **RT-D6 Rendering:** tree → Svelte components; `{@html}` banned by lint; `toHtml` emits
  only our tags with escaped text and keeps single paragraphs unwrapped.
- **RT-D7 Links:** `https:` only; open in a new tab with `rel="noopener noreferrer"` and a
  hidden "(opens in a new tab)".
- **RT-D8 Limits:** 20 000 text characters per field per language, 200 blocks, 100 list
  items, single-level lists; counts shown in the editor.
- **RT-D9 Exports:** XLSForm gets the Markdown subset with backslash escaping of literal
  markup; LSS gets allow-listed HTML; every loss is a capability row.
- **RT-D10 Pipes:** chips backed by `{pipe: id}` nodes; candidates listed client-side like
  the condition editor; server `ref.*` diagnostics are the truth and show on the chip.
- **RT-D11 Translations:** one editing language per pane with the default language as a
  read-only reference and *Copy from default*; formatting may differ per language.

## 12. Proposed build tasks (for the lead to add to `tasks.md` / HubAI)

| id | what | depends on | acceptance criteria |
|---|---|---|---|
| RT2 | Rich-text model end to end | – | `RichText`/`Block`/`Inline` in `osp_spec.model` with the union in §3.1; validator codes `link.scheme`, `link.empty`, `text.too_long`, `text.too_many_blocks`, `text.block_not_allowed`, pipes through `_check_ref` with node pointers; `normalise_text()` used by every text op, with a shared fixture proving Python and TS agree; `doc.py` walks the tree and covers page titles, slider labels and consent; property YAML `rich: block\|inline` + `export_schema.py`; both capability tables cover the new keys (§3.4); plan contract `Block[]` (`make contract`), engine rendered blocks, `toHtml` single-paragraph rule keeps every existing expected trace identical, `toPlain`; ui-components `RichText`/`RichInline`, runtime renders label/help/choices/rows/slider/end/consent/page title rich with `aria-labelledby` where needed; `svelte/no-at-html-tags` error; fixture `41-rich-text` + RTL case; docs (`building-a-survey.md`, `FORMAT.md`, `semantics.md` §8 note on pipes inside formatting); hypothesis fuzz on the tree |
| RT3 | The editor in the builder | RT2 | Tiptap deps added (licence gate green; depcruise rule confining them; lazy chunk); `richtext/` module per §9 with round-trip property tests and paste fixtures (§6); toolbar, link dialog, chips + picker, counts, Escape/blur/debounce contract, edit-on-focus; wired into `PropertyField` (block/inline), `NodeCard`, `ConsentEditor`; cards render rich; e2e `richtext.spec.ts` (flows, keyboard-only, paste, 320/375/1440 snapshots on linux + win32 + darwin via `snapshots.yml`, axe light/dark); bundle size recorded in the devlog |
| RT4 | Exports | RT2 | XLSForm Markdown writer with escaping (§8 table) and LSS HTML writer; `$rich.*` and field rows with levels and notes; diagnostics once per feature/pointer; tests on fixture 41 for both targets; the optional LimeSurvey Docker import test passes with rich labels; `docs/publishing.md` capability text updated |
| RT5 | Choice and row editors | RT3 | `ChoiceListEditor` and `RowsEditor` rows use the inline editor with edit-on-focus; Alt+Arrow, Enter-to-next, Escape, `aria-label` per row kept; 200-row perf check (one editor instance); `PastePanel` unchanged; e2e + axe + snapshots |
| RT6 | Translations in the pane | RT3, RT5 | Editing-language select in `PropertiesPane` (URL `?lang=`), passed to panel, choices, rows, end message, consent; reference strip + *Copy from default*; missing-translation hints per language; counts per language; e2e in `languages.spec.ts` (en/de flows, keyboard, axe) |

## 13. Open questions (needs human)

1. **Underline:** keep it (the owner listed it; LSS native, XLSForm approximated via a styled
   span) or drop it to keep exports clean? My recommendation: keep.
2. **Headings in answerable question labels:** the model allows block content in every
   `label`; should the editor offer headings only in notes, description, consent and endings
   (recommended), or everywhere?
3. **Links open in a new tab** (recommended, so a participant does not lose the survey) or
   in the same tab?
4. **Limit of 20 000 characters** per field per language (recommended; a consent text is
   rarely above 8 000) and whether choice labels should have a smaller cap (say 1 000).
5. **XLSForm escaping of literal `* _ #`** in existing plain text: today they pass through
   and may render as formatting in Enketo/Collect; the plan escapes them so text shows as
   written. Confirm this behaviour change.
6. **`metadata.title` stays plain** (recommended: it is the `<title>`, the list entry, the
   export name) or becomes inline rich?
7. **Build order:** RT2 → RT3 → (RT4 ∥ RT5) → RT6 as proposed, or exports (RT4) straight
   after RT2 so the model's losses are visible before the editor lands?
