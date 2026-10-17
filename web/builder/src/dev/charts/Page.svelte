<script lang="ts">
	import { theme as appTheme } from '@osp/ui-components';
	import { onMount } from 'svelte';
	import ResultsChart from '#lib/results/charts/ResultsChart.svelte';
	import { entryOptions, galleryEntries } from '#lib/results/charts/gallery.js';
	import { buildSpec } from '#lib/results/charts/spec.js';
	import { readTokens } from '#lib/results/charts/theme.js';
	import type { ChartTheme } from '#lib/results/charts/types.js';

	// Developer gallery of every results chart, drawn from the fixture cards
	// (src/lib/results/charts/fixtures.ts). ?theme=export shows the export theme;
	// ?only=<id prefix> narrows the list. Checked by e2e/charts.spec.ts (snapshots, axe).
	onMount(() => appTheme.init());

	const params = new URLSearchParams(location.search);
	const chartTheme: ChartTheme = params.get('theme') === 'export' ? 'export' : 'app';
	const only = params.get('only');
	const entries = galleryEntries().filter((e) => !only || e.id.startsWith(only));

	// App theme colours follow light/dark: rebuilt when the resolved theme changes.
	let tokens = $state(readTokens());
	$effect(() => {
		void appTheme.resolved;
		tokens = readTokens();
	});

	let ready = $state(0);
	const total = entries.length;
</script>

<main class="gallery" class:export={chartTheme === 'export'} data-ready={ready >= total ? 'true' : 'false'}>
	<h1>Results charts</h1>
	<p class="intro">
		{total} charts, {chartTheme === 'export' ? 'export theme (white, Okabe-Ito)' : 'app theme (design tokens)'}.
		<a href="/dev/charts">App theme</a> · <a href="/dev/charts?theme=export">Export theme</a>
	</p>
	<ul class="grid">
		{#each entries as e (e.id)}
			{@const opts = entryOptions(e, { theme: chartTheme, tokens, width: chartTheme === 'export' ? 360 : undefined })}
			<li data-chart={e.id}>
				<h2>{e.title}</h2>
				<p class="meta">{e.card.type} · {e.choice}{e.split ? ` · ${e.split}` : ''}</p>
				<ResultsChart
					spec={buildSpec(e.card, e.choice, opts)}
					theme={chartTheme}
					title={e.title}
					description={opts.description}
					onview={() => ready++}
				/>
			</li>
		{/each}
	</ul>
</main>

<style>
	.gallery {
		max-width: 90rem;
		margin: 0 auto;
		padding: var(--space-5);
		color: var(--color-text);
	}
	h1 {
		font-size: var(--text-xl);
	}
	.intro,
	.meta {
		color: var(--color-text-muted);
	}
	.meta {
		margin: 0 0 var(--space-2);
		font-size: var(--text-sm);
	}
	.intro a {
		color: var(--color-accent);
	}
	h2 {
		font-size: var(--text-md);
		margin: 0 0 var(--space-1);
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(24rem, 1fr));
		gap: var(--space-4);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.grid > li {
		min-width: 0;
		padding: var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
	}
	.export .grid > li {
		background: #ffffff;
		color: #000000;
	}
	.export .grid > li .meta {
		color: #333333;
	}
	@media (max-width: 30rem) {
		.grid {
			grid-template-columns: 1fr;
		}
	}
</style>
