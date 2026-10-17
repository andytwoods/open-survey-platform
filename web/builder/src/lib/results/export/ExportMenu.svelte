<script lang="ts">
	import Download from '@lucide/svelte/icons/download';
	import { DropdownMenu } from 'bits-ui';
	import type { ResultsController } from '../results.svelte';
	import type { Card } from '../types';
	import ExportDialog from './ExportDialog.svelte';
	import type { ExportFormat } from './run';

	/**
	 * A card's Export menu (task V4): one entry per format; each opens the export dialog
	 * (settings, caption, final-size preview) with that format chosen.
	 */
	let { card, controller }: { card: Card; controller: ResultsController } = $props();

	const ITEMS: { format: ExportFormat; label: string }[] = [
		{ format: 'png', label: 'PNG image…' },
		{ format: 'svg', label: 'SVG image…' },
		{ format: 'csv', label: 'CSV of the numbers…' },
		{ format: 'vega-lite', label: 'Vega-Lite spec and manifest…' }
	];

	let open = $state(false);
	let format = $state<ExportFormat>('png');
	let pending: ExportFormat | null = null;

	/** Open the dialog once the menu has closed, so focus moves into it, not back to the menu. */
	function afterMenuClose(e: Event) {
		if (!pending) return;
		e.preventDefault();
		format = pending;
		pending = null;
		open = true;
	}
</script>

<DropdownMenu.Root>
	<DropdownMenu.Trigger class="export-trigger" aria-label="Export {card.label || card.name}">
		<Download size={16} aria-hidden="true" />
		<span>Export</span>
	</DropdownMenu.Trigger>
	<DropdownMenu.Portal disabled>
		<DropdownMenu.Content class="export-menu" align="end" sideOffset={4} strategy="fixed" onCloseAutoFocus={afterMenuClose}>
			{#each ITEMS as item (item.format)}
				<DropdownMenu.Item class="export-item" onSelect={() => (pending = item.format)}>{item.label}</DropdownMenu.Item>
			{/each}
		</DropdownMenu.Content>
	</DropdownMenu.Portal>
</DropdownMenu.Root>

<ExportDialog bind:open bind:format {card} {controller} />

<style>
	:global(.export-trigger) {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		min-height: 2.75rem;
		padding: 0 var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
		cursor: pointer;
	}
	:global(.export-trigger:focus-visible) {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}
	:global(.export-menu) {
		z-index: 70;
		min-width: 14rem;
		padding: var(--space-1);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		box-shadow: var(--shadow-lg);
	}
	:global(.export-item) {
		display: flex;
		align-items: center;
		min-height: 2.75rem;
		padding: 0 var(--space-3);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
		cursor: pointer;
	}
	:global(.export-item[data-highlighted]) {
		background: var(--color-selected);
		outline: 2px solid var(--color-focus);
		outline-offset: -2px;
	}
</style>
