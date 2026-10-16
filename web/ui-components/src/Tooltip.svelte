<script lang="ts">
	import { Tooltip } from 'bits-ui';
	import type { Snippet } from 'svelte';

	/**
	 * Wraps a trigger with a text tooltip. The trigger snippet receives the props to
	 * spread onto the focusable element:
	 *   <Tooltip text="Undo">{#snippet trigger(props)}<button {...props}>…</button>{/snippet}</Tooltip>
	 * A tooltip only repeats an accessible name; never put essential information only here.
	 */
	let {
		text,
		shortcut,
		side = 'bottom',
		trigger
	}: {
		text: string;
		shortcut?: string;
		side?: 'top' | 'bottom' | 'left' | 'right';
		trigger: Snippet<[Record<string, unknown>]>;
	} = $props();
</script>

<Tooltip.Provider delayDuration={400}>
	<Tooltip.Root>
		<Tooltip.Trigger>
			{#snippet child({ props })}
				{@render trigger(props)}
			{/snippet}
		</Tooltip.Trigger>
		<Tooltip.Portal>
			<Tooltip.Content class="osp-tooltip" {side} sideOffset={6}>
				<span>{text}</span>
				{#if shortcut}<kbd>{shortcut}</kbd>{/if}
			</Tooltip.Content>
		</Tooltip.Portal>
	</Tooltip.Root>
</Tooltip.Provider>

<style>
	:global(.osp-tooltip) {
		z-index: 70;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-sm);
		background: var(--color-text);
		color: var(--color-bg);
		font-size: var(--text-xs);
		box-shadow: var(--shadow-sm);
	}
	:global(.osp-tooltip kbd) {
		font-family: var(--font-sans);
		opacity: 0.85;
	}
</style>
