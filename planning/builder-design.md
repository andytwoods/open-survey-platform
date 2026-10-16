# Builder design

**Status:** draft, 16 Oct 2026 · **Stack:** Svelte (SvelteKit `adapter-static`), Python op registry behind an OpenAPI contract (`review.md` §3.4, §9 Q2)
**Principle:** the builder is **generic components driven by data**, plus a few specialised editors. It holds no survey logic: it displays the model and sends ops.

## 1. Property schema: each question type described once

Lives in `osp-spec` (Python, L1) as data files, exported to the web via the OpenAPI contract.

```yaml
type: likert
family: choice            # chooses the canvas card component
label: { en: "Likert scale" }
properties:
  label:      { kind: richtext, translatable: true, required: true }
  choices:    { kind: choicelist, default: agree5 }
  required:   { kind: bool, default: false }
  randomize:  { kind: bool, default: false }
  showIf:     { kind: condition }
  help:       { kind: richtext, translatable: true }
```

Each export target's capability table (`osp-targets`) says, per property, whether it is `native`, `lowered`, `approximated` or `unsupported`. The builder reads both to show badges.

**Generated from the schema:**
- property panels (§2)
- validation (in `osp-spec`)
- docs pages
- export-warning badges
- default values for `add_question`

**Completeness guard:** CI fails if a property has no field editor for its `kind`, or no row in every capability table.

## 2. Generic components (written once)

| Component | Job | Notes |
|---|---|---|
| **Outline tree** | Pages → blocks → questions. Reorder by drag *and* keyboard; multi-select | Emits `move_*` ops |
| **Question card** | Canvas preview, one per **family**: `choice`, `text`, `number`, `matrix`, `scale`, `note` | Read-only preview; click selects |
| **Property panel** | Renders a schema into a form: loops over `properties`, picks a field editor by `kind` | No per-type code |
| **Field editors** by `kind` | `text`, `richtext`, `number`, `bool`, `enum`, `choicelist`, `condition`, `expression` | Each emits `set_property` |
| **Diagnostics strip** | Validation errors + export warnings, each linked to its property | Click focuses the field |
| **Shell** | Selection, undo/redo, command palette, shortcuts, save/sync state, conflict banner | Owns the op client |

## 3. Specialised editors

| Editor | What it does | Hard parts |
|---|---|---|
| **Condition builder** | Nested AND/OR rows: *question / operator / value*; operators filtered by question type; text view toggle | Keeping tree and text view in sync; references to deleted questions |
| **Choice list editor** | Codes + labels, reorder, shared lists, bulk paste | Code uniqueness; changing codes after data exists |
| **Flow editor** | Nested list of `block`, `branch`, `randomiser`, `assign`, `end` | Readable nesting; drag across levels; shows unreachable nodes from `osp-qa` |
| **Matrix editor** | Rows × columns, each with codes | Large grids, keyboard navigation |
| **Translation grid** | One column per language, missing cells highlighted | Rich-text cells |

## 4. Edit flow

```text
user toggles "required"
  → field editor emits   set_property(q12, "required", true)
  → op client sends      { op, params, opId, baseRevision }
  → Python osp-ops       apply → validate → store inverse → new revision
  → response             { revision, patch, diagnostics }
  → Svelte store         applies patch; card, panel, outline, JSON view update
```

- **Text inputs** edit a local buffer and send on blur or after a pause. No round trip per keystroke.
- **Optimistic** only for trivial structural gestures (move, rename), reconciled when the server replies.
- **Undo/redo** are ops too: `undo(transactionId)`. A drag or a bulk paste is one transaction.
- **Conflicts:** a stale `baseRevision` gets a 409. The client refetches and replays pending local ops, or shows the conflict banner.
- **JSON view:** CodeMirror holds edits until **Apply**, which sends one `replace_survey` op, validated like any other.

## 5. Preview and debugger

- **Preview:** publish the draft to a temporary XForm and render it in **Enketo**, so the preview is exactly what participants see.
- **Debugger panel:** steps the Python engine (`osp-engine`) through a simulated participant. It shows the current page, why each question is visible (condition + values), realised orders and the assigned condition. Answers come from the user or a saved script.

## 6. Libraries (all permissive)

| Need | Library | Licence |
|---|---|---|
| Accessible primitives (menu, dialog, tabs, combobox, popover) | **Bits UI** (or Melt UI) | MIT |
| Drag and drop with keyboard support | `svelte-dnd-action` | MIT |
| Text/JSON/expression editor | CodeMirror 6 | MIT |
| Icons | Lucide | ISC |
| API client | generated from `contract/openapi.json` (e.g. `openapi-typescript` + `openapi-fetch`) | MIT |
| Component tests | Vitest + Testing Library; Playwright for end to end; axe-core for accessibility | MIT / MPL-2.0 (axe) |

Confirm each licence in CI (`automation.md`). axe-core is MPL-2.0: fine as a **test-only** dependency.

## 7. Accessibility (designed in, not added later)

- Every drag action has a keyboard equivalent (move up/down, move to block).
- Focus is preserved when patches arrive. No full re-render of the panel being edited.
- Diagnostics are announced through a live region.
- axe-core runs in CI on every builder screen. Manual NVDA + VoiceOver pass before the pilot.

## 8. Adding a question type

1. Add a YAML entry to the property schema.
2. Add its row to each target's capability table, plus lowering/emit code where needed.
3. Write a card component **only** if it introduces a new family.
4. Add fixtures. CI's completeness guard tells you what's missing.

## 9. Build order (agent tasks)

| # | Task | Depends on | Done when |
|---|---|---|---|
| B1 | Property schema format + 6 MVP types | `osp-spec` | Schema validates; types load |
| B2 | Op client + store + patch applier + undo/redo | contract | Unit tests: apply, reject, conflict, undo grouping |
| B3 | Shell + outline tree (drag + keyboard) | B2 | Playwright: reorder by mouse and keyboard; axe clean |
| B4 | Property panel + basic field editors (`text`, `number`, `bool`, `enum`, `richtext`) | B1, B2 | Every MVP property editable; focus kept on patch |
| B5 | Question cards (6 families) | B1 | Visual snapshot per family |
| B6 | Choice list editor | B4 | Codes unique; shared lists work |
| B7 | Condition builder | B4 | Nested AND/OR round-trips with the text view; deleted-reference diagnostic |
| B8 | Flow editor | B3, B7 | Build the §2.3 example flow; unreachable nodes flagged |
| B9 | JSON view with Apply | B2 | Invalid JSON never corrupts the draft |
| B10 | Diagnostics strip + export badges | B1, capability tables | Badge appears for an unsupported feature on a selected target |
| B11 | Enketo preview + debugger panel | runtime, engine | Preview matches participant view; debugger trace matches the fixture |

B1–B2 come first. After that, B3–B7 can run in parallel (3–5 agents), then B8–B11.
