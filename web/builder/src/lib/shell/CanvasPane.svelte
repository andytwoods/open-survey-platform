<script lang="ts">
	import GripVertical from '@lucide/svelte/icons/grip-vertical';
	import Plus from '@lucide/svelte/icons/plus';
	import { announce } from '@osp/ui-components';
	import { onDestroy, tick } from 'svelte';
	import QuestionCard from '../cards/QuestionCard.svelte';
	import { canvasDropAt, canvasGapAt, describeGap, measureCanvas, type DragHit } from '../outline/drag';
	import type { DropTarget } from '../outline/moves';
	import type { TypeDrag } from '../question-types/type-drag.svelte';
	import { AutoScroller, scrollParent } from './auto-scroll';
	import { choiceListsOf } from '../choices/model';
	import ExportBadges from '../diagnostics/ExportBadges.svelte';
	import { validationByOwner, type ExportBadge, type ValidationDiagnostic } from '../diagnostics/model';
	import { defaultLanguage, type OutlineNode } from '../model/outline';
	import { schemaFor } from '../properties/schemas.svelte';
	import type { PropertySchemasDoc } from '../properties/types';
	import type { SelectionStore } from '../selection.svelte';
	import { canvasQuestions, cardSchema } from './canvas';
	import { iconFor } from './icons';

	/**
	 * The outline tree as cards: sections (level 1), groups (level 2), question cards.
	 * Real survey: block → page → question; the `?mock` tree: page → block → question.
	 * Questions of a real survey are the rich per-family cards (lib/cards, task B5), fed the
	 * question's own JSON from `survey`, its property schema, the shared choice lists and
	 * the default language: a read-only participant preview that follows every patch.
	 * Editing stays in the properties panel. The mock tree has no question JSON, and an
	 * outline node not (yet) in `survey` has none either: those get the simple card.
	 *
	 * Drag and drop (B19): a type dragged from the toolbox (`typeDrag`) drops into the gap
	 * under the pointer, shown as a line between cards or a zone on an empty page; with
	 * `onMove`, a card dragged by mouse (anywhere on it) or touch (by its grip) reorders,
	 * as one `moveOps` transaction like the outline's. Escape cancels; near the pane's top
	 * or bottom edge it scrolls. `placing` is the narrow-screen fallback: "Place here"
	 * buttons in every gap, for a type picked from the toolbox with a tap.
	 */
	let {
		pages,
		selection,
		survey = null,
		schemas = null,
		mock = false,
		onAddQuestion,
		exportBadges,
		onBadge,
		diagnostics = [],
		onDiagnostic,
		typeDrag,
		onMove,
		placing = null,
		onPlace,
		onCancelPlace,
		placeDefault = null
	}: {
		pages: OutlineNode[];
		selection: SelectionStore;
		/** The survey document the cards preview (null: simple cards only, e.g. `?mock`). */
		survey?: unknown;
		/** The property schemas (GET /api/meta/property-schemas), once loaded. */
		schemas?: PropertySchemasDoc | null;
		mock?: boolean;
		/** Present when editing is connected: shows "Add question" under each page. */
		onAddQuestion?: (pageId: string) => void;
		/** Export badges (B10) per block/page/question id, for the selected target. */
		exportBadges?: ReadonlyMap<string, readonly ExportBadge[]>;
		/** A badge was clicked: go to the property it is about. */
		onBadge?: (badge: ExportBadge) => void;
		/** The validator's diagnostics for `survey` (B18): each card shows its own counts. */
		diagnostics?: readonly ValidationDiagnostic[];
		/** A card's error or warning count was clicked: go to its first such diagnostic. */
		onDiagnostic?: (diagnostic: ValidationDiagnostic) => void;
		/** A type dragged from the toolbox: the canvas is a drop zone for it. */
		typeDrag?: TypeDrag;
		/** Move questions into a gap (the outline's move); present when cards may be dragged. */
		onMove?: (ids: string[], target: DropTarget) => Promise<unknown> | void;
		/** Tap-to-place: the name of the type being placed (null: not placing). */
		placing?: string | null;
		/** A "Place here" button was chosen. */
		onPlace?: (target: DropTarget) => void;
		onCancelPlace?: () => void;
		/** The page whose end gets focus when placing starts (else the first gap). */
		placeDefault?: string | null;
	} = $props();

	let root = $state<HTMLElement | null>(null);
	/** The scrolling pane around the canvas (the editor's canvas pane, else the nearest). */
	const scroller = () =>
		root?.closest<HTMLElement>('[data-pane="canvas"]') ?? scrollParent(root?.parentElement ?? null);

	/** Is (x, y) on the visible canvas, and not under something covering it (an overlay)? */
	function overCanvas(x: number, y: number): boolean {
		if (!root) return false;
		const box = (scroller() ?? root).getBoundingClientRect();
		if (x < box.left || x > box.right || y < box.top || y > box.bottom) return false;
		const top = typeof document.elementFromPoint === 'function' ? document.elementFromPoint(x, y) : null;
		return !top || (scroller() ?? root).contains(top);
	}

	// -- a question type dragged from the toolbox ------------------------------------------

	$effect(() => {
		if (!typeDrag) return;
		return typeDrag.attach((x, y) => {
			if (!root || !overCanvas(x, y)) return null;
			const hit = canvasGapAt(measureCanvas(root), y);
			return hit && { hit, description: describeGap(pages, hit.target) };
		});
	});

	// While a type is dragged, scroll near the edges and follow the pointer (the toolbox
	// holds the pointer capture, so its moves reach the window).
	$effect(() => {
		if (!typeDrag?.type) return;
		const td = typeDrag;
		const auto = new AutoScroller(scroller, () => {
			if (td.refresh() && td.hit) announce(td.hit.description);
		});
		const follow = (e: PointerEvent) => auto.update(e.clientX, e.clientY);
		window.addEventListener('pointermove', follow);
		return () => {
			window.removeEventListener('pointermove', follow);
			auto.stop();
		};
	});

	// -- dragging a card to reorder ------------------------------------------------------

	const DRAG_THRESHOLD = 4;
	let cardDrag = $state<{
		id: string;
		label: string;
		pointerId: number;
		startX: number;
		startY: number;
		x: number;
		y: number;
		active: boolean;
		hit: DragHit | null;
	} | null>(null);
	let suppressClick = false;
	const cardScroll = new AutoScroller(scroller, () => {
		if (cardDrag?.active) follow(cardDrag.x, cardDrag.y);
	});

	function labelOf(id: string): string {
		for (const s of pages) for (const g of s.children ?? []) for (const q of g.children ?? []) if (q.id === id) return q.label;
		return id;
	}

	function onpointerdown(e: PointerEvent) {
		if (!onMove || !root || e.button !== 0 || e.shiftKey || e.ctrlKey || e.metaKey || e.altKey) return;
		const t = e.target as Element | null;
		const card = t?.closest<HTMLElement>('[data-canvas-question]');
		if (!card || !root.contains(card)) return;
		// Badge buttons keep their clicks; touch drags only by the grip (else it scrolls).
		if (t?.closest('.count-btn, .xbadges, a, input, select, textarea')) return;
		const grip = t?.closest('[data-drag-handle]');
		if (e.pointerType === 'touch' && !grip) return;
		if (grip) e.preventDefault();
		const id = card.dataset.canvasQuestion ?? '';
		cardDrag = {
			id,
			label: labelOf(id),
			pointerId: e.pointerId,
			startX: e.clientX,
			startY: e.clientY,
			x: e.clientX,
			y: e.clientY,
			active: false,
			hit: null
		};
	}

	function follow(x: number, y: number) {
		const d = cardDrag;
		if (!d || !root) return;
		d.x = x;
		d.y = y;
		const hit = overCanvas(x, y) ? canvasDropAt(measureCanvas(root), y, pages, [d.id]) : null;
		const a = d.hit?.target;
		const changed = a?.parent !== hit?.target.parent || a?.slot !== hit?.target.slot;
		d.hit = hit;
		if (changed && hit) announce(describeGap(pages, hit.target, [d.id]));
	}

	function onpointermove(e: PointerEvent) {
		const d = cardDrag;
		if (!d || e.pointerId !== d.pointerId || !root) return;
		if (!d.active) {
			if (Math.abs(e.clientX - d.startX) < DRAG_THRESHOLD && Math.abs(e.clientY - d.startY) < DRAG_THRESHOLD) return;
			root.setPointerCapture?.(e.pointerId);
			d.active = true;
			announce(`Moving ${d.label}. Drop it between questions. Escape cancels.`);
			window.addEventListener('keydown', onWindowKey, true);
		}
		follow(e.clientX, e.clientY);
		cardScroll.update(e.clientX, e.clientY);
	}

	async function onpointerup(e: PointerEvent) {
		const d = cardDrag;
		if (!d || e.pointerId !== d.pointerId) return;
		cardDrag = null;
		stopCardDrag();
		if (!d.active) return;
		suppressClick = true;
		setTimeout(() => (suppressClick = false), 0);
		if (root?.hasPointerCapture?.(e.pointerId)) root.releasePointerCapture(e.pointerId);
		if (!d.hit || !onMove) return announce('Not moved.');
		const done = onMove([d.id], d.hit.target);
		selection.select(d.id);
		await tick();
		document.getElementById(cardId(d.id))?.focus();
		await done;
	}

	function cancelCardDrag() {
		const d = cardDrag;
		cardDrag = null;
		stopCardDrag();
		if (!d?.active) return;
		if (root?.hasPointerCapture?.(d.pointerId)) root.releasePointerCapture(d.pointerId);
		announce('Move cancelled.');
	}

	function onWindowKey(e: KeyboardEvent) {
		if (e.key !== 'Escape') return;
		e.preventDefault();
		e.stopPropagation();
		cancelCardDrag();
	}

	function stopCardDrag() {
		window.removeEventListener('keydown', onWindowKey, true);
		cardScroll.stop();
	}
	onDestroy(stopCardDrag);

	function onclickcapture(e: MouseEvent) {
		if (!suppressClick) return;
		suppressClick = false;
		e.preventDefault();
		e.stopPropagation();
	}

	// -- what to draw ----------------------------------------------------------------------

	/** The gap being shown: this pane's card drag, else the toolbox drag (over either pane). */
	const gap = $derived<DropTarget | null>(
		cardDrag?.active ? (cardDrag.hit?.target ?? null) : (typeDrag?.hit?.hit.target ?? null)
	);
	const dragging = $derived(!!cardDrag?.active || !!typeDrag?.type);

	/** Which edge of card `index` (of `count` on page `pageId`) shows the line, if any. */
	function dropEdge(pageId: string, index: number, count: number): 'before' | 'after' | undefined {
		if (!gap || gap.parent !== pageId) return undefined;
		if (gap.slot === index) return 'before';
		if (gap.slot >= count && index === count - 1) return 'after';
		return undefined;
	}

	// Tap-to-place: put the cursor on the default page's last gap, ready for Enter.
	$effect(() => {
		if (!placing) return;
		const page = placeDefault;
		void tick().then(() => {
			const all = root?.querySelectorAll<HTMLElement>('[data-place-page]');
			const mine = [...(all ?? [])].filter((b) => b.dataset.placePage === page);
			(mine.at(-1) ?? all?.[0])?.focus();
		});
	});

	function onPlacingKey(e: KeyboardEvent) {
		if (placing && e.key === 'Escape') {
			e.preventDefault();
			onCancelPlace?.();
		}
	}

	const cardId = (id: string) => `card-${id}`;
	const firstId = $derived(pages[0]?.id);
	const questions = $derived(canvasQuestions(survey));
	const choiceLists = $derived(choiceListsOf(survey));
	const lang = $derived(defaultLanguage(survey));
	const byQuestion = $derived(validationByOwner(survey, diagnostics));

	function goToFirst(id: string, severity: 'error' | 'warning') {
		const d = byQuestion.get(id)?.find((x) => x.severity === severity);
		if (d) onDiagnostic?.(d);
	}
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

