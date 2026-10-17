<script lang="ts">
	import { buildSpec, CHART_LABELS, chartsFor, isChart, ResultsChart, splitsFor } from './charts';
	import type { MenuChoice, SplitLayout, ThemeTokens } from './charts/types';
	import ExportMenu from './export/ExportMenu.svelte';
	import { captionFor } from './export/run';
	import { cardSections, DATE_UNITS, stateRows, TYPE_NAMES } from './model';
	import type { ResultsController } from './results.svelte';
	import ResultsTable from './ResultsTable.svelte';
	import StatsTable from './StatsTable.svelte';
	import TextAnswers from './TextAnswers.svelte';
	import type { Card, StateCounts } from './types';
	import type { Snippet } from 'svelte';

	/**
	 * One question's results (tasks V2, V4): its text and variable, warnings, response-state
	 * counts, a chart menu with the charts that suit its type (`chartsFor`, the one source of
	 * truth), split layout and date period where they apply, the Vega-Lite chart (or its
	 * Table view), statistics and the Export menu. Versions that do not combine show as
	 * per-version facets; a grid has one chart for all rows and one table per row.
	 * Presenting (task V6): only the title, the chart (or table) and its caption.
	 */
	let {
		card,
		controller,
		tokens,
		tools,
		presenting = false,
		pulse = false
	}: {
		card: Card;
		controller: ResultsController;
		/** The design tokens to draw with (the app's, or the page theme's: V6); a change rebuilds the spec. */
		tokens: ThemeTokens;
		/** The page's per-card tools (move, hide: task V5b), beside the title. */
		tools?: Snippet;
		/** Presentation mode: no controls, meta, states or statistics; the figure's caption under it. */
		presenting?: boolean;
		/** The card's numbers just changed in a live refresh (task LV3): a short outline pulse. */
		pulse?: boolean;
	} = $props();

	const LAYOUT_LABELS: Record<SplitLayout, string> = {
		grouped: 'Grouped bars',
		stacked: '100 % stacked bars',
		multiples: 'Small multiples'
	};
	const UNIT_LABELS: Record<string, string> = { month: 'Month', day: 'Day', week: 'Week', year: 'Year' };

	const uid = $props.id();
	const denominator = $derived(controller.response?.denominator ?? controller.applied.denominator);
	const intervals = $derived(controller.applied.intervals);
	const offered = $derived(chartsFor(card));
	const menu = $derived(offered.choices);
	const chosen = $derived(controller.charts.get(card.question));
	const chart = $derived<MenuChoice>(chosen && menu.some((o) => o.id === chosen) ? chosen : offered.default);
	const layouts = $derived(isChart(chart) ? splitsFor(card, chart) : []);
	const layout = $derived.by(() => {
		const l = controller.charts.layout(card.question);
		return l && layouts.includes(l) ? l : layouts[0];
	});
	const view = $derived(controller.charts.view(card.question));
	const facets = $derived(cardSections(card));
	const showTable = $derived(view === 'table' || chart === 'table');
	const title = $derived(card.label || card.name);
	const versions = $derived(
		`${card.versionsUsed.length === 1 ? 'Version' : 'Versions'} ${card.versionsUsed.join(', ')}`
	);
	const description = $derived(
		isChart(chart)
			? `${CHART_LABELS[chart]}${layout && layouts.length > 1 ? `, ${LAYOUT_LABELS[layout].toLowerCase()}` : ''} of ${title}. The Table view has the exact numbers.`
			: ''
	);
	const spec = $derived.by(() => {
		if (showTable || !isChart(chart) || card.type === 'note') return null;
		try {
			// A plain copy: Vega clones the spec, and $state proxies cannot be cloned.
			return buildSpec($state.snapshot(card) as Card, chart, { theme: 'app', tokens, split: layout, intervals, denominator, description });
		} catch {
			return null;
		}
	});
	/** Presenting: the figure's caption (as edited, or written from the question, filters and n). */
	const caption = $derived(presenting ? captionFor(card, { filters: controller.activeFilters }, controller.exports, 0).text : '');
</script>

