<script lang="ts">
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import Plus from '@lucide/svelte/icons/plus';
	import { Button, announce } from '@osp/ui-components';
	import { onDestroy, onMount, untrack } from 'svelte';
	import type { OutlineNode } from '../model/outline';
	import type { DropTarget } from '../outline/moves';
	import type { TypeDrag } from '../question-types/type-drag.svelte';
	import BankItemCard from './BankItemCard.svelte';
	import { bank, type SearchParams } from './library.svelte';
	import { describeDestination, destinationFromGap, hasNewerVersion, type BankItemOut, type BankKind, type BankSummary } from './logic';

	/**
	 * The Bank section under the outline (question-bank.md §6), beside the question types:
	 * search over title, abbreviation, item text and tags; filters for source and kind; a
	 * card per item with a preview; Insert places it at the selection; dragging a card onto
	 * the outline or the canvas uses the toolbox drag (B19's insertion line); on narrow
	 * screens a tap picks it up and the canvas shows "Place here". The heading collapses it.
	 */
	let {
		drag,
		roots,
		survey,
		collapsed = $bindable(true),
		tapToPlace = false,
		lang = 'en',
		bankPageUrl = null,
		oninsert,
		ondrop,
		onplace
	}: {
		drag: TypeDrag;
		roots: OutlineNode[];
		survey: unknown;
		collapsed?: boolean;
		tapToPlace?: boolean;
		lang?: string;
		/** The Bank page, when the host serves it. */
		bankPageUrl?: string | null;
		/** Insert at the selection. */
		oninsert: (summary: BankSummary, item: BankItemOut) => void;
		/** Dropped on a gap of the outline or the canvas. */
		ondrop: (summary: BankSummary, item: BankItemOut, target: DropTarget) => void;
		/** Narrow screens: picked up; the canvas asks where it goes. */
		onplace: (summary: BankSummary, item: BankItemOut) => void;
	} = $props();

	const uid = $props.id();
	const bodyId = `osp-bank-${uid}`;
	let q = $state('');
	let source = $state<'' | 'lab' | 'host' | 'bundled'>('');
	let kind = $state<'' | BankKind>('');
	let timer: ReturnType<typeof setTimeout> | undefined;
	let loadedOnce = false;

	function params(): SearchParams {
		const p: SearchParams = { pageSize: 50 };
		if (q.trim()) p.q = q.trim();
		if (source) p.source = source;
		if (kind) p.kind = kind;
		return p;
	}
	function run() {
		loadedOnce = true;
		void bank.search(params());
	}
	function later() {
		clearTimeout(timer);
		timer = setTimeout(run, 250);
	}
	onDestroy(() => clearTimeout(timer));
	onMount(() => {
		if (!collapsed) run();
	});
	$effect(() => {
		if (!collapsed && !untrack(() => loadedOnce)) untrack(run);
	});

	const items = $derived(bank.list?.items ?? []);
	const busy = $state<Record<string, boolean>>({});

	async function withDoc(summary: BankSummary, fn: (item: BankItemOut) => void) {
		busy[summary.id] = true;
		const r = await bank.get(summary.id);
		busy[summary.id] = false;
		if (!r.ok) return announce(`Could not load ${summary.title}: ${r.message}`, 'assertive');
		fn(r.data);
	}

	function insert(summary: BankSummary) {
		void withDoc(summary, (item) => (tapToPlace ? onplace(summary, item) : oninsert(summary, item)));
	}

	// -- drag (pointer), as the type toolbox does it ----------------------------------------

	const DRAG_THRESHOLD = 4;
	let pointer = $state<{ summary: BankSummary; el: HTMLElement; pointerId: number; startX: number; startY: number; x: number; y: number; active: boolean } | null>(
		null
	);

	function onpointerdown(e: PointerEvent, summary: BankSummary) {
		if (tapToPlace || e.button !== 0 || e.shiftKey || e.ctrlKey || e.metaKey) return;
		const el = e.currentTarget as HTMLElement;
		pointer = { summary, el, pointerId: e.pointerId, startX: e.clientX, startY: e.clientY, x: 0, y: 0, active: false };
	}

	function describe(): string | null {
		const p = pointer;
		const hit = drag.hit;
		if (!p || !hit) return null;
		const d = destinationFromGap(p.summary.kind, roots, survey, hit.hit.target);
		return d ? describeDestination(roots, p.summary.abbreviation || p.summary.title, d) : 'Nowhere to put it here';
	}

	function onpointermove(e: PointerEvent) {
		const p = pointer;
		if (!p || e.pointerId !== p.pointerId) return;
		if (!p.active) {
			if (Math.abs(e.clientX - p.startX) < DRAG_THRESHOLD && Math.abs(e.clientY - p.startY) < DRAG_THRESHOLD) return;
			p.el.setPointerCapture?.(e.pointerId);
			p.active = true;
			drag.start({ kind: 'bank', id: p.summary.id, label: p.summary.abbreviation || p.summary.title, itemKind: p.summary.kind });
			announce(`Dragging ${p.summary.title}. Drop it on a page or between questions. Escape cancels.`);
			window.addEventListener('keydown', onWindowKey, true);
		}
		p.x = e.clientX;
		p.y = e.clientY;
		if (drag.move(e.clientX, e.clientY) && drag.hit) {
			const text = describe();
			if (text) announce(text);
		}
	}

	function onpointerup(e: PointerEvent) {
		const p = pointer;
		if (!p || e.pointerId !== p.pointerId) return;
		pointer = null;
		if (!p.active) return;
		stopListening();
		if (p.el.hasPointerCapture?.(e.pointerId)) p.el.releasePointerCapture(e.pointerId);
		const hit = drag.end();
		if (!hit) return announce('Not inserted: drop it on a page or between questions.');
		void withDoc(p.summary, (item) => ondrop(p.summary, item, hit.hit.target));
	}

	function cancel() {
		const p = pointer;
		pointer = null;
		stopListening();
		if (!p?.active) return;
		if (p.el.hasPointerCapture?.(p.pointerId)) p.el.releasePointerCapture(p.pointerId);
		drag.end();
		announce('Drag cancelled.');
	}
	function onWindowKey(e: KeyboardEvent) {
		if (e.key !== 'Escape') return;
		e.preventDefault();
		e.stopPropagation();
		cancel();
	}
	function stopListening() {
		window.removeEventListener('keydown', onWindowKey, true);
	}
	onDestroy(stopListening);
	const ghost = $derived(pointer?.active ? pointer.summary : null);
