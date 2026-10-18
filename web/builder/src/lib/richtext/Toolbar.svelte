<script lang="ts" module>
	/** What a toolbar control asks the editor to do. */
	export type ToolbarAction =
		| { kind: 'bold' }
		| { kind: 'italic' }
		| { kind: 'link' }
		| { kind: 'bulletList' }
		| { kind: 'orderedList' }
		| { kind: 'heading'; level: 0 | 1 | 2 | 3 }
		| { kind: 'break' }
		| { kind: 'pipe' }
		| { kind: 'clear' }
		| { kind: 'undo' }
		| { kind: 'redo' };
</script>

<script lang="ts">
	import Bold from '@lucide/svelte/icons/bold';
	import Braces from '@lucide/svelte/icons/braces';
	import CornerDownLeft from '@lucide/svelte/icons/corner-down-left';
	import Ellipsis from '@lucide/svelte/icons/ellipsis';
	import Italic from '@lucide/svelte/icons/italic';
	import Link from '@lucide/svelte/icons/link';
	import List from '@lucide/svelte/icons/list';
	import ListOrdered from '@lucide/svelte/icons/list-ordered';
	import Redo from '@lucide/svelte/icons/redo';
	import RemoveFormatting from '@lucide/svelte/icons/remove-formatting';
	import Undo from '@lucide/svelte/icons/undo';
	import { IconButton } from '@osp/ui-components';
	import { DropdownMenu } from 'bits-ui';
	import type { ToolbarState } from './tiptap';
	import { allows, type Level } from './levels';

	/**
	 * The formatting toolbar (planning/rich-text.md §9): the WAI-ARIA toolbar pattern (one
	 * tab stop, arrow keys, Home/End, Escape back to the text), ui-components IconButtons
	 * with `aria-pressed` for the toggles, a Select for the heading level (block fields only),
	 * and under 480 px the rarely used controls fold into a "More" menu. Buttons keep the
	 * editor's selection (mousedown is prevented), so a click never blurs the text.
	 * Written by hand rather than with bits-ui's Toolbar: its `child` props and the
	 * IconButton's Tooltip both want to own the button's id.
	 */
	let {
		level,
		state: tb,
		pipes,
		disabled = false,
		label,
		onAction,
		onEscape
	}: {
		level: Level;
		state: ToolbarState;
		/** Whether the field may pipe answers in (shows "Insert answer"). */
		pipes: boolean;
		disabled?: boolean;
		/** Names the toolbar after its field: "Formatting for Question text". */
		label: string;
		onAction: (action: ToolbarAction) => void;
		/** Escape (or a menu closing): put focus back in the text. */
		onEscape: () => void;
	} = $props();

	const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);
	const mod = isMac ? '⌘' : 'Ctrl+';
	const keys = (k: string) => `Control+${k} Meta+${k}`;

	let root = $state<HTMLDivElement | null>(null);
	let compact = $state(false);
	let active = $state(0);
	let menuOpen = $state(false);

	// Under 480 px (a phone: the properties pane is a drawer) the rarely used controls fold
	// into a menu; wider than that the toolbar wraps to a second row inside its pane.
	$effect(() => {
		if (typeof matchMedia === 'undefined') return;
		const mq = matchMedia('(max-width: 479.98px)');
		const apply = () => (compact = mq.matches);
		apply();
		mq.addEventListener('change', apply);
		return () => mq.removeEventListener('change', apply);
	});

	const items = () => (root ? [...root.querySelectorAll<HTMLElement>('[data-tb]')] : []);

	/** Move focus to the toolbar (Alt+F10): the item that last had it. */
	export function focus() {
		const list = items();
		(list[Math.min(active, list.length - 1)] ?? list[0])?.focus();
	}

	function onkeydown(e: KeyboardEvent) {
		if (menuOpen) return;
		const t = e.target as HTMLElement;
		if (e.key === 'Escape') {
			e.preventDefault();
			e.stopPropagation();
			onEscape();
			return;
		}
		if (t.tagName === 'SELECT' && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) return;
		const list = items();
		const at = list.indexOf(t.closest<HTMLElement>('[data-tb]')!);
		let next = -1;
		if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (at + 1) % list.length;
		else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (at - 1 + list.length) % list.length;
		else if (e.key === 'Home') next = 0;
		else if (e.key === 'End') next = list.length - 1;
		if (next < 0 || !list[next]) return;
		e.preventDefault();
		active = next;
		list[next].focus();
	}

	function onfocusin(e: FocusEvent) {
		const t = (e.target as HTMLElement).closest<HTMLElement>('[data-tb]');
		if (t) active = Math.max(0, items().indexOf(t));
	}

	// Keep the selection in the text: a mouse click on a button never takes focus.
	const keep = (e: MouseEvent) => e.preventDefault();
	const tabindex = (i: number) => (i === active ? 0 : -1);

	type Spec = { key: string; icon: typeof Bold; label: string; shortcut?: string; keyshortcuts?: string; pressed?: boolean; disabled?: boolean; action: ToolbarAction; rare?: boolean };
	const specs = $derived.by((): Spec[] => {
		const out: Spec[] = [
			{ key: 'bold', icon: Bold, label: 'Bold', shortcut: `${mod}B`, keyshortcuts: keys('b'), pressed: tb.bold, action: { kind: 'bold' } },
			{ key: 'italic', icon: Italic, label: 'Italic', shortcut: `${mod}I`, keyshortcuts: keys('i'), pressed: tb.italic, action: { kind: 'italic' } },
			// No shortcut: Ctrl/Cmd+K is the builder's command palette.
			{ key: 'link', icon: Link, label: 'Link', pressed: tb.link, action: { kind: 'link' } }
		];
		if (allows(level, 'list')) {
			out.push(
				{ key: 'ul', icon: List, label: 'Bulleted list', pressed: tb.bulletList, action: { kind: 'bulletList' } },
				{ key: 'ol', icon: ListOrdered, label: 'Numbered list', pressed: tb.orderedList, action: { kind: 'orderedList' } }
			);
		}
		if (pipes) out.push({ key: 'pipe', icon: Braces, label: 'Insert answer', action: { kind: 'pipe' } });
		if (allows(level, 'paragraphs')) {
			out.push({ key: 'break', icon: CornerDownLeft, label: 'Line break', shortcut: 'Shift+Enter', keyshortcuts: 'Shift+Enter', action: { kind: 'break' }, rare: true });
		}
		out.push(
			{ key: 'clear', icon: RemoveFormatting, label: 'Clear formatting', action: { kind: 'clear' }, rare: true },
			{ key: 'undo', icon: Undo, label: 'Undo', shortcut: `${mod}Z`, keyshortcuts: keys('z'), disabled: !tb.canUndo, action: { kind: 'undo' }, rare: true },
			{ key: 'redo', icon: Redo, label: 'Redo', shortcut: `${mod}Y`, keyshortcuts: `${keys('y')} Control+Shift+z Meta+Shift+z`, disabled: !tb.canRedo, action: { kind: 'redo' }, rare: true }
		);
		return out;
	});
	const shown = $derived(compact ? specs.filter((s) => !s.rare) : specs);
	const folded = $derived(compact ? specs.filter((s) => s.rare) : []);
	const headingValue = $derived(String(tb.heading));
