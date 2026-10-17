// Results charts (task V3): <ResultsChart {spec} {theme} {title} {description} /> draws a
// spec from buildSpec(card, chartChoice, opts); chartsFor(card) is the per-card chart menu.
// Vega is loaded by ResultsChart on first use, so importing this module stays light.
export { default as ResultsChart } from './ResultsChart.svelte';
export { buildSpec, defaultSpec, VEGA_LITE_SCHEMA } from './spec';
export { CHART_LABELS, chartsFor, isChart, isSplit, splitsFor } from './menu';
export { EXPORT_TEXT, LIGHT_TOKENS, OKABE_ITO, likertPalette, readTokens, themeConfig } from './theme';
export * from './types';