</script>

<section class="bank toolbox" aria-labelledby="{bodyId}-heading" data-testid="bank-pane">
	<h2 id="{bodyId}-heading" class="heading">
		<button type="button" class="toggle" aria-expanded={!collapsed} aria-controls={bodyId} onclick={() => (collapsed = !collapsed)}>
			<span class="chevron" class:open={!collapsed} aria-hidden="true"><ChevronRight size={16} /></span>
			Bank
		</button>
	</h2>
	<div id={bodyId} class="body" hidden={collapsed}>
		<p class="hint">
			Saved questions, pages and blocks, and the bundled instruments.
			{#if tapToPlace}Insert picks one up; tap where it goes on the canvas.{:else}Insert places it at the selection, or drag a
				card onto the outline or the canvas.{/if}
		</p>
		<div class="filters">
			<label class="search">
				<span class="osp-visually-hidden">Search the bank</span>
				<input type="search" placeholder="Search the bank…" bind:value={q} oninput={later} autocomplete="off" />
			</label>
			<label>
				<span class="osp-visually-hidden">Source</span>
				<select bind:value={source} onchange={run}>
					<option value="">All sources</option>
					<option value="lab">My lab</option>
					<option value="host">Shared on this host</option>
					<option value="bundled">Bundled</option>
				</select>
			</label>
			<label>
				<span class="osp-visually-hidden">Kind</span>
				<select bind:value={kind} onchange={run}>
					<option value="">Any kind</option>
					<option value="question">Questions</option>
					<option value="page">Pages</option>
					<option value="block">Blocks</option>
				</select>
			</label>
		</div>
		{#if bank.error}
			<p class="status error" role="alert">{bank.error}</p>
		{:else if bank.loading && !bank.list}
			<p class="status" role="status">Loading the bank…</p>
		{:else if bank.list && items.length === 0}
			<p class="status" role="status">Nothing matches. Save a question, page or block from its menu to start your lab's bank.</p>
		{/if}
		<ul class="results" aria-label="Bank items" aria-busy={bank.loading}>
			{#each items as s (s.id)}
				<li
					class="result"
					class:dragging={pointer?.active && pointer.summary.id === s.id}
					data-bank-result={s.id}
					onpointerdown={(e) => onpointerdown(e, s)}
					{onpointermove}
					{onpointerup}
					onpointercancel={cancel}
				>
					<BankItemCard summary={s} newer={hasNewerVersion(s, survey)} {lang} compact>
						{#snippet actions(summary)}
							<Button size="sm" variant="primary" disabled={busy[summary.id]} aria-label="Insert {summary.title}" onclick={() => insert(summary)}>
								<Plus size={14} aria-hidden="true" />
								Insert
							</Button>
						{/snippet}
					</BankItemCard>
				</li>
			{/each}
		</ul>
		{#if bank.list && bank.list.total > items.length}
			<p class="status">Showing {items.length} of {bank.list.total}. Narrow the search to see the rest.</p>
		{/if}
		{#if bankPageUrl}
			<p class="status">
				<a href={bankPageUrl}>Manage the bank <ExternalLink size={12} aria-hidden="true" /></a>
			</p>
		{/if}
	</div>
</section>

{#if ghost && pointer}
	<div class="ghost" aria-hidden="true" style:left="{pointer.x + 12}px" style:top="{pointer.y + 12}px">
		{ghost.abbreviation || ghost.title}
	</div>
{/if}

<style>
	.bank {
		border-top: 1px solid var(--color-border);
		background: var(--color-surface);
	}
	.heading {
		margin: 0;
		font-size: var(--text-sm);
	}
	.toggle {
		display: flex;
		align-items: center;
		gap: var(--space-1);
		width: 100%;
		min-height: 2.75rem;
		padding: 0 var(--space-3);
		border: 0;
		background: none;
		color: var(--color-text-muted);
		font: inherit;
		font-weight: var(--weight-bold);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		cursor: pointer;
	}
	.toggle:hover {
		color: var(--color-text);
	}
	.chevron {
		display: inline-grid;
		place-items: center;
		transition: transform var(--duration-fast);
	}
	.chevron.open {
		transform: rotate(90deg);
	}
	.body {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: 0 var(--space-2) var(--space-2);
	}
	.hint,
	.status {
		margin: 0 var(--space-1);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.status.error {
		color: var(--color-danger);
	}
	.filters {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1);
	}
	.filters label {
		flex: 1 1 7rem;
		min-width: 0;
	}
	.filters .search {
		flex-basis: 100%;
	}
	.filters input,
	.filters select {
		width: 100%;
		min-height: 2.25rem;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
	}
	.results {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.result {
		/* Vertical swipes still scroll the pane; a sideways drag picks the card up. */
		touch-action: pan-y;
		user-select: none;
		cursor: grab;
	}
	.result.dragging {
		opacity: 0.55;
		cursor: grabbing;
	}
	.ghost {
		position: fixed;
		z-index: 100;
		max-width: 16rem;
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		box-shadow: var(--shadow-lg);
		color: var(--color-text);
		font-size: var(--text-sm);
		pointer-events: none;
	}
	a {
		color: var(--color-accent);
	}
</style>
