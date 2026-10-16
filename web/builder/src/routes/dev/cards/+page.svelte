<script lang="ts">
	import { theme } from '@osp/ui-components';
	import { QuestionCard, FAMILIES } from '#lib/cards/index.js';
	import { onMount } from 'svelte';
	import { CHOICE_LISTS, SAMPLES, SCHEMAS } from './content';

	// Developer gallery of the builder's question cards, one section per family.
	// Checked by e2e/cards.spec.ts (snapshots per family, light + dark, axe).
	onMount(() => theme.init());

	let selected = $state<string | null>('q_devices');
</script>

<svelte:head>
	<title>Question cards · Open Survey Platform</title>
</svelte:head>

<main class="gallery">
	<h1>Question cards</h1>
	<p class="status" data-testid="selected">Selected: {selected ?? 'none'}</p>

	{#each FAMILIES as family (family)}
		<section aria-labelledby="h-{family}" data-testid="family-{family}">
			<h2 id="h-{family}">{family}</h2>
			<ul class="cards">
				{#each SAMPLES[family] as sample (sample.question.id)}
					<li>
						<QuestionCard
							question={sample.question}
							schema={SCHEMAS[sample.question.type]}
							selected={selected === sample.question.id}
							diagnostics={sample.diagnostics}
							choiceLists={CHOICE_LISTS}
							onselect={(id) => (selected = id)}
						>
							{#snippet exportBadges()}
								{#if sample.exportWarning}
									<li data-badge="export">{sample.exportWarning}</li>
								{/if}
							{/snippet}
						</QuestionCard>
					</li>
				{/each}
			</ul>
		</section>
	{/each}

	<section aria-labelledby="h-unknown" data-testid="family-unknown">
		<h2 id="h-unknown">Unknown type</h2>
		<QuestionCard
			question={{ id: 'q_rank', type: 'ranking', label: 'Rank these options' }}
			selected={selected === 'q_rank'}
			onselect={(id) => (selected = id)}
		/>
	</section>
</main>

<style>
	.gallery {
		max-width: 46rem;
		margin: 0 auto;
		padding: var(--space-5);
		color: var(--color-text);
	}
	h1 {
		font-size: var(--text-xl);
	}
	h2 {
		font-size: var(--text-md);
		color: var(--color-text-muted);
		text-transform: capitalize;
	}
	section {
		padding: var(--space-2);
		margin-block-end: var(--space-4);
	}
	.status {
		color: var(--color-text-muted);
	}
	.cards {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		margin: 0;
		padding: 0;
		list-style: none;
	}
</style>
