<script lang="ts">
	import type { HTMLInputAttributes, HTMLTextareaAttributes } from 'svelte/elements';

	/**
	 * The one text box every survey widget uses (internal). Font size ≥ 16 px, height ≥ the
	 * touch target, and `multiline` grows with its content instead of scrolling.
	 */
	type Props = {
		value: string;
		multiline?: boolean;
		/** Width hint in characters (e.g. 4 for a day field). Full width when omitted. */
		chars?: number;
		invalid?: boolean;
		ref?: HTMLInputElement | HTMLTextAreaElement | null;
		oninput?: (value: string) => void;
	} & Omit<HTMLInputAttributes & HTMLTextareaAttributes, 'value' | 'oninput'>;

	let {
		value,
		multiline = false,
		chars,
		invalid = false,
		ref = $bindable(null),
		oninput,
		...rest
	}: Props = $props();

	// Auto-grow fallback for browsers without `field-sizing: content`.
	function grow(el: HTMLTextAreaElement) {
		if (typeof CSS !== 'undefined' && CSS.supports?.('field-sizing', 'content')) return;
		el.style.blockSize = 'auto';
		el.style.blockSize = `${el.scrollHeight + (el.offsetHeight - el.clientHeight)}px`;
	}

	$effect(() => {
		void value;
		if (multiline && ref instanceof HTMLTextAreaElement) grow(ref);
	});
</script>

{#if multiline}
	<textarea
		bind:this={ref}
		class="osp-survey-text"
		class:sized={chars !== undefined}
		style:--chars={chars}
		aria-invalid={invalid ? 'true' : undefined}
		{value}
		oninput={(e) => {
			grow(e.currentTarget);
			oninput?.(e.currentTarget.value);
		}}
		{...rest}
	></textarea>
{:else}
	<input
		bind:this={ref}
		class="osp-survey-text"
		class:sized={chars !== undefined}
		style:--chars={chars}
		aria-invalid={invalid ? 'true' : undefined}
		{value}
		oninput={(e) => oninput?.(e.currentTarget.value)}
		{...rest}
	/>
{/if}

<style>
	.osp-survey-text {
		box-sizing: border-box;
		inline-size: 100%;
		max-inline-size: 100%;
		min-block-size: var(--survey-target-size);
		padding-block: var(--space-2);
		padding-inline: var(--space-3);
		border: var(--survey-control-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font-family: inherit;
		font-size: var(--survey-input-font-size);
		line-height: var(--leading-normal);
	}
	.sized {
		/* chars of content + padding + border; never wider than the column. */
		inline-size: calc(var(--chars) * 1ch + var(--space-3) * 2 + 2px);
		min-inline-size: var(--survey-target-size);
	}
	textarea.osp-survey-text {
		min-block-size: calc(var(--survey-target-size) * 2);
		resize: vertical;
		field-sizing: content;
		overflow-wrap: break-word;
	}
	.osp-survey-text:disabled {
		background: var(--color-surface-sunken);
		color: var(--color-text-muted);
		cursor: not-allowed;
	}
	.osp-survey-text[aria-invalid='true'] {
		border-color: var(--color-danger);
		box-shadow: inset 0 0 0 1px var(--color-danger);
	}
	.osp-survey-text:focus-visible {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 2px;
	}
</style>
