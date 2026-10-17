# Property panel profiles (task B21)

**Status:** plan, 17 Oct 2026 · **Depends on:** the property schema (B1, `osp_spec.property_schema`) and the property panel (B4)
**Clean-room:** the idea (a lab tailors which properties researchers see and adds its own) is common to several builders. Nothing here is taken from any of them: our profile is a declarative overlay on our own property schema.

## 1. What a lab wants

A methods lab onboarding students does not want every property of every question type in the panel. It wants to:

1. **hide** properties nobody in the lab uses (`choiceOrder`, `constraintMessage` …);
2. **reorder** the ones that remain, so the important ones come first;
3. **rename group headings** ("Logic" → "Conditions");
4. **set defaults for new questions** (every new question `required`, say);
5. **add its own properties** (a "Construct" text, a "Scoring weight" number, a "Pre-registered" boolean, a "Scale" choice …), stored on the question and visible in the codebook, so analysis scripts and the pre-registration can refer to them.

None of this changes how a survey runs. A profile is a *view* of the schema plus a set of *annotations*; the runtime, the engine and the exporters never read a profile.

## 2. Data model

### 2.1 The profile (`osp_spec.panel_profile`, L1, pure)

One profile per lab, a JSON document validated by a pydantic model (strict, `extra="forbid"`, like every spec model). Every entry refers to the stock property schema by `type` (a question type, `page`, `block`, `survey`) and property key.

```yaml
profileVersion: osp-panel-profile/0.1
hidden:                      # "<type>.<key>" or "*.<key>" (every type that has <key>)
  - "*.constraintMessage"
  - single.choiceOrder
order:                       # per type (or "*"): these keys first, in this order; the rest keep schema order
  "*": [label, required, help]
groups:                      # heading overrides, translatable text like schema labels
  Logic: { en: "Conditions" }
defaults:                    # per question type: the value a *new* question starts with
  single: { required: true }
  text: { multiline: true }
custom:                      # the lab's own properties, stored under `custom` on questions
  - key: construct
    kind: text
    label: { en: "Construct" }
    help: { en: "The psychological construct this item measures." }
    group: Basics
  - key: weight
    kind: number
    label: { en: "Scoring weight" }
    default: 1
    types: [single, multi, slider]
  - key: preregistered
    kind: bool
    label: { en: "Pre-registered" }
  - key: scale
    kind: choice
    label: { en: "Scale" }
    options:
      - { value: likert, label: { en: "Likert" } }
      - { value: vas, label: { en: "Visual analogue" } }
```

`CustomProperty`:

| Field | Type | Notes |
|---|---|---|
| `key` | `^[a-z][a-z0-9_]{0,39}$` | Unique within the profile; the key under `custom` on the question and the codebook name |
| `kind` | `text` / `number` / `bool` / `choice` | Maps onto the panel's `text` / `number` / `bool` / `enum` editors. No rich text, conditions or lists: a custom property is an annotation, not logic |
| `label`, `help` | `Text` | As schema labels |
| `types` | list of question types, or absent | Absent: every question type |
| `options` | `[{value, label}]` | `choice` only, required then, unique values |
| `default` | scalar | Must fit `kind` (and be one of `options` for `choice`) |
| `group` | a schema group | Default `Advanced` |
| `required` | bool | Panel marks it; the survey's own validation does not block publishing on it (it is an annotation), but a `profile.custom_missing` **warning** is reported |

Limits: 40 custom properties, 50 options each, 64 KB body.

### 2.2 Where custom values live: `custom` on the question

`_QuestionBase` gets one new field:

```python
custom: dict[CustomKey, CustomValue] | None = None   # CustomKey = the key pattern above
                                                     # CustomValue = StrictStr | StrictInt | float | StrictBool
```

- **Reserved key.** `custom` is listed under `hidden` in every question schema file ("edited through the lab profile's custom properties") and is **not** settable through `set_property` (added to `FORBIDDEN`): a value goes in through the new op `set_custom_property` (§4), so there is exactly one editing path with a proper inverse.
- The spec validates the **shape** (keys, scalar values, size); whether a value fits the lab's definition (kind, options) is a **profile check**: `check_custom_values(survey, profile)` in `osp_spec.panel_profile` returns `profile.*` diagnostics (warnings, never errors, because a survey must stay valid when a lab edits or deletes its profile, or when it moves to another lab).
- Pages, blocks and the survey do not get `custom` in this task (the row says "per question type"). Adding it later is the same pattern.
- Runtime and engine: `osp_runtime.plan` builds its own item structure, so `custom` never reaches the plan or the participant. Exporters: `custom` gets an `unsupported` row ("lab annotation, not part of the form") in the XLSForm and LimeSurvey capability tables, so the completeness guard passes and the export diagnostics explain the drop.

### 2.3 Applying a profile (pure)

`apply_profile(schemas, profile) -> (schemas', diagnostics)` in `osp_spec.panel_profile` builds the **effective schema document** the builder renders:

1. drops hidden properties, except `required` ones (`profile.required_hidden`, warning, kept visible);
2. reorders: listed keys first, then the rest in schema order (unknown keys: `profile.unknown_key`, ignored);
3. replaces each property's `default` with the profile default after validating it against the model (`profile.bad_default`, ignored);
4. appends each custom property as a `custom.<key>` property entry (kind mapped, `options` copied) on every type it applies to, in its group; a key that collides with a stock property of that type is `profile.key_clash` and skipped;
5. the document gains `groupLabels` (the heading overrides) and `profileApplied: true`.

