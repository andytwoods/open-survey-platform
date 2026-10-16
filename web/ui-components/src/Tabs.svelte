<script lang="ts" module>
	import type { Snippet } from 'svelte';

	export interface TabItem {
		value: string;
		label: string;
		content: Snippet;
	}
</script>

<script lang="ts">
	import { Tabs } from 'bits-ui';

	/** Tabs with automatic activation: arrow keys move between tabs, Tab enters the panel. */
	let {
		tabs,
		value = $bindable(tabs[0]?.value ?? ''),
		label
	}: {
		tabs: TabItem[];
		value?: string;
		/** Accessible name for the tab list. */
		label: string;
	} = $props();
</script>

<Tabs.Root bind:value class="osp-tabs">
	<Tabs.List class="osp-tabs-list" aria-label={label}>
		{#each tabs as tab (tab.value)}
			<Tabs.Trigger class="osp-tabs-trigger" value={tab.value}>{tab.label}</Tabs.Trigger>
		{/each}
	</Tabs.List>
	{#each tabs as tab (tab.value)}
		<Tabs.Content class="osp-tabs-content" value={tab.value}>
			{@render tab.content()}
		</Tabs.Content>
	{/each}
</Tabs.Root>

<style>
	:global(.osp-tabs-list) {
		display: flex;
		gap: var(--space-1);
		border-bottom: 1px solid var(--color-border);
	}
	:global(.osp-tabs-trigger) {
		margin-bottom: -1px;
		padding: var(--space-2) var(--space-3);
		border: 0;
		border-bottom: 2px solid transparent;
		background: transparent;
		color: var(--color-text-muted);
		font: inherit;
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
		cursor: pointer;
	}
	:global(.osp-tabs-trigger:hover) {
		color: var(--color-text);
	}
	:global(.osp-tabs-trigger[data-state='active']) {
		border-bottom-color: var(--color-accent);
		color: var(--color-text);
	}
	:global(.osp-tabs-content) {
		padding-block: var(--space-3);
	}
</style>
