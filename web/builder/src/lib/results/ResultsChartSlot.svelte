<script lang="ts">
	import { fmtPct } from './model';
	import type { ResultsChartSpec, ResultsChartTheme } from './spec';

	/**
	 * Placeholder for V3's `<ResultsChart spec theme>` (same props): until the charts land
	 * it shows which chart was chosen and the numbers it will draw, as a table. V3's merge
	 * replaces this component's body (or the import in ResultCard) with the real chart.
	 */
	let { spec, theme }: { spec: ResultsChartSpec; theme: ResultsChartTheme } = $props();

	const values = $derived(spec.data.values);
	const grouped = $derived(new Set(values.map((v) => v.group)).size > 1);
</script>

<figure class="chart-slot" data-chart={spec.usermeta.chart} data-theme={theme}>
	<figcaption>
		<span class="chart-name">{spec.usermeta.chartLabel}</span>
		<span class="muted">Chart drawing is not available yet; these are its numbers.</span>
	</figcaption>
	<!-- A scrolling region takes keyboard focus, so it can be scrolled without a mouse. -->
	<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
	<div class="scroll" role="region" aria-label="{spec.description}, numbers" tabindex="0">
		<table>
			<thead>
				<tr>
					{#if grouped}<th scope="col">Group</th>{/if}
					<th scope="col">Category</th>
					<th scope="col" class="num">Count</th>
					<th scope="col" class="num">%</th>
				</tr>
			</thead>
			<tbody>
				{#each values as v, i (i)}
					<tr>
						{#if grouped}<td>{v.group}</td>{/if}
						<td>{v.category}</td>
						<td class="num">{v.count}</td>
						<td class="num">{fmtPct(v.pct)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</figure>

<style>
	.chart-slot {
		margin: 0;
		padding: var(--space-3);
		border: 1px dashed var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-sunken);
	}
	figcaption {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1) var(--space-2);
		margin-bottom: var(--space-2);
		font-size: var(--text-sm);
	}
	.chart-name {
		font-weight: var(--weight-bold);
	}
	.muted {
		color: var(--color-text-muted);
	}
	.scroll {
		max-height: 18rem;
		overflow: auto;
	}
	.scroll:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
	}
	th,
	td {
		padding: var(--space-1) var(--space-2);
		border-bottom: 1px solid var(--color-border);
		text-align: start;
	}
	.num {
		text-align: end;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
</style>
