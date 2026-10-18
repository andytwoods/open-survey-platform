<script lang="ts">
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import Copy from '@lucide/svelte/icons/copy';
	import { editingLanguage, setReferenceOpen } from '../translations/editing-language.svelte';
	import type { RichValue } from './convert';
	import RichView from './RichView.svelte';

	/**
	 * The reference strip above a field edited in a non-default language (planning/rich-text.md
	 * §5): the default-language value rendered read-only (formatting and chips visible), so the
	 * translator sees what to translate, with *Copy from <default>* to start from it. Collapsing
	 * it collapses every strip (one shared, remembered choice).
	 */
	let {
		id,
		value,
		language,
		inline = false,
		same = false,
		onCopy
	}: {
		/** The field's id; the strip's own ids derive from it. */
		id: string;
		/** The default-language value. */
		value: RichValue;
		/** The default language's tag. */
		language: string;
		inline?: boolean;
		/** The translation already equals the reference: nothing to copy. */
		same?: boolean;
		onCopy: () => void;
	} = $props();

	const open = $derived(editingLanguage.referenceOpen);
	const bodyId = $derived(`${id}-ref`);
</script>

<div class="osp-rt-ref" data-testid="reference-strip" data-open={open || undefined}>
	<div class="osp-rt-ref-head">
		<button
			type="button"
			class="osp-rt-ref-toggle"
			aria-expanded={open}
			aria-controls={bodyId}
			onclick={() => setReferenceOpen(!open)}
		>
			<span class="chev" class:open aria-hidden="true"><ChevronRight size={14} /></span>
			Reference ({language})
		</button>
		<button type="button" class="osp-rt-ref-copy" disabled={same} onclick={onCopy}>
			<Copy size={14} aria-hidden="true" />
			Copy from {language}
		</button>
	</div>
	<div id={bodyId} class="osp-rt-ref-body" hidden={!open} lang={language}>
		<RichView {value} {inline} />
	</div>
</div>

<style>
	.osp-rt-ref {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		padding: var(--space-1) var(--space-2);
		border: 1px dashed var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-sunken);
		font-size: var(--text-sm);
	}
	.osp-rt-ref-head {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-1) var(--space-2);
	}
	.osp-rt-ref-toggle,
	.osp-rt-ref-copy {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		min-height: 2rem;
		padding: 0 var(--space-1);
		border: 1px solid transparent;
		border-radius: var(--radius-sm);
		background: none;
		color: var(--color-text-muted);
		font: inherit;
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		cursor: pointer;
	}
	.osp-rt-ref-copy {
		color: var(--color-text);
		border-color: var(--color-border-strong);
		padding-inline: var(--space-2);
		background: var(--color-surface-raised);
	}
	.osp-rt-ref-toggle:hover,
	.osp-rt-ref-copy:hover:not(:disabled) {
		background: var(--color-surface);
		color: var(--color-text);
	}
	.osp-rt-ref-copy:disabled {
		cursor: not-allowed;
		opacity: 0.6;
	}
	.osp-rt-ref-toggle:focus-visible,
	.osp-rt-ref-copy:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}
	.chev {
		display: inline-flex;
		transition: transform 120ms;
	}
	.chev.open {
		transform: rotate(90deg);
	}
	.osp-rt-ref-body {
		padding: 0 var(--space-1) var(--space-1);
		color: var(--color-text);
		line-height: 1.4;
	}
	.osp-rt-ref-body[hidden] {
		display: none;
	}
</style>
