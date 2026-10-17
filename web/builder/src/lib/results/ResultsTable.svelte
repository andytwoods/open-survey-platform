<script lang="ts">
	import { categoryHeading, fmtPct, pctHeading, type Denominator } from './model';
	import type { CardType, ResultUnit } from './types';

	/**
	 * A card's Table view (task V2): the exact numbers behind its chart, one row per
	 * category, bin or period, a count and a percentage column per group, and each group's
	 * denominator n. It is also the accessible alternative to the chart.
	 */
	let {
		unit,
		type,
		denominator,
		caption
	}: { unit: ResultUnit; type: CardType; denominator: Denominator; caption: string } = $props();

	const groups = $derived(unit.groups);
	const multi = $derived(groups.length > 1);
	const keys = $derived(groups[0]?.cells.map((c) => ({ key: c.key, label: c.label })) ?? []);
	const lookup = $derived(groups.map((g) => new Map(g.cells.map((c) => [c.key, c]))));
	const pctName = $derived(pctHeading(type, denominator));
</script>

<!-- A scrolling region takes keyboard focus, so it can be scrolled without a mouse. -->
<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<div class="scroll" role="region" aria-label="{caption}, table" tabindex="0">
	<table class="results-table">
		<caption>{caption}</caption>
		<thead>
			<tr>
				<th scope="col">{categoryHeading(unit)}</th>
				{#each groups as g (g.key)}
					<th scope="col" class="num">{multi ? `${g.label}: count` : 'Count'}</th>
					<th scope="col" class="num">{multi ? `${g.label}: %` : pctName}</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each keys as k (k.key)}
				<tr>
					<th scope="row">{k.label}</th>
					{#each groups as g, gi (g.key)}
						{@const c = lookup[gi].get(k.key)}
						<td class="num">{c ? c.count : 0}</td>
						<td class="num">{fmtPct(c?.pct)}</td>
					{/each}
				</tr>
			{:else}
				<tr><td colspan={1 + groups.length * 2} class="empty">No answers to count.</td></tr>
			{/each}
		</tbody>
		<tfoot>
			<tr>
				<th scope="row">n ({denominator})</th>
				{#each groups as g (g.key)}
					<td class="num" data-testid="group-n">{g.n}</td>
					<td></td>
				{/each}
			</tr>
		</tfoot>
	</table>
</div>

<style>
	.scroll {
		max-width: 100%;
		overflow-x: auto;
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
	caption {
		padding-bottom: var(--space-1);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		text-align: start;
	}
	th,
	td {
		padding: var(--space-1) var(--space-2);
		border-bottom: 1px solid var(--color-border);
		text-align: start;
		vertical-align: top;
	}
	thead th {
		font-weight: var(--weight-bold);
	}
	tbody th {
		font-weight: var(--weight-normal);
	}
	tfoot th,
	tfoot td {
		border-bottom: 0;
		font-weight: var(--weight-bold);
	}
	.num {
		text-align: end;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.empty {
		color: var(--color-text-muted);
	}
</style>
