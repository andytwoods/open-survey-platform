<script lang="ts">
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import { announce } from '@osp/ui-components';
	import { tick, untrack } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import type { OutlineNode } from '../model/outline';
	import { dropTargetAt, measureRows, type DragHit, type RowBox } from '../outline/drag';
	import { indexTree, keyboardTarget, movableIds, type DropTarget, type MovableType } from '../outline/moves';
	import { MultiSelection } from '../outline/multi-select.svelte';
	import { ancestorsOf, navigate, visibleRows } from '../outline/tree-nav';
	import type { SelectionStore } from '../selection.svelte';
	import { iconFor } from './icons';

	/**
	 * Outline tree (WAI-ARIA tree, selection follows focus). Roving tabindex: only the
	 * active item is in the Tab order; arrows move within. Shift/Ctrl extend the selection.
	 * With `onMove`, items reorder by pointer drag, Alt+↑/↓ (past a sibling) and
	 * Alt+Shift+↑/↓ (across a page or block boundary); each gesture is one `onMove` call.
	 */
	let {
		roots,
		selection,
		multi = new MultiSelection(untrack(() => selection)),
		onMove
	}: {
		roots: OutlineNode[];
		selection: SelectionStore;
		multi?: MultiSelection;
		/** Move the items (all one type) into the gap; resolves when the server answered. */
		onMove?: (ids: string[], target: DropTarget) => Promise<unknown> | void;
	} = $props();

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
	const info = $derived(indexTree(roots));
	const typeOf = (id: string) => info.get(id)?.type;
	const activeId = $derived(
		selection.id && rows.some((r) => r.node.id === selection.id) ? selection.id : rows[0]?.node.id
	);

	// A selection made elsewhere (e.g. the canvas) reveals the item here.
	$effect(() => {
		const id = selection.id;
		if (id) for (const a of ancestorsOf(roots, id)) expanded.add(a);
	});

	const domId = (id: string) => `outline-${id}`;

	async function focusItem(id: string, mode: 'single' | 'range' | 'toggle' = 'single') {
		if (mode === 'range') multi.range(id, rows.map((r) => r.node.id), typeOf);
		else if (mode === 'toggle') multi.toggle(id, typeOf);
		else multi.single(id);
		await tick();
		document.getElementById(domId(id))?.focus();
	}

	function toggle(node: OutlineNode) {
		if (expanded.has(node.id)) {
			expanded.delete(node.id);
			if (selection.id && ancestorsOf(roots, selection.id).includes(node.id)) multi.single(node.id);
		} else {
			expanded.add(node.id);
		}
	}

	// -- moving ------------------------------------------------------------------------

	const isMovable = (t: string | undefined): t is MovableType => t === 'block' || t === 'page' || t === 'question';

	/** The items a gesture on `id` moves: the selection if `id` is in it, else just `id`. */
	function gestureIds(id: string): string[] {
		const t = typeOf(id);
		return multi.has(id) && isMovable(t) ? movableIds(roots, multi.ids, t) : [id];
	}

	async function runMove(ids: string[], target: DropTarget, focusId: string) {
		if (!onMove) return;
		const done = onMove(ids, target);
		// Keyed rows move in the DOM, which drops focus: put it back (and again once the
		// server has answered, in case a rollback moved them again).
		const refocus = async () => {
			await tick();
			for (const id of ids) for (const a of ancestorsOf(roots, id)) expanded.add(a);
			await tick();
			const el = document.getElementById(domId(focusId));
			const active = document.activeElement;
			if (el && (!active || active === document.body || active.closest('[role="tree"]'))) el.focus();
		};
		await refocus();
		await done;
		await refocus();
	}

	function keyMove(e: KeyboardEvent, id: string) {
		const dir = e.key === 'ArrowUp' ? -1 : 1;
		const ids = gestureIds(id);
		const target = keyboardTarget(roots, ids, dir, e.shiftKey);
		if (!target) {
			if (e.shiftKey && typeOf(id) === 'block') announce('Blocks have no boundary to cross. Use Alt+Up or Alt+Down.');
			else announce(dir < 0 ? 'Already at the top.' : 'Already at the bottom.');
			return;
		}
		void runMove(ids, target, id);
	}

	function onkeydown(e: KeyboardEvent) {
		if (drag && e.key === 'Escape') {
			e.preventDefault();
			e.stopPropagation();
			cancelDrag();
			return;
		}
		if (!activeId) return;
		if (e.altKey && !e.ctrlKey && !e.metaKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
			if (!onMove) return;
			e.preventDefault();
			keyMove(e, activeId);
			return;
		}
		if (e.ctrlKey || e.metaKey || e.altKey) return;
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			multi.single(activeId);
			return;
		}
		const result = navigate(e.key, activeId, roots, expanded);
		if (result.kind === 'none') return;
		e.preventDefault();
		if (result.kind === 'expand') expanded.add(result.id);
		else if (result.kind === 'collapse') expanded.delete(result.id);
		else {
			const extend = e.shiftKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown');
			void focusItem(result.id, extend ? 'range' : 'single');
		}
	}

	function onItemClick(e: MouseEvent, id: string) {
		if (suppressClick) {
			suppressClick = false;
			return;
		}
		void focusItem(id, e.shiftKey ? 'range' : e.ctrlKey || e.metaKey ? 'toggle' : 'single');
	}

	// -- drag (pointer) ------------------------------------------------------------------

	const DRAG_THRESHOLD = 4;
	let tree = $state<HTMLElement | null>(null);
	let suppressClick = false;
	let drag = $state<{
		id: string;
		ids: string[];
		pointerId: number;
		startX: number;
		startY: number;
		active: boolean;
		boxes: RowBox[];
		hit: DragHit | null;
	} | null>(null);
	const dragging = $derived(drag?.active ? new Set(drag.ids) : null);

	function describeHit(hit: DragHit): string {
		const label = info.get(hit.rowId)?.label ?? hit.rowId;
		return hit.edge === 'into' ? `Drop into ${label}` : `Drop ${hit.edge} ${label}`;
	}

	function onpointerdown(e: PointerEvent) {
		if (!onMove || e.button !== 0 || e.shiftKey || e.ctrlKey || e.metaKey) return;
		const target = e.target as Element | null;
		const el = target?.closest<HTMLElement>('[role="treeitem"]');
		if (!el || target?.closest('.chevron')) return;
		const id = el.dataset.id;
		if (!id || !isMovable(typeOf(id))) return;
		drag = { id, ids: [], pointerId: e.pointerId, startX: e.clientX, startY: e.clientY, active: false, boxes: [], hit: null };
	}

	function onpointermove(e: PointerEvent) {
		if (!drag || e.pointerId !== drag.pointerId) return;
		const type = typeOf(drag.id);
		if (!isMovable(type)) return;
		if (!drag.active) {
			const dx = Math.abs(e.clientX - drag.startX);
			const dy = Math.abs(e.clientY - drag.startY);
			if ((dx < DRAG_THRESHOLD && dy < DRAG_THRESHOLD) || !tree) return;
			tree.setPointerCapture?.(e.pointerId);
			drag.ids = gestureIds(drag.id);
			drag.boxes = measureRows(tree, rows);
			drag.active = true;
			const n = drag.ids.length;
			announce(`Moving ${n === 1 ? (info.get(drag.id)?.label ?? drag.id) : `${n} items`}. Escape cancels.`);
		}
		const hit = dropTargetAt(drag.boxes, e.clientY, type, roots, drag.ids);
		const changed = hit?.rowId !== drag.hit?.rowId || hit?.edge !== drag.hit?.edge;
		drag.hit = hit;
		if (changed && hit) announce(describeHit(hit));
	}

	function onpointerup(e: PointerEvent) {
		if (!drag || e.pointerId !== drag.pointerId) return;
		const { active, hit, ids, id } = drag;
		drag = null;
		if (!active) return;
		suppressClick = true;
		setTimeout(() => (suppressClick = false), 0);
		if (tree?.hasPointerCapture?.(e.pointerId)) tree.releasePointerCapture(e.pointerId);
		if (!hit) return announce('Move cancelled.');
		void runMove(ids, hit.target, id);
	}

	function cancelDrag() {
		if (drag?.active) announce('Move cancelled.');
		drag = null;
	}

	/** Which edge of this row shows the drop indicator, if any. */
	function dropEdge(id: string): string | undefined {
		const hit = drag?.active ? drag.hit : null;
		return hit && hit.lineRowId === id ? hit.edge : undefined;
	}
