<script lang="ts">
	import type { MockNode } from '../mock/survey';
	import type { SelectionStore } from '../selection.svelte';
	import { iconFor } from './icons';

	/** Placeholder cards for the mock tree. Real question cards (per family) are task B5. */
	let { pages, selection }: { pages: MockNode[]; selection: SelectionStore } = $props();

	const cardId = (id: string) => `card-${id}`;
	const firstId = $derived(pages[0]?.id);

	$effect(() => {
		const id = selection.id;
		if (id) document.getElementById(cardId(id))?.scrollIntoView?.({ block: 'nearest' });
	});

	// F6 lands on the selected card, or the first one when nothing is selected.
	const focusMark = (id: string) => ((selection.id ?? firstId) === id ? '' : undefined);
</script>

<div class="canvas">
	<p class="mock-note">Mock data: placeholder cards, not a live survey.</p>
	{#each pages as page (page.id)}
		{@const PageIcon = iconFor(page)}
		<section class="page" aria-labelledby={cardId(page.id)}>
			<button
				type="button"
				id={cardId(page.id)}
				class="page-head"
				aria-current={selection.id === page.id ? 'true' : undefined}
				data-pane-focus={focusMark(page.id)}
				onclick={() => selection.select(page.id)}
			>
				<PageIcon size={18} aria-hidden="true" />
				<span>Page: {page.label}</span>
			</button>
			{#each page.children ?? [] as block (block.id)}
				{@const BlockIcon = iconFor(block)}
				<div class="block">
					<button
						type="button"
						id={cardId(block.id)}
						class="block-head"
						aria-current={selection.id === block.id ? 'true' : undefined}
						data-pane-focus={focusMark(block.id)}
						onclick={() => selection.select(block.id)}
					>
						<BlockIcon size={16} aria-hidden="true" />
						<span>Block: {block.label}</span>
					</button>
					<ul class="cards">
						{#each block.children ?? [] as question (question.id)}
							{@const QIcon = iconFor(question)}
							<li>
								<button
									type="button"
									id={cardId(question.id)}
									class="card"
									aria-current={selection.id === question.id ? 'true' : undefined}
									data-pane-focus={focusMark(question.id)}
									onclick={() => selection.select(question.id)}
								>
									<span class="card-type">
										<QIcon size={16} aria-hidden="true" />
										{question.family}
									</span>
									<span class="card-label">{question.label}</span>
									<span class="card-placeholder" aria-hidden="true"></span>
								</button>
							</li>
						{/each}
					</ul>
				</div>
			{/each}
		</section>
	{/each}
</div>

<style>
	.canvas {
		max-width: 46rem;
		margin: 0 auto;
		padding: var(--space-5) var(--space-5) var(--space-8);
	}
	.mock-note {
		margin: 0 0 var(--space-4);
		padding: var(--space-2) var(--space-3);
		border: 1px dashed var(--color-border-strong);
		border-radius: var(--radius-md);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.page {
		margin-block-end: var(--space-6);
	}
	button {
		font: inherit;
		color: inherit;
		text-align: start;
		cursor: pointer;
	}
	.page-head,
	.block-head {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		width: 100%;
		padding: var(--space-2) var(--space-2);
		border: 1px solid transparent;
		border-radius: var(--radius-md);
		background: transparent;
	}
	.page-head {
		font-size: var(--text-lg);
		font-weight: var(--weight-bold);
	}
	.block-head {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}
	.page-head:hover,
	.block-head:hover {
		background: var(--color-surface-sunken);
	}
	.block {
		margin: var(--space-2) 0 var(--space-4) var(--space-3);
		padding-inline-start: var(--space-3);
		border-inline-start: 2px solid var(--color-border);
	}
	.cards {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		margin: var(--space-2) 0 0;
		padding: 0;
		list-style: none;
	}
	.card {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		width: 100%;
		padding: var(--space-3) var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		background: var(--color-surface-raised);
		box-shadow: var(--shadow-sm);
	}
	.card:hover {
		border-color: var(--color-border-strong);
	}
	.card-type {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.card-label {
		font-weight: var(--weight-medium);
	}
	.card-placeholder {
		display: block;
		height: 0.625rem;
		width: 60%;
		border-radius: var(--radius-full);
		background: var(--color-surface-sunken);
	}
	[aria-current='true'] {
		background: var(--color-selected);
	}
	.card[aria-current='true'] {
		border-color: var(--color-accent);
		box-shadow: 0 0 0 1px var(--color-accent);
	}
</style>