{#snippet placeButton(pageId: string, slot: number)}
	{@const where = describeGap(pages, { parent: pageId, slot }, [], 'Place here')}
	<li class="place">
		<button
			type="button"
			class="place-btn"
			data-place-page={pageId}
			data-place-slot={slot}
			aria-label={where}
			title={where}
			onclick={() => onPlace?.({ parent: pageId, slot })}
		>
			<Plus size={16} aria-hidden="true" />
			<span>Place here</span>
		</button>
	</li>
{/snippet}

<!-- svelte-ignore a11y_no_static_element_interactions (pointer drags; the keyboard has Move to… and the toolbox's Shift+Enter) -->
<div
	bind:this={root}
	class="canvas"
	class:is-dragging={dragging}
	{onpointerdown}
	{onpointermove}
	{onpointerup}
	onpointercancel={cancelCardDrag}
	onlostpointercapture={(e) => {
		// It bubbles: a card's grip handing its (touch) capture over to the canvas is not a loss.
		if (e.target === root && cardDrag?.active) cancelCardDrag();
	}}
	{onclickcapture}
	onkeydown={onPlacingKey}
>
	{#if mock}
		<p class="mock-note">Mock data: placeholder cards, not a live survey.</p>
	{/if}
	{#if placing}
		<div class="placing" role="group" aria-label="Placing a question">
			<p>Choose where the {placing} question goes.</p>
			<button type="button" class="cancel-place" onclick={() => onCancelPlace?.()}>Cancel</button>
		</div>
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
				{@const isPage = group.type === 'page'}
				{@const count = group.children?.length ?? 0}
				<div
					class="block"
					data-canvas-page={isPage ? group.id : undefined}
					data-drop={isPage && !count && gap?.parent === group.id ? 'into' : undefined}
				>
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
						{#if isPage && dragging && !count}
							<li class="empty-drop" aria-hidden="true">Drop here: this page is empty</li>
						{/if}
						{#each group.children ?? [] as question, qi (question.id)}
							{@const QIcon = iconFor(question)}
							{@const full = questions.get(question.id)}
							{#if isPage && placing}{@render placeButton(group.id, qi)}{/if}
							<li
								class="card-slot"
								data-canvas-question={isPage ? question.id : undefined}
								data-drop={isPage ? dropEdge(group.id, qi, count) : undefined}
								class:moving={cardDrag?.active && cardDrag.id === question.id}
							>
								{#if onMove && isPage && !placing}
									<span
										class="grip"
										data-drag-handle
										aria-hidden="true"
										title="Drag to move"
										onclick={() => selection.select(question.id)}
									>
										<GripVertical size={16} />
									</span>
								{/if}
								{#if full}
									<QuestionCard
										id={cardId(question.id)}
										question={full}
										schema={cardSchema(schemaFor(schemas, 'question', full))}
										selected={selection.id === question.id}
										{lang}
										{choiceLists}
										diagnostics={byQuestion.get(question.id) ?? null}
										ondiagnostic={onDiagnostic ? (s) => goToFirst(question.id, s) : undefined}
										data-pane-focus={focusMark(question.id)}
										onselect={() => selection.select(question.id)}
									/>
								{:else}
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
								{/if}
								{@render badgeList(question)}
							</li>
						{/each}
						{#if isPage && placing}{@render placeButton(group.id, count)}{/if}
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

{#if cardDrag?.active}
	<div class="ghost" aria-hidden="true" style:left="{cardDrag.x + 12}px" style:top="{cardDrag.y + 12}px">
		<GripVertical size={16} />
		{cardDrag.label}
	</div>
{/if}

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
	/* -- drag and drop (B19) -- */
	.canvas.is-dragging {
		cursor: grabbing;
		user-select: none;
	}
	.card-slot {
		position: relative;
	}
	.card-slot.moving {
		opacity: 0.45;
	}
	/* The insertion line sits in the gap between cards, so nothing shifts while dragging. */
	.card-slot[data-drop='before']::before,
	.card-slot[data-drop='after']::after {
		content: '';
		position: absolute;
		z-index: 3;
		inset-inline: calc(-1 * var(--space-2));
		height: 4px;
		border-radius: var(--radius-full);
		background: var(--color-accent);
		box-shadow: 0 0 0 2px var(--color-bg);
		pointer-events: none;
	}
	.card-slot[data-drop='before']::before {
		top: calc(var(--space-3) / -2 - 2px);
	}
	.card-slot[data-drop='after']::after {
		bottom: calc(var(--space-3) / -2 - 2px);
	}
	.empty-drop {
		display: grid;
		place-items: center;
		min-height: 4.5rem;
		border: 2px dashed var(--color-border-strong);
		border-radius: var(--radius-lg);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.block[data-drop='into'] .empty-drop {
		border-color: var(--color-accent);
		background: var(--color-selected);
		color: var(--color-text);
	}
	.grip {
		position: absolute;
		z-index: 2;
		inset-block-start: var(--space-1);
		inset-inline-end: var(--space-1);
		display: grid;
		place-items: center;
		width: 2.75rem;
		height: 2.75rem;
		border-radius: var(--radius-md);
		color: var(--color-text-muted);
		cursor: grab;
		/* A touch on the grip drags the card instead of scrolling the pane. */
		touch-action: none;
		opacity: 0;
		transition: opacity var(--duration-fast);
	}
	.card-slot:hover .grip,
	.card-slot:focus-within .grip {
		opacity: 1;
	}
	@media (hover: none), (pointer: coarse) {
		.grip {
			opacity: 1;
		}
	}
	.grip:hover {
		background: var(--color-surface-sunken);
		color: var(--color-text);
	}
	.ghost {
		position: fixed;
		z-index: 100;
		display: flex;
		align-items: center;
		gap: var(--space-1);
		max-width: 20rem;
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		box-shadow: var(--shadow-lg);
		color: var(--color-text);
		font-size: var(--text-sm);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		pointer-events: none;
	}
	/* -- tap-to-place (narrow screens) -- */
	.placing {
		position: sticky;
		top: var(--space-2);
		z-index: 4;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		margin-block-end: var(--space-4);
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-accent);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		box-shadow: var(--shadow-lg);
	}
	.placing p {
		margin: 0;
		font-size: var(--text-sm);
	}
	.cancel-place,
	.place-btn {
		min-height: 2.75rem;
		padding: var(--space-1) var(--space-3);
		border-radius: var(--radius-md);
		font-size: var(--text-sm);
	}
	.cancel-place {
		flex: none;
		border: 1px solid var(--color-border-strong);
		background: var(--color-surface);
	}
	.place-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-1);
		width: 100%;
		border: 2px dashed var(--color-accent);
		background: transparent;
		color: var(--color-text);
	}
	.place-btn:hover,
	.place-btn:focus-visible {
		background: var(--color-selected);
	}
	.card[aria-current='true'] {
		border-color: var(--color-accent);
		box-shadow: 0 0 0 1px var(--color-accent);
	}
</style>
