<script lang="ts">
	import { tick } from 'svelte';
	import type { StructureActions } from './actions.svelte';
	import type { StructureType } from './ops';

	export interface MenuTarget {
		id: string;
		label: string;
		/** The element the menu opens beside (a row, a heading, a button). */
		anchor: HTMLElement | null;
		/** Where a right-click happened (the menu opens there instead). */
		point?: { x: number; y: number };
	}

	/**
	 * The page/block (and question) context menu (task B20): opened by right-click, the
	 * context-menu key or Shift+F10 on an outline row or canvas heading, or the outline's
	 * Actions button. WAI-ARIA menu: focus moves in, arrows/Home/End move, Enter or Space
	 * runs, Escape or Tab closes and focus goes back to where it was.
	 */
	let {
		target = $bindable(null),
		actions
	}: { target?: MenuTarget | null; actions: StructureActions } = $props();

	interface Item {
		id: string;
		label: string;
		danger?: boolean;
		run: (id: string) => void;
	}

	function itemsFor(type: StructureType | undefined): Item[] {
		if (!type) return [];
		const out: Item[] = [];
		if (type === 'page') out.push({ id: 'add-page', label: 'Add page after', run: (id) => void actions.addPage(id) });
		if (type === 'block') {
			out.push({ id: 'add-page', label: 'Add page', run: (id) => void actions.addPage(id) });
			out.push({ id: 'add-block', label: 'Add block after', run: (id) => void actions.addBlock(id) });
		}
		out.push(
			{ id: 'rename', label: type === 'question' ? 'Edit text…' : 'Rename…', run: (id) => actions.rename(id) },
			{ id: 'duplicate', label: 'Duplicate', run: (id) => void actions.duplicate(id) }
		);
		if (actions.canSaveToBank) out.push({ id: 'save-bank', label: 'Save to bank…', run: (id) => actions.saveToBank(id) });
		out.push({ id: 'delete', label: 'Delete…', danger: true, run: (id) => void actions.remove(id) });
		return out;
	}

	const type = $derived(target ? actions.typeOf(target.id) : undefined);
	const items = $derived(itemsFor(type));
	let menu = $state<HTMLElement | null>(null);
	let pos = $state({ top: 0, left: 0 });
	let returnTo: HTMLElement | null = null;

	$effect(() => {
		if (!target || !menu) return;
		const t = target;
		const m = menu;
		returnTo = document.activeElement instanceof HTMLElement ? document.activeElement : null;
		void tick().then(() => {
			const w = m.offsetWidth;
			const h = m.offsetHeight;
			const r = t.anchor?.getBoundingClientRect();
			let left = t.point?.x ?? r?.left ?? 8;
			let top = t.point?.y ?? (r ? r.bottom + 4 : 8);
			if (top + h > innerHeight - 8) top = Math.max(8, (t.point ? top : (r?.top ?? top)) - h - 4);
			left = Math.max(8, Math.min(left, innerWidth - w - 8));
			pos = { top, left };
			m.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
		});
	});

	function close(restore = true) {
		target = null;
		if (restore && returnTo?.isConnected) returnTo.focus();
		returnTo = null;
	}

	function activate(item: Item) {
		const id = target?.id;
		close();
		if (id) item.run(id);
	}

	function onkeydown(e: KeyboardEvent) {
		const els = [...(menu?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])];
		const i = els.indexOf(document.activeElement as HTMLElement);
		const go = (j: number) => els[(j + els.length) % els.length]?.focus();
		if (e.key === 'ArrowDown') go(i + 1);
		else if (e.key === 'ArrowUp') go(i - 1);
		else if (e.key === 'Home') go(0);
		else if (e.key === 'End') go(els.length - 1);
		else if (e.key === 'Escape') close();
		else if (e.key === 'Tab') close();
		else if (e.key === 'Enter' || e.key === ' ') {
			const item = items[i];
			if (item) activate(item);
		} else return;
		e.preventDefault();
		e.stopPropagation();
	}
</script>

{#if target && items.length}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="scrim" onpointerdown={() => close(false)} oncontextmenu={(e) => (e.preventDefault(), close(false))}></div>
	<ul
		bind:this={menu}
		class="menu"
		role="menu"
		aria-label="Actions for {target.label}"
		style:top="{pos.top}px"
		style:left="{pos.left}px"
		data-testid="structure-menu"
		{onkeydown}
	>
		{#each items as item (item.id)}
			<!-- svelte-ignore a11y_click_events_have_key_events (keys are handled on the menu) -->
			<li role="menuitem" tabindex="-1" class:danger={item.danger} onclick={() => activate(item)}>
				{item.label}
			</li>
		{/each}
	</ul>
{/if}

<style>
	.scrim {
		position: fixed;
		inset: 0;
		z-index: 69;
	}
	.menu {
		position: fixed;
		z-index: 70;
		min-width: 12rem;
		max-width: calc(100vw - 16px);
		margin: 0;
		padding: var(--space-1);
		list-style: none;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		box-shadow: var(--shadow-lg);
	}
	li {
		display: flex;
		align-items: center;
		min-height: 2.75rem;
		padding: 0 var(--space-3);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
		cursor: pointer;
	}
	li:hover,
	li:focus {
		background: var(--color-selected);
	}
	li:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: -2px;
	}
	li.danger {
		color: var(--color-danger);
	}
</style>