</script>

<!-- Flat rendering with aria-level/setsize/posinset (valid for the tree pattern). -->
<ul
	bind:this={tree}
	class="tree"
	class:is-dragging={!!drag?.active}
	role="tree"
	aria-label="Survey outline"
	aria-multiselectable="true"
	{onkeydown}
	{onpointerdown}
	{onpointermove}
	{onpointerup}
	onpointercancel={cancelDrag}
	onlostpointercapture={() => drag?.active && cancelDrag()}
>
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
			aria-selected={multi.has(node.id)}
			tabindex={activeId === node.id ? 0 : -1}
			data-pane-focus={activeId === node.id ? '' : undefined}
			data-type={node.type}
			data-id={node.id}
			data-drop={dropEdge(node.id)}
			class:moving={dragging?.has(node.id)}
			style:padding-inline-start="calc({row.level - 1} * 1rem + 0.25rem)"
			onclick={(e) => onItemClick(e, node.id)}
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
	.tree.is-dragging {
		cursor: grabbing;
		user-select: none;
	}
	li {
		position: relative;
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
	li.moving {
		opacity: 0.55;
	}
	/* Drop indicators: a line between rows, or an outline round the row dropped into. */
	li[data-drop='before']::before,
	li[data-drop='after']::after {
		content: '';
		position: absolute;
		inset-inline: 0;
		height: 2px;
		background: var(--color-accent);
		pointer-events: none;
	}
	li[data-drop='before']::before {
		top: -1px;
	}
	li[data-drop='after']::after {
		bottom: -1px;
	}
	li[data-drop='into'] {
		box-shadow: inset 0 0 0 2px var(--color-accent);
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