{#snippet states(s: StateCounts, label: string)}
	<dl class="states" aria-label={label}>
		{#each stateRows(s) as r (r.key)}
			<div class="state" data-state={r.key} class:zero={r.count === 0}>
				<dt>{r.label}</dt>
				<dd>{r.count}</dd>
			</div>
		{/each}
	</dl>
{/snippet}

<article class="result-card" class:presenting class:pulse id="result-{card.question}" aria-labelledby="{uid}-h" data-type={card.type} data-pulse={pulse || undefined}>
	<header>
		<div class="title-row">
			<!-- Presenting, the page heading is the h1, so cards are h2 (heading order). -->
			<svelte:element this={presenting ? 'h2' : 'h3'} id="{uid}-h" class="card-title">{title}</svelte:element>
			{#if tools && !presenting}<div class="tools">{@render tools()}</div>{/if}
		</div>
		{#if !presenting}
			<p class="meta">
				<code>{card.name}</code>
				<span>{TYPE_NAMES[card.type]}</span>
				<span>{versions}</span>
			</p>
		{/if}
	</header>

	{#if presenting}
		{#if spec}
			<div class="chart" data-chart={chart} data-layout={layouts.length ? layout : undefined}>
				<ResultsChart {spec} theme="app" {tokens} {title} {description} />
			</div>
		{:else if card.type !== 'text'}
			{#each facets as f (f.facet ?? 'all')}
				{#each f.sections as s (s.key)}
					{@const name = [title, f.facet !== null ? `version ${f.facet}` : null, s.heading].filter(Boolean).join(', ')}
					<ResultsTable unit={s.unit} type={card.type} {denominator} caption={name} />
				{/each}
			{/each}
		{/if}
		{#if caption}<p class="caption" data-testid="card-caption">{caption}</p>{/if}
	{:else}
	{#if card.warnings?.length}
		<ul class="warnings" aria-label="Warnings for {card.label || card.name}">
			{#each card.warnings as w, i (i)}
				<li data-code={w.code}>{w.message}</li>
			{/each}
		</ul>
	{/if}

	{#if card.states}
		{@render states(card.states, `Response states for ${card.label || card.name}`)}
	{/if}

	<div class="controls">
		{#if menu.length > 1}
			<label class="field">
				<span>Chart</span>
				<select
					value={chart}
					onchange={(e) =>
						controller.chooseChart(card.question, (e.currentTarget as HTMLSelectElement).value as MenuChoice)}
				>
					{#each menu as o (o.id)}<option value={o.id}>{o.label}</option>{/each}
				</select>
			</label>
		{/if}
		{#if layouts.length > 1 && !showTable}
			<label class="field">
				<span>Groups</span>
				<select
					value={layout}
					onchange={(e) =>
						controller.charts.setLayout(card.question, (e.currentTarget as HTMLSelectElement).value as SplitLayout)}
				>
					{#each layouts as l (l)}<option value={l}>{LAYOUT_LABELS[l]}</option>{/each}
				</select>
			</label>
		{/if}
		{#if offered.binUnits}
			<label class="field">
				<span>Per</span>
				<select
					value={controller.charts.unit(card.question)}
					onchange={(e) => controller.chooseUnit(card.question, (e.currentTarget as HTMLSelectElement).value)}
				>
					{#each DATE_UNITS as u (u)}<option value={u}>{UNIT_LABELS[u]}</option>{/each}
				</select>
			</label>
		{/if}
		{#if card.type !== 'text' && chart !== 'table'}
			<div class="views" role="group" aria-label="Show as">
				<button
					type="button"
					aria-pressed={view === 'chart'}
					onclick={() => controller.charts.setView(card.question, 'chart')}>Chart</button
				>
				<button
					type="button"
					aria-pressed={view === 'table'}
					onclick={() => controller.charts.setView(card.question, 'table')}>Table view</button
				>
			</div>
		{/if}
		<div class="export"><ExportMenu {card} {controller} /></div>
	</div>

	{#if spec}
		<div class="chart" data-chart={chart} data-layout={layouts.length ? layout : undefined}>
			<ResultsChart {spec} theme="app" {tokens} {title} {description} />
		</div>
	{/if}

	{#each facets as f (f.facet ?? 'all')}
		<div class="facet" data-facet={f.facet ?? undefined}>
			{#if f.facet !== null}<h4>Version {f.facet}</h4>{/if}
			{#each f.sections as s (s.key)}
				{@const name = [card.label || card.name, f.facet !== null ? `version ${f.facet}` : null, s.heading]
					.filter(Boolean)
					.join(', ')}
				<section class="section" aria-label={s.heading ?? undefined}>
					{#if s.heading}<h4 class="row-heading">{s.heading}</h4>{/if}
					{#if s.states && (s.heading || f.facet !== null)}
						{@render states(s.states, `Response states for ${name}`)}
					{/if}
					{#if card.type !== 'text' && (showTable || !spec)}
						<ResultsTable unit={s.unit} type={card.type} {denominator} caption={name} />
					{/if}
					<StatsTable groups={s.unit.groups} categories={s.unit.categories} caption={name} />
				</section>
			{/each}
		</div>
	{/each}

	{#if card.type === 'text'}
		<TextAnswers
			question={card.question}
			label={card.label || card.name}
			source={controller.source}
			filters={controller.applied}
			current={controller.response?.watermark ?? null}
		/>
	{/if}
	{/if}
</article>

<style>
	.result-card {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		min-width: 0;
		padding: var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}
	header {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.card-title {
		margin: 0;
		font-size: var(--text-md);
		overflow-wrap: anywhere;
	}
	.title-row {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-2);
		min-width: 0;
	}
	.title-row .card-title {
		flex: 1 1 auto;
		min-width: 0;
	}
	.tools {
		display: flex;
		flex: 0 0 auto;
		gap: var(--space-1);
	}
	h4 {
		margin: 0;
		font-size: var(--text-sm);
	}
	.meta {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1) var(--space-3);
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	code {
		font-family: var(--font-mono);
	}
	.warnings {
		margin: 0;
		padding: var(--space-2) var(--space-3) var(--space-2) var(--space-5);
		border: 1px solid var(--color-border-strong);
		border-inline-start: 4px solid var(--color-warning);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		font-size: var(--text-sm);
	}
	.states {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(9rem, 1fr));
		gap: var(--space-1) var(--space-3);
		margin: 0;
		font-size: var(--text-xs);
	}
	.state {
		display: flex;
		justify-content: space-between;
		gap: var(--space-2);
		padding-block: 2px;
		border-bottom: 1px solid var(--color-border);
	}
	.state dt {
		color: var(--color-text-muted);
	}
	.state dd {
		margin: 0;
		font-weight: var(--weight-bold);
		font-variant-numeric: tabular-nums;
	}
	.state.zero dd {
		font-weight: var(--weight-normal);
	}
	.controls {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: var(--space-2) var(--space-3);
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
		max-width: 100%;
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}
	select {
		max-width: 100%;
		min-height: 2.75rem;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-weight: var(--weight-normal);
	}
	.views {
		display: inline-flex;
		padding: 2px;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-sunken);
	}
	.views button {
		min-height: 2.5rem;
		padding: 0 var(--space-3);
		border: 0;
		border-radius: var(--radius-sm);
		background: transparent;
		color: var(--color-text-muted);
		font: inherit;
		font-size: var(--text-sm);
		cursor: pointer;
	}
	.views button[aria-pressed='true'] {
		background: var(--color-surface-raised);
		color: var(--color-text);
		font-weight: var(--weight-bold);
	}
	.export {
		margin-inline-start: auto;
	}
	.chart {
		min-width: 0;
	}
	select:focus-visible,
	.views button:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}
	.facet,
	.section {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		min-width: 0;
	}
	.facet[data-facet] {
		padding-top: var(--space-2);
		border-top: 1px solid var(--color-border);
	}
	.caption {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.result-card.presenting {
		break-inside: avoid;
	}
	/* A live refresh changed this card's numbers (LV3): a short outline pulse, none under reduced motion. */
	.result-card.pulse {
		animation: live-pulse 1.2s ease-out 1;
	}
	@keyframes live-pulse {
		0% {
			outline: 2px solid var(--color-accent);
			outline-offset: 2px;
		}
		100% {
			outline: 2px solid transparent;
			outline-offset: 2px;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.result-card.pulse {
			animation: none;
		}
	}
</style>
