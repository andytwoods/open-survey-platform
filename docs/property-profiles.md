# Property panel profiles

A lab can tailor the **property panel** (the pane on the right of the editor) for everyone
in it: hide properties nobody uses, put the important ones first, rename the section
headings, set what a new question starts with, and add the lab's own properties. This is
the lab's **panel profile**. Only lab **owners** can change it; everyone else sees its
effect the next time they open a survey.

A profile is a view of the panel plus annotations. It never changes how a survey runs, and
a survey never depends on it: delete the profile and every survey stays valid.

## Opening the profile page

**Panel profile** is in the top bar's *More actions* menu (and in the command palette as
*Open lab panel profile*) whenever your host serves the page. Hosts add it with the
optional `profile` link (see [Hosting](hosting.md)).

## What you can change

| Section | What it does |
|---|---|
| **Properties** | Pick a question type (or pages, blocks, the survey). Untick a property to hide it from the panel; required properties stay. Move properties up or down. For question types, type a **Default for new questions**: every question of that type added from then on starts with it. |
| **Group headings** | Rename the panel's sections (*Basics*, *Choices*, *Logic*, *Validation*, *Advanced*). |
| **Custom properties** | Your lab's own properties: a **key** (letters, digits and `_`, starting with a letter), a **label**, help text, a **kind** (Text, Number, Yes / no or Choice with its options), a default, the panel section it sits in, which question types it applies to (none ticked means all), and whether it is **required**. |

**Save profile** sends the whole profile; **Discard changes** returns to what is saved;
**Remove profile…** goes back to the stock panel.

Parts of a profile that cannot apply (a hidden property that is required, a default the
model refuses, a custom key that clashes with a built-in property) are saved but listed as
warnings under the form, and the stock panel stands in for them.

## Custom properties on a question

In the panel, a custom property looks like any other field. Its value is stored on the
question under `custom` (you can see it in the JSON view):

```json
{ "id": "q7", "type": "single", "label": "How calm do you feel?",
  "custom": { "construct": "affect", "weight": 2.5, "preregistered": true } }
```

Values are plain text, numbers or true/false. They are **annotations for researchers**:
participants never see them, exports to other platforms drop them (with a note), and no
data column carries them.

A **required** custom property with no value is a warning, never an error: the survey can
still be published, and a survey moved to another lab keeps its values. The API's
`GET /api/panel-profile/check/{survey_id}` lists these warnings, as well as values that do
not fit the lab's definition (a text where a number is expected, a choice that is not one
of the options).

## In the codebook

The [codebook](publishing.md) of every published version lists each question's custom
values (`- Lab properties: construct = "affect"; weight = 2.5`) and, at the top, a **Lab
properties** table of every key in use and the question types it appears on. The JSON
codebook carries the same under `custom` per variable and `customProperties`. The codebook
documents values, not the lab's labels: a published version stays self-describing without
the profile.

## The profile document

The profile is JSON (`osp-panel-profile/0.1`); owners can also set it with
`PUT /api/panel-profile` (see the [API reference](reference/api.md#setPanelProfile)):

```yaml
hidden: ["*.constraintMessage", "single.choiceOrder"]   # "*" = every type that has the key
order: { "*": [label, required, help] }                   # these first, then the stock order
groups: { Logic: { en: "Conditions" } }
defaults: { single: { required: true } }
custom:
  - { key: construct, kind: text, label: { en: "Construct" }, group: Basics }
  - { key: weight, kind: number, label: { en: "Weight" }, default: 1, types: [single, multi] }
  - key: scale
    kind: choice
    label: { en: "Scale" }
    options: [{ value: likert, label: { en: "Likert" } }, { value: vas, label: { en: "Visual analogue" } }]
```

`GET /api/panel-profile/schemas` returns the property schemas with the profile applied: the
document the builder renders the panel from.
