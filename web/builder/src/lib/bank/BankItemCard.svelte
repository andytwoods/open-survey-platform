<script lang="ts">
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import type { Snippet } from 'svelte';
	import BankPreview from './BankPreview.svelte';
	import { bank } from './library.svelte';
	import { KIND_LABELS, LICENCE_LABELS, SOURCE_LABELS, type BankItemOut, type BankSummary } from './logic';

	/**
	 * One bank item in a list (question-bank.md §6): title, abbreviation, kind, item count,
	 * licence badge, version, source, and a "newer than inserted" dot when the survey holds
	 * an older version. Expanding it fetches the document and shows the preview. `actions`
	 * renders the caller's buttons (Insert, Edit…, Share…).
	 */
	let {
		summary,
		newer = false,
		lang = 'en',
		compact = false,
		actions
	}: {
		summary: BankSummary;
		newer?: boolean;
		lang?: string;
		compact?: boolean;
		actions?: Snippet<[BankSummary, BankItemOut | null]>;
	} = $props();

	const uid = $props.id();
	let open = $state(false);
	let item = $state<BankItemOut | null>(null);
	let error = $state<string | null>(null);

	async function toggle() {
		open = !open;
		if (open && !item) {
			const r = await bank.get(summary.id);
			if (r.ok) item = r.data;
			else error = r.message;
		}
	}
	const kind = $derived(KIND_LABELS[summary.kind] ?? summary.kind);
	const count = $derived(`${summary.itemCount} item${summary.itemCount === 1 ? '' : 's'}`);
</script>

<article class="item" class:compact data-bank-item={summary.id} data-source={summary.source} aria-labelledby="{uid}-title">
	<div class="row">
		<button
			type="button"
			class="expand"
			aria-expanded={open}
			aria-controls="{uid}-body"
			onclick={toggle}
		>
			<span class="chevron" class:open aria-hidden="true"><ChevronRight size={16} /></span>
			<span class="titles">
				<span id="{uid}-title" class="title">
					{summary.title}
					{#if summary.abbreviation}<span class="abbr">{summary.abbreviation}</span>{/if}
					{#if newer}
						<span class="newer" title="A newer version than the one in this survey">
							<span aria-hidden="true">●</span><span class="osp-visually-hidden">newer version available</span>
						</span>
					{/if}
				</span>
				<span class="meta">
					<span>{kind}</span>
					<span>{count}</span>
					<span>v{summary.version}</span>
					<span>{SOURCE_LABELS[summary.source] ?? summary.source}</span>
					<span class="licence" data-licence={summary.licenceClass}>{LICENCE_LABELS[summary.licenceClass] ?? summary.licenceClass}</span>
					{#if summary.visibility === 'host' && summary.source === 'lab'}<span>Shared with the host</span>{/if}
				</span>
			</span>
		</button>
		{#if actions}<div class="actions">{@render actions(summary, item)}</div>{/if}
	</div>
	<div id="{uid}-body" class="body" hidden={!open}>
		{#if item}
			<BankPreview {item} {lang} {compact} />
		{:else if error}
			<p class="error" role="alert">{error}</p>
		{:else if open}
			<p class="loading" role="status">Loading…</p>
		{/if}
	</div>
</article>

<style>
	.item {
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-start;
		gap: var(--space-1) var(--space-2);
		padding: var(--space-1) var(--space-2) var(--space-1) var(--space-1);
	}
	.expand {
		display: flex;
		flex: 1 1 12rem;
		align-items: flex-start;
		gap: var(--space-1);
		min-width: 0;
		min-height: 2.75rem;
		padding: var(--space-1);
		border: 0;
		border-radius: var(--radius-sm);
		background: none;
		color: inherit;
		font: inherit;
		text-align: start;
		cursor: pointer;
	}
	.expand:hover {
		background: var(--color-surface-sunken);
	}
	.chevron {
		display: inline-grid;
		flex: none;
		place-items: center;
		margin-top: 0.2rem;
		transition: transform var(--duration-fast);
	}
	.chevron.open {
		transform: rotate(90deg);
	}
	.titles {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}
	.title {
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
		overflow-wrap: anywhere;
	}
	.abbr {
		margin-inline-start: var(--space-1);
		color: var(--color-text-muted);
		font-weight: var(--weight-normal);
	}
	.newer {
		margin-inline-start: var(--space-1);
		color: var(--color-warning);
	}
	.meta {
		display: flex;
		flex-wrap: wrap;
		gap: 0 var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.licence {
		padding: 0 var(--space-1);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-full);
	}
	.licence[data-licence='licensed-to-lab'],
	.licence[data-licence='unknown'],
	.licence[data-licence='free-noncommercial'] {
		border-color: var(--color-warning);
	}
	.actions {
		display: flex;
		flex: none;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1);
		margin-inline-start: auto;
	}
	.body {
		padding: 0 var(--space-3) var(--space-3) var(--space-3);
	}
	.compact .body {
		padding-inline: var(--space-2);
	}
	.error {
		margin: 0;
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
	.loading {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
</style>
