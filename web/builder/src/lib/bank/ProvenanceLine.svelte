<script lang="ts">
	import Info from '@lucide/svelte/icons/info';
	import Replace from '@lucide/svelte/icons/replace';
	import Unlink from '@lucide/svelte/icons/unlink';
	import type { ProvenanceInfo } from './provenance.svelte';
	import type { SourceRef } from './logic';

	/**
	 * The small provenance line on an inserted question, page or block (question-bank.md
	 * §6): "PHQ-9 · bundled · v1" with Details, "Replace with v2" when the bank holds a
	 * newer version, and Detach (`clear_source`). Its buttons sit above a card's stretched
	 * select button and never start a card drag (CanvasPane ignores `.provenance`).
	 */
	let {
		id,
		source,
		info,
		ondetails,
		onreplace,
		ondetach
	}: {
		id: string;
		source: SourceRef;
		info: ProvenanceInfo;
		ondetails?: (id: string, source: SourceRef) => void;
		onreplace?: (id: string, source: SourceRef, version: number) => void;
		ondetach?: (id: string) => void;
	} = $props();
</script>

<div class="provenance" data-provenance={id} data-bank={source.bank} data-version={source.version}>
	<span class="label" title="From the question bank">{info.label}</span>
	{#if ondetails}
		<button type="button" class="act" aria-label="Details of {info.title ?? source.bank}" onclick={() => ondetails(id, source)}>
			<Info size={12} aria-hidden="true" /> Details
		</button>
	{/if}
	{#if info.newer && info.current && onreplace}
		<button type="button" class="act newer" aria-label="Replace with version {info.current} of {info.title ?? source.bank}" onclick={() => onreplace(id, source, info.current!)}>
			<Replace size={12} aria-hidden="true" /> Replace with v{info.current}
		</button>
	{/if}
	{#if ondetach}
		<button type="button" class="act" aria-label="Detach {info.title ?? source.bank} from the bank item" onclick={() => ondetach(id)}>
			<Unlink size={12} aria-hidden="true" /> Detach
		</button>
	{/if}
</div>

<style>
	.provenance {
		position: relative;
		z-index: 2;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1) var(--space-2);
		margin: var(--space-1) 0 0;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.label {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.act {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		min-height: 1.75rem;
		padding: 0 var(--space-1);
		border: 1px solid transparent;
		border-radius: var(--radius-sm);
		background: none;
		color: var(--color-text-muted);
		font: inherit;
		font-size: var(--text-xs);
		cursor: pointer;
	}
	.act:hover {
		border-color: var(--color-border);
		color: var(--color-text);
	}
	.act:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}
	.act.newer {
		color: var(--color-warning);
	}
</style>
