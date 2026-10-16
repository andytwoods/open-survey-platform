<script lang="ts">
	import { Tabs } from '@osp/ui-components';
	import type { MockNode } from '../mock/survey';
	import { findNode } from '../outline/tree-nav';
	import type { SelectionStore } from '../selection.svelte';

	/** Shows what is selected. The schema-driven property panel is task B4. */
	let { roots, selection }: { roots: MockNode[]; selection: SelectionStore } = $props();

	const node = $derived(selection.id ? findNode(roots, selection.id) : undefined);
	let tab = $state('details');
</script>

<div class="properties">
	<h2 id="properties-heading" tabindex="-1" data-pane-focus>Properties</h2>
	{#if node}
		{#snippet details()}
			<dl data-testid="selected-details">
				<dt>Id</dt>
				<dd><code>{node.id}</code></dd>
				<dt>Type</dt>
				<dd>{node.type}</dd>
				{#if node.family}
					<dt>Family</dt>
					<dd>{node.family}</dd>
				{/if}
				<dt>Label</dt>
				<dd>{node.label}</dd>
			</dl>
		{/snippet}
		{#snippet diagnostics()}
			<p class="muted">No diagnostics. Validation is not connected yet.</p>
		{/snippet}
		<Tabs
			label="Property sections"
			bind:value={tab}
			tabs={[
				{ value: 'details', label: 'Details', content: details },
				{ value: 'diagnostics', label: 'Diagnostics', content: diagnostics }
			]}
		/>
	{:else}
		<p class="muted">Select an item in the outline or on the canvas to see its properties.</p>
	{/if}
</div>

<style>
	.properties {
		padding: var(--space-3) var(--space-4);
	}
	h2 {
		margin: 0 0 var(--space-3);
		font-size: var(--text-sm);
		font-weight: var(--weight-bold);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-muted);
	}
	dl {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: var(--space-2) var(--space-4);
		margin: 0;
		font-size: var(--text-sm);
	}
	dt {
		color: var(--color-text-muted);
	}
	dd {
		margin: 0;
		overflow-wrap: anywhere;
	}
	code {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		padding: 0.1rem 0.3rem;
		border-radius: var(--radius-sm);
		background: var(--color-surface-sunken);
	}
	.muted {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
</style>
