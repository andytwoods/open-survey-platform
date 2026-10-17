MIT# Open Survey Platform — Project Overview and Design Brief

**Status:** Draft for independent LLM scrutiny and subsequent implementation planning  
**Date:** 16 October 2026  
**Working name:** Open Survey Platform (placeholder; not a branding decision)

## 1. Purpose and motivation

Build an **open-source, browser-based, GUI-first survey authoring and delivery platform** focused on academic research. The motivation is rising Qualtrics licensing costs and the desire for a capable, portable, self-hostable alternative without vendor lock-in.

The ambition is to match most of the **core Qualtrics survey builder and research survey runtime**, not its entire enterprise experience-management suite. The product should also improve on conventional survey software through reproducibility, debugging, automated testing, experimental-design tooling, extensibility and open interchange.

This document captures agreed requirements, proposed implementation directions and unresolved decisions. **Do not treat proposed technologies, schedules, completeness percentages or interchange compatibility as verified facts or fixed commitments.**

## 2. Firm product decisions

1. **GUI first.** Researchers create and manage surveys in a rich web-based visual editor; programming is not required.
2. **Optional text editing.** A survey's structured definition can also be inspected and edited as text. Changes in either mode must be reflected consistently in the other, with validation and clear error handling.
3. **Entirely web-based user experience.** Researchers should log into a hosted/self-hosted instance through a browser, build surveys, publish them and collect responses without installing desktop software or R locally.
4. **Open source and self-hostable.** Licensing and dependency choices must permit an openly distributed project. Outbound licence: **MIT** (decided 16 October 2026). Dependencies must be MIT-compatible; see `review.md` §12.2.
5. **Lightweight stack, no React preference.** Prefer a simpler frontend over React and avoid heavyweight client-side frameworks unless clearly justified.
6. **Framework independent.** The survey specification, renderer and essential logic must not depend on Django. Provide optional, straightforward ways to integrate with Django and other applications.
7. **Open survey representation.** Prefer an established, platform-independent specification over inventing a closed proprietary format. Survey portability, versioning and export are central goals.
8. **Qualtrics-like research capability.** Focus on questions, blocks, logic, randomisation, flow, response collection and research-oriented tooling.
9. **No enterprise-suite scope creep.** See explicit exclusions below.

## 3. Target users and workflows

Primary users are university researchers, research teams and institutional survey administrators. Secondary users include developers embedding surveys in research applications.

Core workflow:

1. Researcher logs into a browser-based builder.
2. Creates or imports a survey; adds pages, blocks and questions visually.
3. Configures validation, branching, piped text, embedded data, randomisation and/or an experimental design.
4. Optionally views or edits the structured survey definition in a text editor.
5. Previews the survey, inspects the logic trace and runs automated simulated-participant tests.
6. Publishes an immutable survey version and obtains a participant-facing URL or embeddable integration.
7. Collects responses and exports data and research documentation.
8. Exports the survey to an open format or supported third-party platform, with explicit warnings for unsupported conversions.

## 4. Functional scope

### 4.1 Visual survey builder

- Browser-based WYSIWYG-style question, page and block editing.
- Drag-and-drop ordering, question properties, required/optional settings, answer choices and validation rules.
- Major Qualtrics-like question types: single/multiple choice, text, number, matrix, Likert scales, sliders, rankings and other common research formats.
- Visual survey flow: branching, display/skip logic, piped text, embedded data, block randomisation, quotas and screening.
- Preview/test modes and responsive/mobile presentation.
- Survey themes, multilingual survey content and save/resume.
- Optional textual editor for the same underlying structured model, with round-trip validation.

### 4.2 Survey runtime and data

- Framework-independent participant-facing survey renderer, preferably lightweight JavaScript.
- Server-side validation and authoritative execution of sensitive logic where needed; do not trust client-only validation.
- Survey publishing and immutable published versions; each response records the survey version used.
- Response storage and exports, initially CSV and JSON, with labelled/codebook-oriented exports for statistical tools where feasible.
- Basic researcher accounts, permissions and administration required for a multi-user hosted system.
- Consent and privacy features appropriate to academic research, subject to detailed design and institutional review.

### 4.3 Six agreed differentiating features

**A. Survey logic debugger**
- Step through a simulated survey session.
- Inspect variable values, condition evaluation, branch decisions, randomisation and question visibility.
- Reproduce runs using deterministic seeds and captured test inputs.

**B. Automated survey testing**
- Generate simulated participant paths and response scenarios.
- Detect unreachable questions, contradictory conditions, broken references, missing mandatory paths and incomplete termination logic.
- Produce path/branch coverage reports. Do not claim exhaustive coverage unless it is mathematically established.

