<script lang="ts">
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import { tick, untrack } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import type { OutlineNode } from '../model/outline';
	import { ancestorsOf, navigate, visibleRows } from '../outline/tree-nav';
	import type { SelectionStore } from '../selection.svelte';
	import { iconFor } from './icons';

	/**
	 * Outline tree (WAI-ARIA tree, single select, selection follows focus).
	 * Roving tabindex: only the active item is in the Tab order; arrows move within.
	 */
	let { roots, selection }: { roots: OutlineNode[]; selection: SelectionStore } = $props();

	function allParents(nodes: OutlineNode[], out: string[] = []): string[] {
		for (const n of nodes) {
			if (n.children?.length) {
				out.push(n.id);
				allParents(n.children, out);
			}
		}
		return out;
	}

	const expanded = new SvelteSet<string>(untrack(() => allParents(roots)));
	// Parents that appear later (a page added by an edit) start expanded too; ones the
	// user collapsed stay collapsed.
	// Bookkeeping only, deliberately not reactive.
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	const seen = new Set<string>(untrack(() => allParents(roots)));
	$effect(() => {
		for (const id of allParents(roots)) {
			if (!seen.has(id)) {
				seen.add(id);
				expanded.add(id);
			}
		}
	});
	const rows = $derived(visibleRows(roots, expanded));
	const activeId = $derived(
		selection.id && rows.some((r) => r.node.id === selection.id) ? selection.id : rows[0]?.node.id
	);

	// A selection made elsewhere (e.g. the canvas) reveals the item here.
	$effect(() => {
		const id = selection.id;
		if (id) for (const a of ancestorsOf(roots, id)) expanded.add(a);
	});

	const domId = (id: string) => `outline-${id}`;

	async function focusItem(id: string) {
		selection.select(id);
		await tick();
		document.getElementById(domId(id))?.focus();
	}

	function toggle(node: OutlineNode) {
		if (expanded.has(node.id)) {
			expanded.delete(node.id);
			if (selection.id && ancestorsOf(roots, selection.id).includes(node.id)) selection.select(node.id);
		} else {
			expanded.add(node.id);
		}
	}

	function onkeydown(e: KeyboardEvent) {
		if (e.ctrlKey || e.metaKey || e.altKey || !activeId) return;
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			selection.select(activeId);
			return;
		}
		const result = navigate(e.key, activeId, roots, expanded);
		if (result.kind === 'none') return;
		e.preventDefault();
		if (result.kind === 'expand') expanded.add(result.id);
		else if (result.kind === 'collapse') expanded.delete(result.id);
		else void focusItem(result.id);
	}

</script>

<!-- Flat rendering with aria-level/setsize/posinset (valid for the tree pattern). -->
<ul class="tree" role="tree" aria-label="Survey outline" {onkeydown}>
	{#each rows as row (row.node.id)}
		{@const node = row.node}
		{@const Icon = iconFor(node)}
		{@const hasKids = !!node.children?.length}
		{@const open = hasKids && expanded.has(node.id)}
		<!-- svelte-ignore a11y_click_events_have_key_events (keys are handled on the tree) -->
		<li
			id={domId(node.id)}
			role="treeitem"
			aria-level={row.level}
			aria-setsize={row.setsize}
			aria-posinset={row.posinset}
			aria-expanded={hasKids ? open : undefined}
			aria-selected={selection.id === node.id}
			tabindex={activeId === node.id ? 0 : -1}
			data-pane-focus={activeId === node.id ? '' : undefined}
			data-type={node.type}
			style:padding-inline-start="calc({row.level - 1} * 1rem + 0.25rem)"
			onclick={() => void focusItem(node.id)}
		>
			{#if hasKids}
				<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
				<span
					class="chevron"
					class:open
					onclick={(e) => {
						e.stopPropagation();
						toggle(node);
					}}
				>
					<ChevronRight size={16} aria-hidden="true" />
				</span>
			{:else}
				<span class="chevron spacer"></span>
			{/if}
			<Icon size={16} aria-hidden="true" class="type-icon" />
			<span class="label">{node.label}</span>
		</li>
	{/each}
</ul>

<style>
	ul {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.tree {
		padding: var(--space-1);
	}
	li {
		display: flex;
		align-items: center;
		gap: var(--space-1);
		min-height: 1.875rem;
		padding-inline-end: var(--space-2);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
	}
	li[data-type='page'] {
		font-weight: var(--weight-medium);
	}
	li:hover {
		background: var(--color-surface-sunken);
	}
	li[aria-selected='true'] {
		background: var(--color-selected);
	}
	li:focus-visible {
		outline-offset: -2px;
	}
	.chevron {
		display: inline-grid;
		place-items: center;
		flex: none;
		width: 1.25rem;
		height: 1.25rem;
		color: var(--color-text-muted);
		cursor: pointer;
		transition: transform var(--duration-fast);
	}
	.chevron.open {
		transform: rotate(90deg);
	}
	.chevron.spacer {
		cursor: default;
	}
	li :global(.type-icon) {
		flex: none;
		color: var(--color-text-muted);
	}
	.label {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
</style>
