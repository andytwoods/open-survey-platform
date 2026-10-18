<script lang="ts">
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import { fragmentItems, fragmentVariables, LICENCE_LABELS, textOf, type BankItemOut } from './logic';

	/**
	 * A bank item's document, read-only (question-bank.md §6): its items (rows and options
	 * at a glance), the scoring variables, the citation, the scoring note and the licence
	 * statement with its link. Used by the Bank section, the Bank page and the provenance
	 * Details dialog.
	 */
	let { item, lang = 'en', compact = false }: { item: BankItemOut; lang?: string; compact?: boolean } = $props();

	const doc = $derived(item.document as Record<string, unknown>);
	const items = $derived(fragmentItems(doc, lang));
	const variables = $derived(fragmentVariables(doc));
	const obj = (k: string) => (doc[k] && typeof doc[k] === 'object' ? (doc[k] as Record<string, unknown>) : null);
	const licence = $derived(obj('licence'));
	const citation = $derived(obj('citation'));
	const scoring = $derived(obj('scoring'));
	const source = $derived(obj('source'));
	const provenance = $derived(obj('provenance'));
	const str = (v: unknown) => (typeof v === 'string' ? v : '');
	const description = $derived(str(doc.description));
	const shown = $derived(compact ? items.slice(0, 6) : items);
</script>

<div class="preview" data-testid="bank-preview">
	{#if description}<p class="desc">{description}</p>{/if}
	<ol class="items" aria-label="Items">
		{#each shown as it (it.id)}
			<li>
				<span class="itype">{it.type}</span>
				<span class="ilabel">{it.label || it.id}</span>
				{#if it.rows?.length}
					<ul class="rows" aria-label="Rows of {it.label || it.id}">
						{#each it.rows as r, i (i)}<li>{r}</li>{/each}
					</ul>
				{/if}
				{#if it.choices?.length && !compact}
					<p class="choices">Options: {it.choices.join(' · ')}</p>
				{/if}
			</li>
		{/each}
	</ol>
	{#if compact && items.length > shown.length}
		<p class="more">… and {items.length - shown.length} more</p>
	{/if}
	{#if variables.length}
		<p class="meta"><strong>Scoring variables:</strong> {variables.join(', ')}</p>
	{/if}
	{#if scoring && str(scoring.text)}
		<p class="meta"><strong>Scoring:</strong> {str(scoring.text)}</p>
	{/if}
	{#if citation && str(citation.text)}
		<p class="meta">
			<strong>Cite:</strong>
			{str(citation.text)}
			{#if str(citation.doi)}
				<a href="https://doi.org/{encodeURI(str(citation.doi))}" target="_blank" rel="noreferrer">
					doi:{str(citation.doi)}
					<ExternalLink size={12} aria-hidden="true" />
					<span class="osp-visually-hidden">(opens in a new tab)</span>
				</a>
			{/if}
		</p>
	{/if}
	{#if licence}
		<p class="meta licence">
			<strong>Licence:</strong>
			<span class="badge" data-licence={str(licence.class)}>{LICENCE_LABELS[str(licence.class)] ?? str(licence.class)}</span>
			{#if str(licence.holder)}<span>{str(licence.holder)}.</span>{/if}
			{#if str(licence.statement)}<q>{str(licence.statement)}</q>{/if}
			{#if str(licence.url)}
				<a href={str(licence.url)} target="_blank" rel="noreferrer">
					Terms page{#if str(licence.evidenceDate)}
						(read {str(licence.evidenceDate)}){/if}
					<ExternalLink size={12} aria-hidden="true" />
					<span class="osp-visually-hidden">(opens in a new tab)</span>
				</a>
			{/if}
		</p>
	{/if}
	{#if source && str(source.url) && !compact}
		<p class="meta">
			<strong>Item text from:</strong>
			<a href={str(source.url)} target="_blank" rel="noreferrer"
				>{str(source.url)} <ExternalLink size={12} aria-hidden="true" /><span class="osp-visually-hidden">(opens in a new tab)</span></a
			>
			{#if str(source.note)}<span>{str(source.note)}</span>{/if}
		</p>
	{/if}
	{#if provenance && provenance.from && typeof provenance.from === 'object' && !compact}
		{@const from = provenance.from as Record<string, unknown>}
		<p class="meta">Copied from {textOf(from.library)} item {textOf(from.id)} v{String(from.version ?? '')}.</p>
	{/if}
</div>

<style>
	.preview {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		min-width: 0;
		font-size: var(--text-sm);
	}
	.desc,
	.meta,
	.more,
	.choices {
		margin: 0;
		overflow-wrap: anywhere;
	}
	.desc {
		color: var(--color-text-muted);
	}
	.items {
		margin: 0;
		padding-inline-start: var(--space-5);
	}
	.items > li {
		margin-block: var(--space-1);
	}
	.itype {
		margin-inline-end: var(--space-2);
		padding: 0 var(--space-1);
		border-radius: var(--radius-sm);
		background: var(--color-surface-sunken);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.rows {
		margin: var(--space-1) 0 0;
		padding-inline-start: var(--space-4);
		color: var(--color-text-muted);
	}
	.choices,
	.more {
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.badge {
		display: inline-block;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-full);
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
	}
	.badge[data-licence='licensed-to-lab'],
	.badge[data-licence='unknown'],
	.badge[data-licence='free-noncommercial'] {
		border-color: var(--color-warning, var(--color-border-strong));
	}
	q {
		display: block;
		margin-top: var(--space-1);
		color: var(--color-text-muted);
		font-style: italic;
	}
	a {
		color: var(--color-link, var(--color-accent));
	}
</style>
