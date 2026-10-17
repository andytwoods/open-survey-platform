<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import ExportBadges from '../diagnostics/ExportBadges.svelte';
	import type { ExportBadge } from '../diagnostics/model';
	import type { OutlineNode } from '../model/outline';
	import type { SelectionStore } from '../selection.svelte';
	import { iconFor } from './icons';

	/**
	 * Simple cards for the outline tree: sections (level 1), groups (level 2), question
	 * cards. Real survey: block → page → question; the `?mock` tree: page → block → question.
	 * Rich per-family cards are task B5 (lib/cards).
	 */
	let {
		pages,
		selection,
		mock = false,
		onAddQuestion,
		exportBadges,
		onBadge
	}: {
		pages: OutlineNode[];
		selection: SelectionStore;
		mock?: boolean;
		/** Present when editing is connected: shows "Add question" under each page. */
		onAddQuestion?: (pageId: string) => void;
		/** Export badges (B10) per block/page/question id, for the selected target. */
		exportBadges?: ReadonlyMap<string, readonly ExportBadge[]>;
		/** A badge was clicked: go to the property it is about. */
		onBadge?: (badge: ExportBadge) => void;
	} = $props();

	const cardId = (id: string) => `card-${id}`;
	const firstId = $derived(pages[0]?.id);
	const kind = (n: OutlineNode) => (n.type === 'page' ? 'Page' : n.type === 'block' ? 'Block' : '');

	$effect(() => {
		const id = selection.id;
		if (id) document.getElementById(cardId(id))?.scrollIntoView?.({ block: 'nearest' });
	});

	// F6 lands on the selected card, or the first one when nothing is selected.
	const focusMark = (id: string) => ((selection.id ?? firstId) === id ? '' : undefined);
</script>

{#snippet badgeList(node: OutlineNode)}
	{@const xb = exportBadges?.get(node.id)}
	{#if xb?.length}
		<ul class="xbadges" aria-label="Export issues: {node.label}" data-export-badges={node.id}>
			<ExportBadges badges={xb} ongo={onBadge} />
		</ul>
	{/if}
{/snippet}

<div class="canvas">
	{#if mock}
		<p class="mock-note">Mock data: placeholder cards, not a live survey.</p>
	{/if}
	{#each pages as section (section.id)}
		{@const SectionIcon = iconFor(section)}
		<section class="page" aria-labelledby={cardId(section.id)}>
			<button
				type="button"
				id={cardId(section.id)}
				class="page-head"
				aria-current={selection.id === section.id ? 'true' : undefined}
				data-pane-focus={focusMark(section.id)}
				onclick={() => selection.select(section.id)}
			>
				<SectionIcon size={18} aria-hidden="true" />
				<span>{kind(section)}: {section.label}</span>
			</button>
			{@render badgeList(section)}
			{#each section.children ?? [] as group (group.id)}
				{@const GroupIcon = iconFor(group)}
				<div class="block">
					<button
						type="button"
						id={cardId(group.id)}
						class="block-head"
						aria-current={selection.id === group.id ? 'true' : undefined}
						data-pane-focus={focusMark(group.id)}
						onclick={() => selection.select(group.id)}
					>
						<GroupIcon size={16} aria-hidden="true" />
						<span>{kind(group)}: {group.label}</span>
					</button>
					{@render badgeList(group)}
					<ul class="cards">
						{#each group.children ?? [] as question (question.id)}
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
										{question.questionType || question.family}
									</span>
									<span class="card-label">{question.label}</span>
									<span class="card-placeholder" aria-hidden="true"></span>
								</button>
								{@render badgeList(question)}
							</li>
						{/each}
					</ul>
					{#if onAddQuestion && group.type === 'page'}
						<button
							type="button"
							class="add"
							aria-label="Add question to {group.label}"
							onclick={() => onAddQuestion(group.id)}
						>
							<Plus size={16} aria-hidden="true" />
							<span>Add question</span>
						</button>
					{/if}
				</div>
			{/each}
		</section>
	{/each}
</div>

<style>
	.xbadges {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1);
		margin: var(--space-1) 0 var(--space-2);
		padding: 0 var(--space-2);
	}
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
	.add {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		min-height: 2.75rem;
		margin-top: var(--space-3);
		padding: var(--space-1) var(--space-3);
		border: 1px dashed var(--color-border-strong);
		border-radius: var(--radius-md);
		background: transparent;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.add:hover {
		background: var(--color-surface-sunken);
		color: var(--color-text);
	}
	[aria-current='true'] {
		background: var(--color-selected);
	}
	.card[aria-current='true'] {
		border-color: var(--color-accent);
		box-shadow: 0 0 0 1px var(--color-accent);
	}
</style>
