<script lang="ts">
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import { announce } from '@osp/ui-components';
	import { onDestroy } from 'svelte';
	import { QUESTION_TYPES, type QuestionTypeId } from './catalogue';
	import type { DropTarget } from '../outline/moves';
	import type { TypeDrag } from './type-drag.svelte';

	/**
	 * The question types as a compact toolbox under the outline (the picker's catalogue).
	 * A click (Enter, Space) adds that type to the selected or last page; dragging one onto
	 * the outline inserts it there; Shift+Enter asks where instead (the keyboard way to do
	 * what dragging does). One Tab stop: arrows move between types (a vertical toolbar).
	 * The heading collapses it; `collapsed` starts true where room is short.
	 */
	let {
		drag,
		collapsed = $bindable(false),
		onadd,
		oninsert,
		onchoosewhere
	}: {
		drag: TypeDrag;
		collapsed?: boolean;
		/** Add to the selected (or last) page. */
		onadd: (type: QuestionTypeId) => void;
		/** Insert at a gap in a page (a drop). */
		oninsert: (type: QuestionTypeId, target: DropTarget) => void;
		/** Ask where to put it (keyboard). */
		onchoosewhere: (type: QuestionTypeId) => void;
	} = $props();

	const uid = $props.id();
	const listId = `osp-toolbox-${uid}`;
	const hintId = `osp-toolbox-hint-${uid}`;
	const buttonId = (id: string) => `osp-toolbox-${uid}-${id}`;

	let activeIndex = $state(0);

	function focusAt(i: number) {
		const n = QUESTION_TYPES.length;
		activeIndex = ((i % n) + n) % n;
		document.getElementById(buttonId(QUESTION_TYPES[activeIndex].id))?.focus();
	}

	function onkeydown(e: KeyboardEvent, i: number) {
		if (pointer?.active && e.key === 'Escape') {
			e.preventDefault();
			e.stopPropagation();
			return cancel();
		}
		if (e.ctrlKey || e.metaKey || e.altKey) return;
		if (e.key === 'Enter' && e.shiftKey) {
			e.preventDefault();
			onchoosewhere(QUESTION_TYPES[i].id);
			return;
		}
		if (e.key === 'ArrowDown' || e.key === 'ArrowRight') focusAt(i + 1);
		else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') focusAt(i - 1);
		else if (e.key === 'Home') focusAt(0);
		else if (e.key === 'End') focusAt(QUESTION_TYPES.length - 1);
		else return;
		e.preventDefault();
	}

	// -- drag (pointer) ------------------------------------------------------------------

	const DRAG_THRESHOLD = 4;
	let pointer = $state<{
		type: QuestionTypeId;
		el: HTMLElement;
		pointerId: number;
		startX: number;
		startY: number;
		x: number;
		y: number;
		active: boolean;
	} | null>(null);
	let suppressClick = false;

	function onpointerdown(e: PointerEvent, type: QuestionTypeId) {
		if (e.button !== 0 || e.shiftKey || e.ctrlKey || e.metaKey) return;
		const el = e.currentTarget as HTMLElement;
		pointer = { type, el, pointerId: e.pointerId, startX: e.clientX, startY: e.clientY, x: 0, y: 0, active: false };
	}

	function onpointermove(e: PointerEvent) {
		const p = pointer;
		if (!p || e.pointerId !== p.pointerId) return;
		if (!p.active) {
			if (Math.abs(e.clientX - p.startX) < DRAG_THRESHOLD && Math.abs(e.clientY - p.startY) < DRAG_THRESHOLD) return;
			p.el.setPointerCapture?.(e.pointerId);
			p.active = true;
			drag.start(p.type);
			const name = QUESTION_TYPES.find((t) => t.id === p.type)?.name ?? p.type;
			announce(`Dragging ${name}. Drop it on a page or between questions. Escape cancels.`);
			window.addEventListener('keydown', onWindowKey, true);
		}
		p.x = e.clientX;
		p.y = e.clientY;
		if (drag.move(e.clientX, e.clientY) && drag.hit) announce(drag.hit.description);
	}

	function onpointerup(e: PointerEvent) {
		const p = pointer;
		if (!p || e.pointerId !== p.pointerId) return;
		pointer = null;
		if (!p.active) return;
		stopListening();
		suppressClick = true;
		setTimeout(() => (suppressClick = false), 0);
		if (p.el.hasPointerCapture?.(e.pointerId)) p.el.releasePointerCapture(e.pointerId);
		const hit = drag.end();
		if (!hit) return announce('Not added: drop it on a page or between questions.');
		oninsert(p.type, hit.hit.target);
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

	function onclick(type: QuestionTypeId, i: number) {
		activeIndex = i;
		if (suppressClick) {
			suppressClick = false;
			return;
		}
		onadd(type);
	}

	const ghost = $derived(pointer?.active ? QUESTION_TYPES.find((t) => t.id === pointer!.type) : undefined);
</script>

<section class="toolbox" aria-labelledby="{listId}-heading">
	<h2 id="{listId}-heading" class="heading">
		<button
			type="button"
			class="toggle"
			aria-expanded={!collapsed}
			aria-controls={listId}
			onclick={() => (collapsed = !collapsed)}
		>
			<span class="chevron" class:open={!collapsed} aria-hidden="true"><ChevronRight size={16} /></span>
			Question types
		</button>
	</h2>
	<div id={listId} class="body" hidden={collapsed}>
		<p id={hintId} class="hint">Click to add, or drag onto the outline. Shift+Enter: choose where.</p>
		<div
			class="types"
			role="toolbar"
			aria-label="Add a question of type"
			aria-orientation="vertical"
		>
			{#each QUESTION_TYPES as t, i (t.id)}
				{@const Icon = t.icon}
				<button
					id={buttonId(t.id)}
					type="button"
					class="type"
					class:dragging={pointer?.active && pointer.type === t.id}
					tabindex={i === activeIndex ? 0 : -1}
					data-type={t.id}
					aria-label="Add {t.name} question"
					aria-describedby={hintId}
					title={t.description}
					onclick={() => onclick(t.id, i)}
					onkeydown={(e) => onkeydown(e, i)}
					onpointerdown={(e) => onpointerdown(e, t.id)}
					{onpointermove}
					{onpointerup}
					onpointercancel={cancel}
				>
					<span class="icon" aria-hidden="true"><Icon size={16} /></span>
					<span class="name">{t.name}</span>
				</button>
			{/each}
		</div>
	</div>
</section>

{#if ghost && pointer}
	{@const Icon = ghost.icon}
	<div class="ghost" aria-hidden="true" style:left="{pointer.x + 12}px" style:top="{pointer.y + 12}px">
		<Icon size={16} />
		{ghost.name}
	</div>
{/if}

<style>
	.toolbox {
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
		padding: 0 var(--space-2) var(--space-2);
	}
	.hint {
		margin: 0 var(--space-1) var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.types {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(8rem, 1fr));
		gap: 2px;
	}
	.type {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-width: 0;
		min-height: 2.75rem;
		padding: 0 var(--space-2);
		border: 1px solid transparent;
		border-radius: var(--radius-md);
		background: none;
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
		text-align: start;
		cursor: grab;
		/* Vertical swipes still scroll the pane; a sideways drag picks the type up. */
		touch-action: pan-y;
		user-select: none;
	}
	.type:hover {
		border-color: var(--color-border);
		background: var(--color-surface-sunken);
	}
	.type.dragging {
		opacity: 0.55;
		cursor: grabbing;
	}
	.icon {
		display: inline-grid;
		place-items: center;
		flex: none;
		width: 1.75rem;
		height: 1.75rem;
		border-radius: var(--radius-sm);
		background: var(--color-surface-sunken);
	}
	.name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.ghost {
		position: fixed;
		z-index: 100;
		display: flex;
		align-items: center;
		gap: var(--space-1);
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		box-shadow: var(--shadow-lg);
		color: var(--color-text);
		font-size: var(--text-sm);
		pointer-events: none;
	}
</style>
