<script lang="ts">
	import type { Snippet } from 'svelte';
	import { cardIcon } from './icons';
	import { isEmptyValue, RichView } from '../richtext';
	import { badgesFor, isFamily, richFor, textFor, withoutCardData } from './logic';
	import type { CardProps } from './types';

	/**
	 * The frame every question card shares (builder-design §2): type + id header, the label
	 * rendered rich (formatting, `${pipes}` as chips; planning/rich-text.md §7), required
	 * marker, badges, and a read-only participant preview.
	 *
	 * Selecting: the label is a real <button> (name = the visible label, plus "selected" when
	 * it is), stretched over the whole card, so a click anywhere or Enter / Space selects.
	 * The preview is `inert`: never focusable or clickable, so Tab goes card to card.
	 * Extra attributes (`id`, `data-pane-focus` …) go on that button: it is the focus target.
	 */
	type Props = CardProps & {
		/** The participant widget; receives a page-unique id for it. */
		preview?: Snippet<[string]>;
		/** Shown instead of a preview, e.g. for an unknown type. */
		notice?: string;
	};

	let {
		question,
		family,
		schema,
		selected = false,
		diagnostics,
		lang = 'en',
		onselect,
		ondiagnostic,
		exportBadges,
		preview,
		notice,
		class: klass,
		...other
	}: Props = $props();

	const fam = $derived(isFamily(family) ? family : null);
	// Everything else is for the select button; `choiceLists` is card data, not an attribute.
	const rest = $derived(withoutCardData(other));

	const uid = $derived(`qc-${String(question?.id ?? 'x').replace(/[^A-Za-z0-9_-]/g, '_')}`);
	const Icon = $derived(cardIcon(schema?.icon, fam));
	const typeLabel = $derived(textFor(schema?.label, lang) || String(question?.type ?? 'Question'));
	const label = $derived(richFor(question?.label, lang));
	const help = $derived(richFor(question?.help, lang));
	const required = $derived(question?.required === true && fam !== 'note');
	const badges = $derived(badgesFor(question, schema, diagnostics));
	const hasBadges = $derived(badges.length > 0 || !!exportBadges);
	// Count badges (B18) are buttons when the caller can go to the property; the messages
	// are their accessible description and tooltip.
	const severityOf = (kind: string) => (kind === 'errors' ? 'error' : kind === 'warnings' ? 'warning' : null);
	const messages = (severity: string) =>
		(Array.isArray(diagnostics) ? diagnostics : [])
			.filter((d) => d?.severity === severity)
			.map((d) => String(d.message ?? ''))
			.join(' ');

	function select() {
		onselect?.(String(question?.id ?? ''));
	}
</script>

<div
	class={['qcard', klass]}
	data-family={fam ?? 'unknown'}
	data-question-card={question?.id}
	data-selected={selected ? '' : undefined}
