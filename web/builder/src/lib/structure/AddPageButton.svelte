<script lang="ts">
	import FilePlus from '@lucide/svelte/icons/file-plus';

	/** The canvas's "Add page" button under a page's cards (task B20): a new page after it. */
	let { pageLabel, onclick }: { pageLabel: string; onclick: () => void } = $props();
</script>

<button type="button" class="add-page" aria-label="Add page after {pageLabel}" {onclick}>
	<FilePlus size={16} aria-hidden="true" />
	<span>Add page</span>
</button>

<style>
	.add-page {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		min-height: 2.75rem;
		margin-top: var(--space-3);
		margin-inline-start: var(--space-2);
		padding: var(--space-1) var(--space-3);
		border: 1px dashed var(--color-border-strong);
		border-radius: var(--radius-md);
		background: transparent;
		color: var(--color-text-muted);
		font: inherit;
		font-size: var(--text-sm);
		cursor: pointer;
	}
	.add-page:hover {
		background: var(--color-surface-sunken);
		color: var(--color-text);
	}
</style>