A broken profile never breaks the panel: whatever does not apply is a diagnostic and the stock schema stands in for that part.

## 3. Storage, permissions, API

**Store** (`osp_store.panel_profiles`, mixed into `Store` like `ThemeLibrary`): table `panel_profiles` (migration `0009_panel_profiles`, additive): `tenant_id` PK → `tenants`, `body` JSON, `updated_by`, `updated_at`. One row per lab; no row means the stock panel. Methods: `get_panel_profile(ctx)`, `set_panel_profile(ctx, body)`, `clear_panel_profile(ctx)`; tenant-scoped, audited (`profile.set`, `profile.clear`), 64 KB cap, opaque JSON (osp-app validates).

**Permissions** (`osp_app.auth.permissions`): `PROFILE_VIEW` (viewer, editor, owner) and `PROFILE_MANAGE` (**owner only**, as the task row says), both on the tenant resource.

**App commands** (`osp_app.panel_profile`, registered like the theme commands): `profile.get`, `profile.set` (validates with the spec model and `apply_profile` against the bundled schemas; a schema error is `Rejected` with diagnostics; warnings are saved and returned), `profile.clear`, `profile.schemas` (the effective schema document for the caller's lab).

**API** (`/api/panel-profile`, thin):

| Route | Who | Returns |
|---|---|---|
| `GET /api/panel-profile?tenantId=` | member | `{tenantId, profile \| null, diagnostics, canManage, updatedBy?, updatedAt?}` |
| `PUT /api/panel-profile` `{profile, tenantId?}` | owner | the same; 422 with diagnostics when invalid |
| `DELETE /api/panel-profile?tenantId=` | owner | 204 (back to the stock panel) |
| `GET /api/panel-profile/schemas?tenantId=` | member | the effective `PropertySchemasDoc` (same shape as `GET /api/meta/property-schemas`, plus `groupLabels`, `profileApplied`, `defaults`) |

`make contract` regenerates `contract/openapi.json` and the TS client.

## 4. The op: `set_custom_property`

New module `osp_ops/custom_property_ops.py`:

```text
set_custom_property(target: question id, key: CustomKey, value?: scalar, unset?: bool)
```

Sets or removes one key of the question's `custom` object (creating or dropping the object as needed). Inverse: the previous value, or `unset`. Validated by the model (`custom` shape). Rejected for a non-question target (`op.not_applicable`) and for anything that fails validation, as with `set_property`. Tests plus a hostile-input fuzz case, as the registry requires.

## 5. Export and codebook impact

- **Survey JSON** (the document, the JSON view, exports of the survey): `custom` is an ordinary field of the question, so it is simply there.
- **Codebook** (`osp_targets.data.codebook`): each variable entry gets `"custom": {key: value}` when the question carries custom values (a matrix row inherits its matrix's), and the Markdown lists them as `- Custom: construct = "affect"; weight = 1`. A top-level `customProperties` list names every key in use with the types it appears on, so a reader can see the lab's vocabulary in one place. The codebook documents values, not the lab's labels: the profile is not part of the survey version, so a version stays self-describing without it.
- **CSV / JSON response exports:** unchanged. Custom properties describe questions, not responses; they never become data columns.
- **XLSForm / LimeSurvey:** dropped with a `loss` diagnostic from the capability row (§2.2).
- **Golden fixtures:** `01-all-types` gets a custom value on one question so the codebook goldens prove the field.

## 6. Builder

- **Panel.** `PropertiesPane` loads `GET /api/panel-profile/schemas` (falls back to `/api/meta/property-schemas` on a 403 or error, so a host without the route still works). `PropertyPanel` renders group headings from `groupLabels`; a `custom.<key>` entry is addressed to `set_custom_property` by `opAddress`/`setPropertyOp` (one branch in `logic.ts`), so the field editors need no change.
- **Defaults for new questions.** The effective document's `defaults` per type are appended as `set_property` ops to the `add_question` transaction in the shell's add-question command (one undo step). No logic in Svelte beyond "send what the server listed".
- **Profile editor page.** New page entry `profile` (`src/pages/profile.ts`, Shell view `profile`, host link `profile` in `OPTIONAL_LINK_NAMES`, dev-host URL `/profile`). `lib/profile/ProfileView.svelte`: for each type, a list of its properties with a *Shown* checkbox, move up/down, and a *Default for new questions* field; the group-heading table; the custom-properties table (key, label, kind, options, types, group, default, required); Save (owner) / Reset to stock; read-only for non-owners with a note. Every edit is local state; Save sends the whole profile; the server's diagnostics show under the form. `lib/profile/logic.ts` holds the pure transforms (toggle, move, add/remove custom, profile ⇄ form) with vitest; a component test proves the panel honours a profile.
- **Docs.** `docs/property-profiles.md` (Guide), `docs/hosting.md` gains the optional `profile` link.

## 7. Open questions (not blocking)

- Should pages, blocks and the survey take custom properties too? Same mechanism; left out to keep the first cut small.
- Should the codebook carry the lab's labels for custom keys? It would need the profile at export time; today the codebook stays version-only.
- Per-survey profile override (a study that needs more than its lab's profile)? Not planned; a researcher can still edit the JSON.

## 8. Order of work

spec (model field + profile + apply + check) → ops → targets (capability rows, codebook, goldens) → store (migration, methods) → app (permissions, commands) → api (+ contract) → builder (panel, add-question defaults, profile page) → docs → devlog.
