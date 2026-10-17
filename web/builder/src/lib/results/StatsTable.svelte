<script lang="ts">
	import { statRows, type StatRow } from './model';
	import type { Category, Group } from './types';

	/**
	 * A unit's statistics, one column per group. Values come from the server; one it lists
	 * in `notAvailable` (undefined for the data) reads "not available", never 0.
	 */
	let { groups, categories, caption }: { groups: Group[]; categories?: Category[] | null; caption: string } =
		$props();

	const perGroup = $derived(groups.map((g) => new Map(statRows(g.stats, categories).map((r) => [r.key, r]))));
	const rows = $derived.by(() => {
		const out: StatRow[] = [];
		for (const m of perGroup) for (const r of m.values()) if (!out.some((o) => o.key === r.key)) out.push(r);
		return out;
	});
	const multi = $derived(groups.length > 1);
</script>

{#if rows.length}
	<!-- A scrolling region takes keyboard focus, so it can be scrolled without a mouse. -->
	<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
	<div class="scroll" role="region" aria-label="{caption}, statistics" tabindex="0">
		<table class="stats">
			<caption>Statistics</caption>
			<thead>
				<tr>
					<th scope="col">Statistic</th>
					{#each groups as g (g.key)}<th scope="col" class="num">{multi ? g.label : 'Value'}</th>{/each}
				</tr>
			</thead>
			<tbody>
				{#each rows as r (r.key)}
					<tr data-stat={r.key}>
						<th scope="row">{r.label}</th>
						{#each perGroup as m, i (groups[i].key)}
							{@const v = m.get(r.key)}
							<td class="num" class:na={v && !v.available}>{v ? v.value : '–'}</td>
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

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
	}
	tbody th {
		font-weight: var(--weight-normal);
	}
	.num {
		text-align: end;
		font-variant-numeric: tabular-nums;
	}
	.na {
		color: var(--color-text-muted);
		font-style: italic;
	}
</style>
