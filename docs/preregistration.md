# Preregistration (OSF-ready export)

A preregistration states, before data collection, what will be measured, how participants
are assigned and randomised, and which responses will be excluded. The platform writes the
instrument's half of that for you: every published version has a **preregistration
bundle**, a deterministic ZIP with the exact survey definition and its checksum, the
codebook, a description of the randomisation and assignment, what the platform records
that planned exclusions can rest on, the reproducibility package, and a readable summary
page. It never contains participant data.

Publish first, then export, then share the participant link: the bundle names the version
and checksum that every response will carry, so the registered design is the one
participants get.

## Getting the bundle

After a publish, the dialog's **Exports and records** list has **Preregistration bundle**
(the ZIP) and **Preregistration summary** (the readable page, which a browser prints to
PDF). Both are also plain URLs, so any version can be fetched later:

| What | URL | Needs |
|---|---|---|
| Bundle (ZIP) | `/api/surveys/<id>/versions/<n>/prereg-bundle` ([preregBundle](reference/api.md#preregBundle)) | read access |
| Bundle without the nested reproducibility package | `…/prereg-bundle?repro=false` | read access |
| Summary page (HTML) | `/api/surveys/<id>/versions/<n>/prereg-summary` ([preregSummary](reference/api.md#preregSummary)) | read access |

Read access is enough, so a viewer (a collaborator, a reviewer) can download it. In
`make dev` the links start with `http://localhost:8000`.

## What is in it

```text
README.md  manifest.json  checksums.sha256  summary.html
survey/    survey.json  checksum.txt
codebook/  codebook.md  codebook.json
design/    design.json  structure.md  randomisation.md  exclusions.md
reproducibility-package.zip
```

- **`survey/survey.json`** is the published version, byte for byte what the platform
  stores, and **`checksum.txt`** its SHA-256 (of the canonical JSON: sorted keys, no
  whitespace, UTF-8). Every response collected on this version records the same checksum,
  so a reader can tie data to the registered instrument.
- **`codebook/`** is the [codebook](publishing.md#response-exports) of the version: every
  variable, its labels in every language, codes, conditions, constraints, missing-value
  states and CSV columns, plus the consent texts.
- **`design/structure.md`** lists the blocks, pages and questions and walks the flow in
  order: blocks, branches with their conditions, randomisers, assignment, quota checks and
  endings.
- **`design/randomisation.md`** says how every random decision is made (per-session seed,
  one stream per decision, inside-out Fisher–Yates, fixed at first reach), lists each
  randomiser with what it shuffles and how many children it shows, each shuffled page and
  question, each assigned condition with its levels and the node that assigns it, and the
  quotas. Assignment is simple randomisation (an independent uniform draw per variable);
  the document says so, and that allocation is not balanced or weighted.
- **`design/exclusions.md`** is the planned-exclusions section: for each thing the
  platform records about a response that a rule can rest on, what the platform does and
  the evidence column or record. It is read off the version's settings and flow:
  incomplete sessions (and whether drop-outs are visible, which depends on the save mode),
  late submissions (`_late`, after the resume-link expiry), submissions after the survey
  closed (`_after_close`), non-complete endings (`_end`: screen-outs, quota-full outcomes,
  consent declines), withdrawn responses, the two-device rule, missing-answer states and
  the retention policy. Rules that do not apply to the design (no quotas, no consent page)
  are listed as such. The platform flags; it never drops a submitted response on its own.
- **`design/design.json`** is all of the above as data.
- **`summary.html`** is one self-contained page with everything: identity and checksums,
  the design at a glance, the flow, randomisation, exclusions, the variables, consent,
  custom code, software versions and the bundle's contents. Open it in a browser and print
  it to PDF for a registry that wants a document.
- **`reproducibility-package.zip`** is the version's
  [reproducibility package](publishing.md#the-reproducibility-package) without data (the
  runtime plan participants ran, the XLSForm and LimeSurvey exports, the replay kit).

The bundle is deterministic: building it again from the same version gives the same bytes,
so a copy on a registry can be compared with a fresh download. It carries no timestamp of
its own; the registry's upload record dates it.

## Filling in a registration form

A typical form (the OSF preregistration template, AsPredicted-style questions) asks for
things the bundle answers directly:

| Form section | Where it is |
|---|---|
| Study materials, instrument | `survey/survey.json` and its checksum; `summary.html` |
| Variables, measures | `codebook/codebook.md` (every variable with labels, codes, conditions) |
| Conditions, randomisation, allocation | `design/randomisation.md` |
| Exclusion criteria, missing data | `design/exclusions.md` (what is recorded; state your rules against it) |
| Sample size, stopping rule | the quotas in `design/randomisation.md`, if the design uses them |
| Analysis plan, hypotheses | yours to write: the platform knows the instrument, not the analysis |

Cite the version checksum as the instrument's identifier.

## Uploading to OSF

The publish dialog can put the bundle and the summary page straight into an OSF project:

1. On OSF, create the project that will hold the registration and note its id (the five
   characters after `osf.io/` in its URL) or copy the URL.
2. On OSF, under **Settings → Personal access tokens**, create a token with the
   **osf.full_write** scope.
3. In the publish dialog, under **Upload the preregistration to OSF**, enter the project id
   or URL and paste the token, then **Upload to OSF**.
4. On OSF, register the project when you are ready (the platform never registers it for
   you: a registration is frozen and public, and that is your decision).

What the platform does with the token: it sends it to OSF as the bearer header of this one
upload (to check who it is, look up the project, and upload the two files to the
project's OSF Storage, replacing files of the same name) and then forgets it. The token is
never stored, never logged, never echoed in a response or an error, and never put in a URL.
The audit log records that an upload happened (the project id, the file names, the OSF user
id and the version checksum), nothing else. Uploading needs the publish role (owner or
editor).

The same upload is available to scripts:
[preregUploadOsf](reference/api.md#preregUploadOsf) (`POST …/prereg-bundle/osf` with
`{"token": "…", "node": "ab3de"}`). OSF errors come back as **502** with OSF's reason (a
refused token, a project the token cannot see); nothing is uploaded in that case.

A host can point the upload at OSF's test servers with `OSP_OSF_API_URL`
(`https://api.test.osf.io/v2`) and `OSP_OSF_FILES_URL` (`https://files.test.osf.io/v1`).

## Verifying a bundle

From the folder that holds the extracted files:

```sh
sha256sum -c checksums.sha256        # Linux
shasum -a 256 -c checksums.sha256    # macOS
```

`survey/checksum.txt` says how the version checksum is computed, so it can be recomputed
from `survey.json` with any JSON library.

## Limits

- The summary is HTML, not PDF: print it from a browser.
- Only published versions have a bundle; a draft has no checksum yet.
- The upload goes to the project's OSF Storage root and replaces files of the same name
  (the names carry the version, so two versions never collide).
- Hypotheses and analysis plans are not in the bundle: the platform describes the
  instrument and the design, not the inference.
