<script lang="ts">
	import { cardSections, chartMenu, effectiveChart, stateRows, TYPE_NAMES } from './model';
	import type { ResultsController } from './results.svelte';
	import ResultsChartSlot from './ResultsChartSlot.svelte';
	import ResultsTable from './ResultsTable.svelte';
	import { chartSpec, type ResultsChartTheme } from './spec';
	import StatsTable from './StatsTable.svelte';
	import TextAnswers from './TextAnswers.svelte';
	import type { Card, StateCounts } from './types';

	/**
	 * One question's results (task V2): its text and variable, warnings, response-state
	 * counts, a chart menu that offers only charts that suit its type, the chart (or its
	 * Table view), and statistics. Versions that do not combine show as per-version facets;
	 * a grid shows one section per row (each row has its own n); text shows its answers.
	 */
	let {
		card,
		controller,
		theme,
		split
	}: { card: Card; controller: ResultsController; theme: ResultsChartTheme; split: boolean } = $props();

	const uid = $props.id();
	const denominator = $derived(controller.response?.denominator ?? controller.applied.denominator);
	const menu = $derived(chartMenu(card, split));
	const chart = $derived(effectiveChart(menu, controller.charts.get(card.question)));
	const chartLabel = $derived(menu.find((o) => o.id === chart)?.label ?? '');
	const view = $derived(controller.charts.view(card.question));
	const facets = $derived(cardSections(card));
	const showTable = $derived(view === 'table' || chart === 'table');
	const versions = $derived(
		`${card.versionsUsed.length === 1 ? 'Version' : 'Versions'} ${card.versionsUsed.join(', ')}`
	);
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

<article class="result-card" id="result-{card.question}" aria-labelledby="{uid}-h" data-type={card.type}>
	<header>
		<h3 id="{uid}-h">{card.label || card.name}</h3>
		<p class="meta">
			<code>{card.name}</code>
			<span>{TYPE_NAMES[card.type]}</span>
			<span>{versions}</span>
		</p>
	</header>

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

	{#if menu.length}
		<div class="controls">
			<label class="field">
				<span>Chart</span>
				<select
					value={chart}
					onchange={(e) => controller.chooseChart(card.question, (e.currentTarget as HTMLSelectElement).value)}
				>
					{#each menu as o (o.id)}<option value={o.id}>{o.label}</option>{/each}
				</select>
			</label>
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
					{#if card.type !== 'text'}
						{#if showTable || !chart}
							<ResultsTable unit={s.unit} type={card.type} {denominator} caption={name} />
						{:else}
							<ResultsChartSlot
								{theme}
								spec={chartSpec({
									question: card.question,
									label: name,
									type: card.type,
									chart,
									chartLabel,
									denominator,
									unit: s.unit
								})}
							/>
						{/if}
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
		/>
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
	h3 {
		margin: 0;
		font-size: var(--text-md);
		overflow-wrap: anywhere;
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
</style>