**C. Visual experimental design**
- GUI for between-subject and within-subject experiments, factorial designs, counterbalancing and Latin-square-like ordering.
- Random allocation, optionally balanced assignment, and reproducible recording of condition/order assignments.
- Separate deterministic per-participant randomisation from any aggregate balancing that requires server-side state.

**D. Reproducibility package export**
- Export exact versioned survey definition, question order/flow, variable dictionary, value labels, randomisation settings, scoring metadata and human-readable methods documentation.
- Include relevant provenance, format versions, checksums and dependency/plugin information.
- Avoid including personally identifiable response data by default.

**E. Reusable question and instrument library**
- Shared and private question/block templates and validated instrument definitions.
- Stable identifiers, version pinning, citations, provenance, scoring rules and explicit licensing/permissions metadata.
- Respect copyright and licensing restrictions on third-party instruments.

**F. Custom question plugin system**
- Allow third-party developers to supply custom question renderers, editing controls, validation, scoring and data schemas.
- Keep the core small and establish plugin interfaces early, even if the public ecosystem comes later.
- Define plugin versioning, security boundaries, permissions and compatibility rules.

## 5. Explicitly out of scope for the initial product

These four areas were expressly removed from the roadmap:

1. **Email distribution and reminders.**
2. **Panels and participant management/recruitment.**
3. **Enterprise dashboards and analytics.**
4. **AI-powered analysis and enterprise integrations.**

A per-question results page with exportable figures for the researcher's own survey is in scope (decided 17 Oct 2026, `results-viewer.md`); item 3 means cross-survey BI dashboards.

Do not quietly reintroduce these as dependencies or milestones. Basic researcher login, response collection, and simple operational views are not equivalent to participant panels or enterprise analytics.

## 6. Interoperability and survey specification

### 6.1 Principle

The GUI is the primary authoring interface; a **canonical structured survey model** underpins the GUI, optional text editor, renderer, debugger, test runner and converters. The canonical representation should be open, versioned and documented.

### 6.2 Standards and formats to evaluate

- **Formspec**: candidate canonical or runtime-oriented form specification; evaluate whether it can represent advanced research flow and randomisation without awkward extensions.
- **DDI Lifecycle**: candidate source of concepts for study/question metadata, provenance and academic interoperability, rather than necessarily the live runtime format.
- **XLSForm**: important open import/export target.
- **queXML**: potential questionnaire exchange/documentation target.
- **Qualtrics QSF**: high-priority import/export target for migration.
- **LimeSurvey LSS**: high-priority import/export target.
- **Markdown/YAML**: potential human-readable editing and export view, not necessarily the canonical runtime format.

**No standard has yet been selected.** Before selection, evaluate real complex survey examples, schema expressiveness, licensing, maintenance, compatibility, accessibility and conversion loss.

### 6.3 Conversion rules

- Preserve semantics wherever possible, not merely visible question text.
- Maintain stable question/variable identifiers where possible.
- Warn clearly when a target format cannot represent a feature; never silently discard branching, randomisation or scoring semantics.
- Produce machine-readable conversion diagnostics and human-readable warnings.
- Treat round-trip fidelity as a measurable test criterion, not a blanket promise.

## 7. Proposed technical architecture (provisional)

Separate concerns into independently testable packages/services:

```text
survey-spec/       Canonical model, schemas, parser, validators, migrations
survey-engine/     Branching, piping, randomisation, flow, scoring rules
survey-renderer/   Small embeddable browser runtime, framework independent
survey-builder/    GUI-first visual editor and optional text editing
survey-server/     Hosting, auth, publish/version, responses, REST API
survey-convert/    QSF, LSS, XLSForm, queXML and other adapters
survey-test/       Debugger, simulation, coverage and test fixtures
survey-plugins/    Extension interfaces and compatibility machinery
```

**Candidate technology choices, not settled decisions:**

- Server: Python with FastAPI or another lightweight HTTP framework.
- GUI: **entirely Svelte** (decided 16 October 2026): a static SvelteKit SPA talking to the server only through an OpenAPI contract, so the UI is not tied to a backend framework. See `review.md` §9 Q2.
- Participant runtime: lightweight vanilla JavaScript; no React dependency.
- Database: SQLite for local/small installations, PostgreSQL for production multi-user deployment.
- Specification validation: JSON Schema where appropriate, plus semantic validation.
- Django integration: optional Python client, REST API and/or embed hooks; **Django is not a core dependency**.

**Architecture risks to scrutinise:** a complex GUI may exceed what htmx/Alpine comfortably support; editor/server round trips can introduce latency; arbitrary third-party plugins create security risks; offline and save/resume semantics require deliberate design; data protection and accessibility must be first-class, not late additions.

## 8. Non-functional requirements

