# The question bank

The bank is where a lab keeps questions, pages and blocks it wants to use again, with the
instruments that come bundled with the platform. Anything in it can be dropped into a
survey in one step, and every inserted copy remembers which item and version it came from,
so the codebook can list the instruments a survey used.

Three kinds of item show up in one list:

| Source | What it is | Who may change it |
|---|---|---|
| **My lab** | Items your lab saved from its surveys, imported from a file, copied from the library, or added as licensed copies | Owners and editors of the lab |
| **Shared on this host** | Items other labs on the same host chose to share (read-only; a host can switch this off) | Nobody but the owning lab |
| **Bundled** | Validated instruments whose text may be redistributed: PHQ-9, PHQ-2, GAD-7, GAD-2, Mini-IPIP, NASA-TLX, the CDC ACE module, and a CC0 demographics set | Nobody; "Save a copy to my bank" makes an editable lab version |

Everyone in a lab can browse, search and insert. Saving, editing, importing, exporting and
deleting need the editor or owner role. Sharing with the host, and adding a licensed
instrument, need the owner role.

## Finding and inserting

In the editor, the **Bank** section sits under the outline, beside the question types.
Opening it folds the question types (they share the room). Type in the search box to match
titles, abbreviations, item text and tags; narrow by source (my lab, shared, bundled) and
by kind (question, page, block). Each card shows the kind, the number of items, the version,
the source and a licence badge; a dot after the title means the bank holds a newer version
than the one already in this survey. Expand a card to see its items, scoring variables,
citation and licence statement.

To insert:

- **Insert** puts the item at the selection: a question after the selected question (or at
  the end of the selected page), a page after the selected page, a block after the selected
  item's block (and into the flow right after it).
- **Drag** a card onto the outline or the canvas. The insertion line shows where it lands:
  a question goes into that gap; a page goes before or after the page under the pointer; a
  block goes before or after that page's block.
- On a narrow screen, Insert picks the item up and the canvas shows **Place here** in every
  gap; Escape or Cancel puts it down.

An insert is one edit: one Undo removes the item, its shared choice lists and its scoring
variables together. Ids that clash with the survey's get a numeric suffix. A choice list the
survey already has with the same options is reused rather than duplicated.

