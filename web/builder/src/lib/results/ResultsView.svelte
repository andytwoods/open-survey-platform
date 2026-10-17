<script lang="ts">
	import { Button, theme } from '@osp/ui-components';
	import { onDestroy, onMount } from 'svelte';
	import FilterBar from './FilterBar.svelte';
	import { conditionVariables, describeFilters } from './model';
	import ResultCard from './ResultCard.svelte';
	import { apiSource, ResultsController, type ResultsSource } from './results.svelte';

	/**
	 * The Results page (task V2, planning/results-viewer.md): a filter bar, the active
	 * filters in words, and one card per question in survey order. Every number is the
	 * server's (V1); this page only asks and draws. Lazily loaded by the shell.
	 */
	let {
		surveyId,
		survey,
		publishedVersions,
		source
	}: {
		surveyId: string;
		/** The survey draft: its assigned variables give the condition filter's options. */
		survey: unknown;
		publishedVersions: number;
		/** Where results come from (default: the API). */
		source?: ResultsSource;
	} = $props();

	// The source and version count are fixed for the page's life (a new publish reloads).
	// svelte-ignore state_referenced_locally
	const controller = new ResultsController(source ?? apiSource(surveyId), publishedVersions);
	const conditions = $derived(conditionVariables(survey));
	const response = $derived(controller.response);
	const active = $derived(
		describeFilters(controller.applied, {
			choices: controller.choices,
			versionsUsed: response?.versionsUsed,
			splitLabel: response?.split?.label
		})
	);
	const slow = $derived(controller.loading && controller.elapsed >= 1);
	const chartTheme = $derived(theme.resolved === 'dark' ? 'dark' : 'light');

	let innerWidth = $state(1280);
	const narrow = $derived(innerWidth < 720);

	onMount(() => {
		if (publishedVersions > 0) void controller.load();
	});
	onDestroy(() => controller.dispose());
</script>

<svelte:window bind:innerWidth />

<div class="results" aria-busy={controller.loading}>
	<header class="page-head">
		<h2 id="results-heading">Results</h2>
		<p class="lead">
			One card per question, from the responses to the published survey. Counts are of responses, not
			participants.
		</p>
	</header>

	{#if publishedVersions === 0}
		<p class="empty" data-testid="results-unpublished">
			Nothing is published yet. Publish the survey and collect responses to see results here.
		</p>
	{:else}
		<FilterBar {controller} {conditions} {publishedVersions} {narrow} />

		<section class="summary" aria-labelledby="active-filters-h">
			<h3 id="active-filters-h" class="visually-hidden">Active filters</h3>
			<ul class="chips" data-testid="active-filters">
				{#each active as a (a)}<li>{a}</li>{/each}
			</ul>
			{#if response}
				<p class="count" data-testid="results-count">
					{`${response.responses} ${response.responses === 1 ? 'response' : 'responses'}`}{response.split
						? ` · ${response.split.groups.map((g) => `${g.label}: ${g.responses}`).join(', ')}`
						: ''}
				</p>
			{/if}
		</section>

		<div class="live" role="status" aria-live="polite">
			{#if controller.loading}
				<span class="waiting" data-testid="results-waiting">
					<span class="spinner" aria-hidden="true"></span>
					{#if slow}
						Computing results… {controller.elapsed} s. Large surveys can take a while.
					{:else}
						Computing results…
					{/if}
				</span>
			{/if}
		</div>
		{#if slow}
			<div><Button onclick={() => controller.cancel()}>Cancel</Button></div>
		{/if}

		{#if controller.error}
			<div class="error" role="alert" data-testid="results-error">
				<p>
					{#if controller.error.status === 403}
						You need owner or editor access to this survey to see its results.
					{:else}
						{controller.error.message}
					{/if}
				</p>
				<Button onclick={() => void controller.load()}>Try again</Button>
			</div>
		{/if}

		{#if response?.warnings?.length}
			<ul class="warnings" aria-label="Warnings">
				{#each response.warnings as w, i (i)}<li data-code={w.code}>{w.message}</li>{/each}
			</ul>
		{/if}

		{#if response}
			{#if response.cards.length}
				<ol class="cards" aria-label="Questions">
					{#each response.cards as card (card.question)}
						<li>
							<ResultCard {card} {controller} theme={chartTheme} split={!!response.split} />
						</li>
					{/each}
				</ol>
			{:else}
				<p class="empty">This version has no questions to show.</p>
			{/if}
		{/if}
	{/if}
</div>

<style>
	.results {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		max-width: 64rem;
		margin: 0 auto;
		padding: var(--space-5) var(--space-4) var(--space-6);
		color: var(--color-text);
	}
	.page-head h2 {
		margin: 0;
		font-size: var(--text-lg);
	}
	.lead,
	.count {
		margin: var(--space-1) 0 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.empty {
		padding: var(--space-4);
		border: 1px dashed var(--color-border-strong);
		border-radius: var(--radius-md);
		color: var(--color-text-muted);
	}
	.summary {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.chips li {
		padding: 2px var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-full);
		background: var(--color-surface-sunken);
		font-size: var(--text-xs);
	}
	.live:empty {
		display: none;
	}
	.waiting {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
	}
	.spinner {
		width: 1rem;
		height: 1rem;
		border: 2px solid var(--color-border-strong);
		border-top-color: var(--color-accent);
		border-radius: var(--radius-full);
		animation: spin 0.9s linear infinite;
	}
	@media (prefers-reduced-motion: reduce) {
		.spinner {
			animation: none;
		}
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	.error {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-3);
		padding: var(--space-3);
		border: 1px solid var(--color-danger);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
	}
	.error p {
		margin: 0;
	}
	.warnings {
		margin: 0;
		padding: var(--space-2) var(--space-3) var(--space-2) var(--space-5);
		border-inline-start: 4px solid var(--color-warning);
		background: var(--color-surface-raised);
		font-size: var(--text-sm);
	}
	.cards {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.cards > li {
		min-width: 0;
	}
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}
	@media (max-width: 30rem) {
		.results {
			padding-inline: var(--space-3);
		}
	}
</style>