- Open-source licence compatible with dependencies, self-hosting and potential commercial hosting.
- Secure authentication and authorisation; strict separation of researchers' surveys and response data.
- GDPR-supporting privacy controls, retention/deletion/export mechanisms, minimised data collection, auditability and clear consent practices.
- WCAG-oriented accessible builder and participant runtime, including keyboard, screen-reader and mobile support.
- Versioned schemas and explicit migration strategy.
- Deterministic, testable survey engine; same semantics in preview, production, debugger and automated tests.
- Reliable persistence, backups, error reporting, performance testing and deployment documentation.
- Strong automated unit, integration, browser and compatibility tests.
- Documented APIs and extension contracts.

## 9. Proposed phased roadmap

These are planning phases, **not firm time or cost commitments**. Cross-cutting testing, accessibility and security start in Phase 1.

| Phase | Main deliverable | Indicative focused effort |
|---|---|---|
| 1. Vertical slice / core | Visual editor, common questions, canonical spec, renderer, basic branching, publish, response storage/export, versioning | 6–10 weeks |
| 2. Advanced survey logic | Survey flow, piped text, embedded data, validation, randomisation, quotas, multilingual, save/resume | 6–10 weeks |
| 3. Research design and QA | Visual experimental design, debugger, deterministic simulation, path coverage | 6–10 weeks |
| 4. Portability and reproducibility | QSF/LSS/XLSForm adapters, optional text editing maturity, research/codebook package | 6–12 weeks |
| 5. Extensibility | Reusable instrument library, plugin API, custom questions, scoring | 6–10 weeks |
| 6. Production hardening | Security/accessibility review, migration fidelity, scalability, backup/recovery, documentation and pilots | 8–12 weeks |

An earlier discussion sketched roughly **12–15 months for an experienced full-time developer with overlapping phases**, but this is highly uncertain, may be optimistic for a production-grade platform, and should be independently re-estimated after a technical spike.

### Recommended first vertical slice

A researcher should be able to:

1. Open the hosted builder in a browser.
2. Create consent and demographics questions plus a two-condition experiment visually.
3. Define simple conditional logic and seeded random assignment.
4. Preview and debug a sample participant path.
5. Publish a versioned survey and collect a test response.
6. Export the survey definition, response data and a basic codebook.
7. Embed the participant survey in an unrelated application without Django coupling.

## 10. Legal and intellectual-property considerations

The project aims to **independently reproduce survey functionality**, not copy Qualtrics source code, proprietary assets, documentation or distinctive protected design. Similar functionality is generally a different issue from copying protected expression, but this is **not a guarantee against litigation**. Review patents, trade marks, licences, third-party instrument rights, contractual restrictions and applicable jurisdictions with qualified counsel before release. For QSF compatibility, review the format and applicable terms; avoid assuming that any particular reverse-engineering technique is permissible.

The earlier discussion referenced *SAS Institute v World Programming* as relevant to the distinction between functionality and copyright-protected expression. That precedent should be checked carefully rather than treated as a blanket legal safe harbour.

## 11. Questions for independent LLM scrutiny

Please challenge this plan rather than simply endorse it. In particular:

1. Is **Formspec** sufficiently expressive and mature for complex research surveys, or should another open model be canonical? Supply concrete evidence and alternatives.
2. Can a genuinely rich visual editor be built maintainably with htmx/Alpine/SortableJS, or would a small framework-neutral web-component approach be better?
3. Which features are already present in existing permissively licensed open-source projects and could be reused without bringing in React or Django dependencies?
4. How should survey flow, quotas, deterministic randomisation and concurrent balanced allocation be modelled and tested?
5. What are the hardest QSF and LSS interoperability edge cases? How should conversion loss be measured?
6. How should the survey engine and renderer share semantics without duplicating business rules across Python and JavaScript?
7. What plugin sandboxing and permissions are necessary for third-party question components?
8. Which accessibility, privacy, security, research ethics and data-governance requirements must be addressed before a pilot?
9. Are the proposed phases, estimates and priorities realistic for a small team or solo developer using AI-assisted development?
10. What is the **smallest compelling MVP**, and what should explicitly wait until after an academic pilot?

## 12. Requested outputs from the reviewing LLM

Produce:

1. A critical feasibility review, distinguishing verified facts, assumptions and major risks.
2. A recommendation for the canonical open survey specification, including a worked complex survey example and a comparison matrix.
3. A lean architecture proposal with module boundaries and API contracts.
4. A prioritised MVP backlog with acceptance criteria and non-goals.
5. A testing and security strategy, especially for logic correctness and randomisation.
6. A revised delivery estimate with dependencies, uncertainties and alternative implementation strategies.
7. A short list of technical spikes/prototypes that should precede substantial implementation.

**Do not begin building the complete application solely from this document.** Resolve the high-impact architecture and format questions first, then implement a tested vertical slice.
