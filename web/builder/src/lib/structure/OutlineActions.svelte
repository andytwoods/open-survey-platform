<script lang="ts">
	import Ellipsis from '@lucide/svelte/icons/ellipsis';
	import FilePlus from '@lucide/svelte/icons/file-plus';
	import LayersPlus from '@lucide/svelte/icons/layers-plus';
	import type { StructureActions } from './actions.svelte';
	import type { MenuTarget } from './StructureMenu.svelte';

	/**
	 * Under the outline tree (task B20): "Add page" (after the selected page), "Add block"
	 * and the selected item's actions menu (rename, duplicate, delete).
	 */
	let {
		actions,
		selectedId,
		selectedLabel,
		onmenu
	}: {
		actions: StructureActions;
		selectedId: string | null;
		selectedLabel: string;
		onmenu: (target: MenuTarget) => void;
	} = $props();

	const hasTarget = $derived(!!actions.typeOf(selectedId));
	let more = $state<HTMLButtonElement | null>(null);
</script>

<div class="outline-actions" role="group" aria-label="Pages and blocks">
	<button type="button" class="act" onclick={() => void actions.addPage(selectedId)}>
		<FilePlus size={16} aria-hidden="true" />
		<span>Add page</span>
	</button>
	<button type="button" class="act" onclick={() => void actions.addBlock(selectedId)}>
		<LayersPlus size={16} aria-hidden="true" />
		<span>Add block</span>
	</button>
	<button
		bind:this={more}
		type="button"
		class="act icon"
		aria-haspopup="menu"
		aria-label={hasTarget ? `Actions for ${selectedLabel}` : 'Actions (select a page, block or question first)'}
		disabled={!hasTarget}
		onclick={() => selectedId && onmenu({ id: selectedId, label: selectedLabel, anchor: more })}
	>
		<Ellipsis size={16} aria-hidden="true" />
	</button>
</div>

<style>
	.outline-actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1);
		padding: var(--space-1) var(--space-2) var(--space-2);
	}
	.act {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		min-height: 2.75rem;
		padding: 0 var(--space-2);
		border: 1px dashed var(--color-border-strong);
		border-radius: var(--radius-md);
		background: transparent;
		color: var(--color-text-muted);
		font: inherit;
		font-size: var(--text-sm);
		cursor: pointer;
	}
	.act.icon {
		min-width: 2.75rem;
		justify-content: center;
		border-style: solid;
	}
	.act:hover:not(:disabled) {
		background: var(--color-surface-sunken);
		color: var(--color-text);
	}
	.act:disabled {
		opacity: 0.5;
		cursor: default;
	}
</style>