</script>

<!-- The toolbar itself is not a tab stop (tabindex -1): its controls are, one at a time. -->
<div
	bind:this={root}
	class="osp-rt-toolbar"
	role="toolbar"
	tabindex="-1"
	aria-label={label}
	aria-orientation="horizontal"
	data-compact={compact || undefined}
	{onkeydown}
	{onfocusin}
>
	{#each shown as s, i (s.key)}
		<IconButton
			icon={s.icon}
			label={s.label}
			shortcut={s.shortcut}
			keyshortcuts={s.keyshortcuts}
			aria-pressed={s.pressed === undefined ? undefined : s.pressed}
			disabled={disabled || s.disabled}
			data-tb={s.key}
			tabindex={tabindex(i)}
			tooltipSide="top"
			onmousedown={keep}
			onclick={() => onAction(s.action)}
		/>
	{/each}
	{#if allows(level, 'heading')}
		<select
			class="osp-rt-style"
			aria-label="Text style"
			data-tb="heading"
			tabindex={tabindex(shown.length)}
			{disabled}
			value={headingValue}
			onmousedown={(e) => e.stopPropagation()}
			onchange={(e) => onAction({ kind: 'heading', level: Number(e.currentTarget.value) as 0 | 1 | 2 | 3 })}
		>
			<option value="0">Paragraph</option>
			<option value="1">Heading 1</option>
			<option value="2">Heading 2</option>
			<option value="3">Heading 3</option>
		</select>
	{/if}
	{#if folded.length}
		<DropdownMenu.Root bind:open={menuOpen}>
			<DropdownMenu.Trigger
				class="osp-icon-button"
				aria-label="More formatting"
				data-tb="more"
				tabindex={tabindex(shown.length + (allows(level, 'heading') ? 1 : 0))}
				{disabled}
				onmousedown={keep}
			>
				<Ellipsis size={18} aria-hidden="true" />
			</DropdownMenu.Trigger>
			<DropdownMenu.Portal disabled>
				<DropdownMenu.Content class="osp-rt-menu" align="end" sideOffset={4} strategy="fixed" onCloseAutoFocus={(e) => { e.preventDefault(); onEscape(); }}>
					{#each folded as s (s.key)}
						<DropdownMenu.Item class="osp-rt-menu-item" disabled={s.disabled} onSelect={() => onAction(s.action)}>
							<s.icon size={16} aria-hidden="true" />
							<span>{s.label}</span>
							{#if s.shortcut}<kbd>{s.shortcut}</kbd>{/if}
						</DropdownMenu.Item>
					{/each}
				</DropdownMenu.Content>
			</DropdownMenu.Portal>
		</DropdownMenu.Root>
	{/if}
</div>

<style>
	.osp-rt-toolbar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 2px;
		padding: 2px;
		border-block-end: 1px solid var(--color-border);
	}
	.osp-rt-toolbar :global(.osp-icon-button) {
		min-width: var(--control-height);
		min-height: var(--control-height);
	}
	.osp-rt-toolbar :global(.osp-icon-button:focus-visible),
	.osp-rt-style:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: -2px;
	}
	.osp-rt-style {
		height: var(--control-height);
		max-width: 8.5rem;
		padding: 0 var(--space-1);
		border: 1px solid transparent;
		border-radius: var(--radius-md);
		background: transparent;
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
	}
	.osp-rt-style:hover {
		background: var(--color-surface-sunken);
	}
	:global(.osp-rt-menu) {
		z-index: 70;
		min-width: 12rem;
		padding: var(--space-1);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		box-shadow: var(--shadow-lg);
	}
	:global(.osp-rt-menu-item) {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-height: 2.25rem;
		padding: 0 var(--space-3);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
		cursor: pointer;
	}
	:global(.osp-rt-menu-item[data-highlighted]) {
		background: var(--color-selected);
	}
	:global(.osp-rt-menu-item[data-disabled]) {
		opacity: 0.55;
		cursor: not-allowed;
	}
	:global(.osp-rt-menu-item kbd) {
		margin-inline-start: auto;
		color: var(--color-text-muted);
		font-family: var(--font-sans);
		font-size: var(--text-xs);
	}
</style>
