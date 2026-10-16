<script lang="ts">
	import type { LucideIcon } from '@lucide/svelte';
	import type { HTMLButtonAttributes } from 'svelte/elements';
	import Tooltip from './Tooltip.svelte';

	/**
	 * Icon-only button. `label` is required: it is the accessible name and the tooltip.
	 * `shortcut` is shown in the tooltip and exposed as aria-keyshortcuts.
	 */
	type Props = Omit<HTMLButtonAttributes, 'aria-label'> & {
		icon: LucideIcon;
		label: string;
		shortcut?: string;
		/** aria-keyshortcuts value, e.g. "Control+Z Meta+Z". Defaults to none. */
		keyshortcuts?: string;
		tooltipSide?: 'top' | 'bottom' | 'left' | 'right';
		variant?: 'ghost' | 'secondary';
	};

	let {
		icon: Icon,
		label,
		shortcut,
		keyshortcuts,
		tooltipSide = 'bottom',
		variant = 'ghost',
		class: className = '',
		...rest
	}: Props = $props();
</script>

<Tooltip text={label} {shortcut} side={tooltipSide}>
	{#snippet trigger(props)}
		<button
			type="button"
			{...props}
			{...rest}
			class="osp-icon-button {className}"
			data-variant={variant}
			aria-label={label}
			aria-keyshortcuts={keyshortcuts}
		>
			<Icon size={18} aria-hidden="true" />
		</button>
	{/snippet}
</Tooltip>

<style>
	:global(.osp-icon-button) {
		display: inline-grid;
		place-items: center;
		width: var(--control-height);
		height: var(--control-height);
		padding: 0;
		border: 1px solid transparent;
		border-radius: var(--radius-md);
		background: transparent;
		color: var(--color-text);
		cursor: pointer;
		transition: background var(--duration-fast);
	}
	:global(.osp-icon-button[data-variant='secondary']) {
		border-color: var(--color-border-strong);
		background: var(--color-surface-raised);
	}
	:global(.osp-icon-button:hover) {
		background: var(--color-surface-sunken);
	}
	:global(.osp-icon-button:disabled) {
		opacity: 0.55;
		cursor: not-allowed;
	}
	:global(.osp-icon-button[aria-pressed='true']),
	:global(.osp-icon-button[aria-expanded='true']) {
		background: var(--color-selected);
	}
</style>