>
	<div class="head">
		<span class="type"><Icon size={16} aria-hidden="true" />{typeLabel}</span>
		<code class="qid">{question?.id}</code>
		{#if selected}<span class="sel" aria-hidden="true">Selected</span>{/if}
	</div>

	<p class="label" class:note={fam === 'note'}>
		<button
			{...rest}
			type="button"
			class="select"
			aria-current={selected ? 'true' : undefined}
			aria-describedby={hasBadges ? `${uid}-badges` : undefined}
			onclick={select}
		>
			{#if !isEmptyValue(label)}<RichView value={label} inline {lang} />{:else}<span class="empty">Untitled question</span>{/if}
			{#if required}<span class="req" aria-hidden="true">*</span><span class="osp-visually-hidden"
					>(required)</span
				>{/if}{#if selected}<span class="osp-visually-hidden">, selected</span>{/if}
		</button>
	</p>
	{#if !isEmptyValue(help)}<p class="help"><RichView value={help} inline {lang} /></p>{/if}

	{#if hasBadges}
		<ul id="{uid}-badges" class="badges">
			{#each badges as b (b.kind)}
				{@const severity = severityOf(b.kind)}
				{#if severity && ondiagnostic}
					{@const why = messages(severity)}
					<li class="badge count" data-badge={b.kind} data-tone={b.tone}>
						<button
							type="button"
							class="count-btn"
							title={why}
							aria-describedby="{uid}-{b.kind}-why"
							onclick={() => ondiagnostic(severity)}>{b.label}</button
						>
						<span id="{uid}-{b.kind}-why" class="osp-visually-hidden">{why}</span>
					</li>
				{:else}
				<li class="badge" data-badge={b.kind} data-tone={b.tone}>
					<span class="badge-label">{b.label}{#if b.detail}<span class="osp-visually-hidden">:</span>{/if}</span>
					{#if b.detail}<code class="badge-detail">{b.detail}</code>{/if}
				</li>
				{/if}
			{/each}
			{@render exportBadges?.()}
		</ul>
	{/if}

	{#if notice}
		<p class="notice">{notice}</p>
	{:else if preview}
		<div class="preview" inert>{@render preview(`${uid}-preview`)}</div>
	{/if}
</div>

<style>
	.qcard {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		min-inline-size: 0;
		padding: var(--space-3) var(--space-4) var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		background: var(--color-surface-raised);
		box-shadow: var(--shadow-sm);
		color: var(--color-text);
		text-align: start;
	}
	.qcard:hover {
		border-color: var(--color-border-strong);
	}
	.qcard:has(.select:focus-visible) {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}
	.select {
		all: unset;
		cursor: pointer;
		overflow-wrap: anywhere;
	}
	/* Stretch the button's hit area over the whole card. */
	.select::after {
		content: '';
		position: absolute;
		inset: 0;
		z-index: 1;
		border-radius: inherit;
	}
	.qcard[data-selected] {
		border-color: var(--color-accent);
		box-shadow: 0 0 0 2px var(--color-accent);
	}
	.qcard[data-selected]::before {
		content: '';
		position: absolute;
		inset-block: var(--space-2);
		inset-inline-start: -2px;
		inline-size: 4px;
		border-radius: var(--radius-full);
		background: var(--color-accent);
	}
	.head {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-inline-size: 0;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
	}
	.type {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.qid {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-family: var(--font-mono);
	}
	.sel {
		margin-inline-start: auto;
		padding: 0 var(--space-2);
		border-radius: var(--radius-full);
		background: var(--color-accent);
		color: var(--color-on-accent);
		font-weight: var(--weight-bold);
	}
	.label {
		margin: 0;
		font-size: var(--text-lg);
		font-weight: var(--weight-medium);
		line-height: var(--leading-tight);
		overflow-wrap: anywhere;
	}
	.label.note {
		font-size: var(--text-md);
		font-weight: var(--weight-normal);
		line-height: var(--leading-normal);
	}
	.empty {
		color: var(--color-text-muted);
		font-style: italic;
	}
	.req {
		margin-inline-start: var(--space-1);
		color: var(--color-danger);
	}
	.help {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.badges {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1) var(--space-2);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.badges > :global(li) {
		display: inline-flex;
		align-items: baseline;
		gap: var(--space-1);
		max-inline-size: 100%;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-full);
		background: var(--color-surface-sunken);
		color: var(--color-text);
		font-size: var(--text-xs);
		line-height: 1.6;
	}
	.badge[data-tone='danger'] {
		border-color: var(--color-danger);
		color: var(--color-danger);
		font-weight: var(--weight-medium);
	}
	.badge[data-tone='warning'] {
		border-color: var(--color-warning);
		color: var(--color-warning);
		font-weight: var(--weight-medium);
	}
	.badges > li.count {
		position: relative;
		z-index: 2; /* above the stretched select button */
		padding: 0;
	}
	.count-btn {
		padding: 0 var(--space-2);
		border: 0;
		border-radius: inherit;
		background: transparent;
		color: inherit;
		font: inherit;
		cursor: pointer;
	}
	.count-btn:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}
	.badge-label {
		font-weight: var(--weight-medium);
		white-space: nowrap;
	}
	.badge-detail {
		min-inline-size: 0;
		overflow-wrap: anywhere;
		font-family: var(--font-mono);
	}
	.notice {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		font-style: italic;
	}
	.preview {
		padding-block-start: var(--space-2);
		border-block-start: 1px dashed var(--color-border);
		pointer-events: none;
	}
	/* The card shows label and help itself (with pipe tokens); hide the widget's copies. */
	.preview :global(.q-label),
	.preview :global(.q-help) {
		display: none;
	}
</style>
