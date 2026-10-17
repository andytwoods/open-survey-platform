<script lang="ts">
	import { Button } from '@osp/ui-components';
	import { onDestroy } from 'svelte';
	import { toTextParams, type ResultsFilters } from './model';
	import type { ResultsSource } from './results.svelte';
	import type { TextPage } from './types';

	/**
	 * A text question's verbatim answers (task V2): the text endpoint, a page at a time,
	 * with the page's filters. Opened on request, because every read is audited (V-D3).
	 * Free text is shown as typed: never translated, never interpreted as markup.
	 */
	let {
		question,
		label,
		source,
		filters,
		pageSize = 20,
		current = null
	}: {
		question: string;
		label: string;
		source: ResultsSource;
		filters: ResultsFilters;
		pageSize?: number;
		/**
		 * The watermark of the results on screen (task LV3). Answers are never refreshed by
		 * themselves (LV-D8): when it differs from the page's, "New answers · Reload" shows.
		 */
		current?: string | null;
	} = $props();

	let open = $state(false);
	let page = $state<TextPage | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);
	/** Cursors of the pages before this one (the first page has none). */
	let back = $state<(string | undefined)[]>([]);
	let cursor = $state<string | undefined>(undefined);
	let abort: AbortController | null = null;
	const uid = $props.id();

	const params = $derived(toTextParams(filters));
	const paramsKey = $derived(JSON.stringify(params));

	// New filters: start again from the first page.
	let shownKey = '';
	$effect(() => {
		const k = paramsKey;
		if (!open || k === shownKey) return;
		back = [];
		void fetchPage(undefined);
	});

	async function fetchPage(c: string | undefined) {
		abort?.abort();
		const a = new AbortController();
		abort = a;
		loading = true;
		error = null;
		shownKey = paramsKey;
		const r = await source.text(question, { ...params, limit: pageSize, ...(c ? { cursor: c } : {}) }, a.signal);
		if (a.signal.aborted) return;
		loading = false;
		if (r.ok) {
			page = r.data;
			cursor = c;
		} else error = r.message;
	}

	function show() {
		open = true;
		if (!page || shownKey !== paramsKey) {
			back = [];
			void fetchPage(undefined);
		}
	}

	function next() {
		if (!page?.nextCursor) return;
		back = [...back, cursor];
		void fetchPage(page.nextCursor);
	}

	function previous() {
		if (!back.length) return;
		const c = back[back.length - 1];
		back = back.slice(0, -1);
		void fetchPage(c);
	}

	/** Start again from the first page (new answers arrived: LV-D8's manual reload). */
	function reload() {
		back = [];
		void fetchPage(undefined);
	}

	const first = $derived(back.length * pageSize + 1);
	const stale = $derived(!!page && current !== null && page.watermark !== current);
	const fmt = (iso: string | null) => (iso ? iso.slice(0, 16).replace('T', ' ') : '–');

	onDestroy(() => abort?.abort());
</script>

<section class="text-answers" aria-labelledby="{uid}-h">
	<h4 id="{uid}-h">Answers</h4>
	{#if !open}
		<p class="muted">Each view of the answers is recorded in the audit log.</p>
		<Button onclick={show}>Show answers</Button>
	{:else}
		{#if error}
			<p role="alert" class="error">{error}</p>
		{/if}
		{#if page}
			<p class="muted" role="status">
				{#if page.total === 0}
					No answers match the filters.
				{:else}
					Answers {first}–{first + page.items.length - 1} of {page.total}
				{/if}
			</p>
			{#if stale}
				<p class="stale" data-testid="text-stale">
					<span>New answers have arrived. Answers are never refreshed by themselves.</span>
					<Button disabled={loading} onclick={reload}>Reload answers</Button>
				</p>
			{/if}
			{#if page.items.length}
				<!-- A scrolling region takes keyboard focus, so it can be scrolled without a mouse. -->
				<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
				<div class="scroll" role="region" aria-label="Answers to {label}" tabindex="0">
					<table aria-busy={loading}>
						<thead>
							<tr>
								<th scope="col">Answer</th>
								<th scope="col">Version</th>
								<th scope="col">Submitted (UTC)</th>
							</tr>
						</thead>
						<tbody>
							{#each page.items as item (item.responseId)}
								<tr>
									<td class="answer">{item.value}</td>
									<td>{item.version}</td>
									<td class="when">{fmt(item.submittedAt)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
			<div class="pager">
				<Button disabled={!back.length || loading} onclick={previous}>Previous</Button>
				<Button disabled={!page.nextCursor || loading} onclick={next}>Next</Button>
			</div>
		{:else if loading}
			<p role="status" class="muted">Loading answers…</p>
		{/if}
	{/if}
</section>

<style>
	.text-answers {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		align-items: flex-start;
	}
	h4 {
		margin: 0;
		font-size: var(--text-sm);
	}
	.muted {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.error {
		margin: 0;
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
	.scroll {
		width: 100%;
		max-height: 24rem;
		overflow: auto;
	}
	.scroll:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
	}
	th,
	td {
		padding: var(--space-1) var(--space-2);
		border-bottom: 1px solid var(--color-border);
		text-align: start;
		vertical-align: top;
	}
	.answer {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.when {
		white-space: nowrap;
	}
	.pager {
		display: flex;
		gap: var(--space-2);
	}
	.stale {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-3);
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-inline-start: 4px solid var(--color-accent);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		font-size: var(--text-sm);
	}
</style>
