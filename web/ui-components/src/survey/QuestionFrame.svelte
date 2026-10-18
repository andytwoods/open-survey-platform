<script lang="ts" module>
	/** What a widget needs from its frame to wire up labels and descriptions. */
	export interface FrameContext {
		/** id of the labelled control (for `kind: 'field'`). */
		controlId: string;
		/** id of the visible question label (for aria-labelledby). */
		labelId: string;
		/**
		 * For `kind: 'field'`: set (to `labelId`) when the label holds block content and is a
		 * `<div>` rather than a `<label for>`, so the control must name itself with
		 * `aria-labelledby` (planning/rich-text.md §7); undefined when `<label for>` names it.
		 */
		labelledBy: string | undefined;
		/** ids of help + error, or undefined. Put on the control (or the group). */
		describedBy: string | undefined;
		invalid: boolean;
	}

	/**
	 * field     one control, labelled by <label for>
	 * group     a widget that names itself with aria-labelledby (e.g. a radiogroup)
	 * fieldset  several controls: <fieldset> + <legend>
	 * note      text only, no control
	 */
	export type FrameKind = 'field' | 'group' | 'fieldset' | 'note';
</script>

<script lang="ts">
	import CircleAlert from '@lucide/svelte/icons/circle-alert';
	import { onMount, type Snippet } from 'svelte';
	import { announce } from '../live-region.svelte';
	import { dirFor, fill, isEmptyText, isInline, messagesFor, plainText } from './locale';
	import RichInline from './RichInline.svelte';
	import RichText from './RichText.svelte';
	import type { Text, WidgetMessages } from './types';

	type Props = {
		id: string;
		label: Text;
		help?: Text;
		required?: boolean;
		error?: string | null;
		disabled?: boolean;
		lang?: string;
		revealed?: boolean;
		messages?: Partial<WidgetMessages>;
		kind?: FrameKind;
		children?: Snippet<[FrameContext]>;
	};

	let {
		id,
		label,
		help,
		required = false,
		error,
		disabled = false,
		lang,
		revealed = false,
		messages,
		kind = 'field',
		children
	}: Props = $props();

	const m = $derived(messagesFor(messages));
	const helpId = $derived(`${id}-help`);
	const errorId = $derived(`${id}-error`);
	const hasHelp = $derived(!isEmptyText(help));
	const hasError = $derived(!!error && kind !== 'note');
	// A label with block content (several paragraphs, a list, a heading) cannot live in a
	// <label>: it becomes a <div id> the control points at with aria-labelledby.
	const inlineLabel = $derived(isInline(label));
	const ctx: FrameContext = $derived({
		controlId: `${id}-input`,
		labelId: `${id}-label`,
		labelledBy: kind === 'field' && !inlineLabel ? `${id}-label` : undefined,
		describedBy: [hasHelp && helpId, hasError && errorId].filter(Boolean).join(' ') || undefined,
		invalid: hasError
	});

	// Conditional reveal: announce once per appearance (a polite live region, §6 Focus).
	onMount(() => {
		if (revealed) announce(fill(m.revealed, { label: plainText(label) }));
	});
</script>

{#snippet labelContent(inline: boolean)}
	{#if inline}<RichInline text={label} {messages} />{:else}<RichText text={label} {messages} />{/if}
	{#if required && kind !== 'note'}
		<span class="req" aria-hidden="true">*</span>
		<span class="osp-visually-hidden">({m.required})</span>
	{/if}
{/snippet}

{#snippet below()}
	{#if hasHelp}
		{#if isInline(help)}<p id={helpId} class="q-help"><RichInline text={help} {messages} /></p>{:else}<div
				id={helpId}
				class="q-help"
			>
				<RichText text={help} {messages} />
			</div>{/if}
	{/if}
	{#if hasError}
		<p id={errorId} class="q-error">
			<CircleAlert class="q-error-icon" aria-hidden="true" />
			<span>{error}</span>
		</p>
	{/if}
{/snippet}

<div
	class="osp-q"
	class:revealed
	data-kind={kind}
	data-invalid={hasError ? '' : undefined}
	data-question={id}
	{lang}
	dir={dirFor(lang)}
>
	{#if kind === 'fieldset'}
		<fieldset class="q-fieldset" aria-describedby={ctx.describedBy} {disabled}>
			<!-- A legend holds phrasing content: block content is flattened inline. -->
			<legend id={ctx.labelId} class="q-label">{@render labelContent(true)}</legend>
			{@render below()}
			{@render children?.(ctx)}
		</fieldset>
	{:else}
		{#if kind === 'field' && inlineLabel}
			<label id={ctx.labelId} for={ctx.controlId} class="q-label">{@render labelContent(true)}</label>
		{:else}
			<div id={ctx.labelId} class="q-label" class:q-note={kind === 'note'}>
				{@render labelContent(false)}
			</div>
		{/if}
		{@render below()}
		{@render children?.(ctx)}
	{/if}
</div>

<style>
	/*
	 * Survey widget tokens, derived from tokens.css. They inherit into every widget inside
	 * the frame. Sizes that are accessibility rules (§6) live only here.
	 */
	.osp-q {
		/* Touch targets ≥ 44×44 CSS px (WCAG 2.5.5). */
		--survey-target-size: 2.75rem;
		/* Text inputs ≥ 16 px so iOS never zooms on focus. */
		--survey-input-font-size: max(16px, var(--text-md));
		--survey-gap: var(--space-3);
		--survey-control-border: 1px solid var(--color-border-strong);
		--survey-indicator-size: 1.25rem;
		/* Narrowest row-label column before a Matrix falls back to cards. */
		--survey-matrix-label-min: 8rem;
		--survey-track-size: 0.375rem;
		--survey-thumb-size: 1.5rem;
		--survey-reveal-duration: calc(var(--duration-fast) * 2);

		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		min-inline-size: 0;
		max-inline-size: 100%;
		overflow-wrap: anywhere;
		hyphens: auto;
		color: var(--color-text);
		font-size: var(--text-md);
		line-height: var(--leading-normal);
	}
	.q-fieldset {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		min-inline-size: 0;
		margin: 0;
		padding: 0;
		border: 0;
	}
	.q-label {
		padding: 0;
		font-size: var(--text-lg);
		font-weight: var(--weight-medium);
		line-height: var(--leading-tight);
	}
	.q-note {
		font-weight: var(--weight-normal);
	}
	.req {
		color: var(--color-danger);
		margin-inline-start: var(--space-1);
	}
	.q-help {
		margin: 0;
		color: var(--color-text-muted);
	}
	.q-error {
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
		margin: 0;
		color: var(--color-danger);
		font-weight: var(--weight-medium);
	}
	.q-error :global(.q-error-icon) {
		flex: none;
		inline-size: 1.25em;
		block-size: 1.25em;
		margin-block-start: 0.125em;
	}
	.revealed {
		animation: q-reveal var(--survey-reveal-duration) ease-out;
	}
	@keyframes q-reveal {
		from {
			opacity: 0;
			transform: translateY(calc(var(--space-2) * -1));
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.revealed {
			animation: none;
		}
	}
</style>