Two kinds of item show a notice the first time they are inserted into a survey: an item
that is free for **non-commercial** research only (the holder's condition and the citation),
and an item **licensed to this lab** (do not share the survey's JSON outside the lab).

## Saving to the bank

Right-click a question, page or block (or press Shift+F10 on it, or open its ⋯ menu) and
choose **Save to bank…**. The same command is in the palette. The dialog asks for a title,
abbreviation, tags, a description and a licence class, and shows what travels with the
part: its items, the shared choice lists it uses, and the computed variables that read only
things inside it (a scoring total, say). Anything that points outside the part is listed
under **Will be cut**: a `showIf` on another page's answer, a piped `${id}` from elsewhere.
The saved copy loses those; the survey itself does not change.

The licence defaults to **Not stated**, which is fine inside the lab but cannot be shared
with other labs. If the words are your lab's own, choose CC BY 4.0 (or CC0) so the item can
be shared later. Owners may also mark an item **Licensed to this lab** (see below).

Saving a part that itself came from one of your lab's items (it carries that item's
provenance) offers **Save as version n+1 of …** instead of a new item. Old versions stay,
so a published survey remains reproducible.

## Provenance on inserted items

An inserted question, page or block carries a small line, for example
*PHQ-9 · bundled · v1*, with:

- **Details**: the item as inserted, with its citation and licence; whether a newer version
  exists; whether the inserted copy was edited since.
- **Replace with v2**: when the bank holds a newer version. The old copy is deleted and the
  new version inserted in the same place, as one undoable edit. It is refused while
  conditions or piping elsewhere still refer to the old copy.
- **Detach**: forgets the provenance (the item stays, edited freely, and is no longer listed
  as that instrument). Undo puts the provenance back.

Questions inside an inserted page or block inherit its provenance; only the object that was
inserted shows the line. The provenance travels into the codebook's "Instruments used"
section and the preregistration record.

## The Bank page

The host may serve a **Bank** page (its link is optional; the top bar's ⋯ menu and the
palette's "Open question bank page" lead to it). It has three tabs.

**Lab bank**: your lab's items with search and a kind filter. For each: **Edit…** (title,
abbreviation, description, tags; the content is version-bound), **Versions** (every
version with who saved it and when; *Compare with current* lists item texts added and
removed), **Share with host** / **Stop sharing** (owners; an item with an unstated licence
is refused and offered a one-click "these are our own words, CC BY 4.0"), **Export** (the
portable `*.osp-bank.json` file) and **Delete…** (soft: surveys that inserted the item keep
their provenance). **Import a bank file…** adds every item of a file to the lab at version 1,
remembering the file as its origin; a file that holds a licensed instrument is taken only
from an owner who ticks the attestation. Items shared by other labs appear below, with
*Save a copy to my bank*.

**Bundled library**: the instruments shipped with the platform, each with the rights
holder's statement, the page it was read on and the date. *Save a copy to my bank* makes an
editable lab item that remembers where it came from.

**Licensed instruments**: see the next section.

## Adding a licensed instrument privately

Many common instruments cannot be bundled: some are proprietary (BDI-II, BAI, STAI, HADS,
GHQ-12, WEMWBS, ISI, Epworth, EPDS, DASS-21, SDQ, CD-RISC, UEQ-S), others are free for
research but their text may not be redistributed (PSS-10, Rosenberg, SWLS, PANAS, WHO-5,
GSE, Grit-S, BRS, UCLA-3, K10, K6, TIPI, SUS, MSPSS, CES-D). For each, the platform ships a
**stub**: the citation, the rights holder's page, the response format and the scoring
recipe, and no item text.

A lab that holds a licence (or has the holder's permission) adds its own copy:

1. On the Bank page's **Licensed instruments** tab, an owner presses **Add our copy…** on a
   stub (or **Add a licensed instrument…** and *Start blank* for a scale of your own).
2. Paste the items, one per line. When each item has its own response wording (BDI-II,
   HADS, GHQ-12, ISI, EPDS), write it after the item text: `Item text | option 0 | option 1
   | option 2 | option 3`, in score order. Otherwise give the shared response options, one
   per line (or leave them blank for the numbers), and choose one grid or one question per
   item. The wizard checks the item count against the stub.
3. Tick **Our lab holds a licence for this instrument; it stays private to this lab** and
   add it.

The result is a block in your lab's bank with the licence class *licensed to this lab*: the
scoring recipe (reversed items, sums or means, subscales, and for the SUS its offset and
factor) is built as computed variables over your items. Such an item is never shared at
host level, is exported only by an owner as the lab's own backup, is imported elsewhere
only with an owner's attestation, and reminds whoever inserts it not to share the survey
JSON outside the lab. The attestation is recorded in the lab's audit log and never shown to
participants.

The recipes follow the published literature; check them against the manual your lab holds
before publishing, and watch the stubs' notes (safety items on the BDI-II and EPDS, the
DASS's ban on showing scores to participants).

## Licences in the bank

| Class | Meaning | Shareable with the host |
|---|---|---|
| Public domain, CC0, CC BY 4.0 | Free to reproduce, adapt and distribute (CC BY: with credit) | Yes |
| With permission | The author's written permission is on file | Yes |
| Free to use | The holder grants use but says nothing about redistribution | No |
| Non-commercial | Free for non-commercial research; a notice shows on insert | No |
| Licensed to this lab | The lab's private copy of a licensed instrument | Never |
| Not stated | The default for a lab's own words until a class is chosen | No |

Only public-domain, CC0, CC BY 4.0 and permission-granted instruments are bundled with the
software (`licence-policy.toml`); the full audit of who allows what is in
`planning/question-bank.md`.
