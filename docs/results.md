# Results

**Results** in the top bar (or **Open results** in the palette) shows the responses to a
published survey: one card per question, each with counts, statistics, a chart and a table.
It needs the export role (owner or editor); a viewer sees a "no access" message. Counts are
of responses, not participants.

<figure markdown="span">
  ![The results page](assets/screenshots/results.png){ loading=lazy }
</figure>

## Filters

**Show filters** opens the filter bar. Press **Show results** to apply; **Reset filters**
clears it.

| Filter | What it does |
|---|---|
| **Survey version** | Tick the versions to include. None ticked means the latest version. Versions are combined only when a question's type and codes match; otherwise its card shows one facet per version, with a warning. |
| **Responses** | *Complete only* (the outcome was `complete`) or *All submitted*. |
| **Submitted from**, **Submitted to (inclusive)** | A date range. |
| **Condition** | Keep responses assigned to given levels of a condition. |
| **Answer filters** | Keep responses that gave given answers to a single choice, multiple choice or grid row question (up to 20). |
| **Split by** | Compare groups: by a question (single choice, grid row) or by a condition. Each group gets its own *n*, and numeric cards share bin edges across groups. |
| **Denominator** | *Answered* (default) or *Shown (answered + unanswered)*: what percentages are out of. |
| **Show 95 % intervals** | Wilson intervals for proportions, *t* intervals for means. |
| **Labels in** | Which language's labels to show. |

The active filters are shown in words above the cards, with the number of responses.

## Cards

Each card shows the question's **response states** (answered, unanswered, irrelevant, not
reached, not in version, unrecorded, invalid), the **statistics** that make sense for its
type (n, mode, median, mean, standard deviation, quartiles, min and max for numbers;
earliest and latest for dates; mean number of options for multiple choice; mean length for
text), and "not available" where a statistic is undefined, such as a standard deviation
with fewer than two answers.

**Show as** switches between the **Chart** and the accessible **Table view**. The **Chart**
menu offers, by type:

| Type | Charts |
|---|---|
| Single choice | Bars, Sorted bars, Donut |
| Multiple choice | % of respondents, Counts, Dot plot. Percentages are of answering respondents, so they can sum to more than 100. |
| Numbers and sliders | Histogram (or Frequency bars for few distinct values), Box plot, Cumulative distribution |
| Date | Counts per period, with **Per** Day, Week, Month or Year |
| Grid | Diverging stacked bars (neutral centred), 100 % stacked bars, Heatmap; or Grouped bars and Heatmap for unordered columns |
| Text | Response states, and **Show answers** for the verbatim answers in pages (reading them is audited) |

With a split, **Groups** chooses *Grouped bars*, *100 % stacked bars* or *Small
multiples*. Charts are drawn with Vega-Lite as SVG, follow the builder's light or dark
theme, and carry titles and descriptions for screen readers.

## Exporting figures

Every card has an **Export** menu: **PNG image…**, **SVG image…**, **CSV of the numbers…**
or **Vega-Lite spec and manifest…**. The export dialog offers:

- **Final width**: *Single column, 85 mm*, *Double column, 180 mm*, or custom, with the
  real pixel size shown; **PNG resolution** 150, 300 or 600 DPI. SVGs are sized in
  millimetres and PNGs carry their DPI, so a figure drops into a manuscript at the right
  size.
- **Small counts: Hide counts below k**, off by default, for publication where small cells
  could identify someone. Hidden cells show "n<5" and no count or share anywhere in the
  figure, the CSV or the spec. Cumulative and box plots are drawn from every answer, so
  suppression cannot hide small cells in them; the dialog says so.
- A **Caption**, with **Use the automatic caption** as a start, drawn under the figure.

Figures use a print theme: white background, the Okabe-Ito colour-blind-safe palette and
ordered palettes for scales. **Export all** downloads a ZIP with every card's SVG, PNG, CSV
and spec plus one manifest.

Every query and every figure export is recorded in the audit log with the filters used and
the versions, never with answer values.

## Data exports

The results page aggregates; it never shows raw rows except the audited text pages. The raw
data, with a codebook, comes from the response export
([Publishing and exports](publishing.md#response-exports)).
