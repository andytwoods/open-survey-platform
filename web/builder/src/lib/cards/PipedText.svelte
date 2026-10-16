<script lang="ts">
	import { pipeSegments } from './logic';

	/** Text with `${id}` pipes shown as tokens (the builder never resolves them). */
	let { text }: { text: string } = $props();
	const segments = $derived(pipeSegments(text));
</script>

{#each segments as seg, i (i)}{#if seg.kind === 'pipe'}<span class="pipe" title="Piped answer of {seg.id}"
			>$&#123;{seg.id}&#125;</span
		>{:else}{seg.text}{/if}{/each}

<style>
	.pipe {
		display: inline-block;
		padding: 0 var(--space-1);
		border: 1px solid var(--color-accent);
		border-radius: var(--radius-sm);
		background: var(--color-accent-subtle);
		color: var(--color-text);
		font-family: var(--font-mono, ui-monospace, monospace);
		font-size: 0.875em;
		font-weight: var(--weight-normal);
		line-height: 1.4;
		white-space: nowrap;
	}
</style>
