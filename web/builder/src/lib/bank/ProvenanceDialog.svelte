<script lang="ts">
	import { Button, Dialog } from '@osp/ui-components';
	import { untrack } from 'svelte';
	import BankPreview from './BankPreview.svelte';
	import { bank } from './library.svelte';
	import { LICENCE_LABELS, SOURCE_LABELS, type BankItemOut, type SourceRef } from './logic';

	/**
	 * "Details" of an inserted object's provenance: the bank item as inserted (that
	 * version) with its citation and licence, whether a newer version exists, and whether
	 * the inserted content was edited since (checksum). Replace and Detach are offered here
	 * too, for keyboard users who reached the dialog from the line.
	 */
	let {
		request,
		lang = 'en',
		onreplace,
		ondetach,
		onclose
	}: {
		request: { id: string; source: SourceRef } | null;
		lang?: string;
		onreplace?: (id: string, source: SourceRef, version: number) => void;
		ondetach?: (id: string) => void;
		onclose: () => void;
	} = $props();

	let open = $derived(!!request);
	$effect(() => {
		if (!open && untrack(() => request)) onclose();
	});

	let inserted = $state<BankItemOut | null>(null);
	let current = $state<BankItemOut | null>(null);
	let error = $state<string | null>(null);

	$effect(() => {
		const r = request;
		if (!r) return;
		untrack(() => {
			inserted = current = null;
			error = null;
			void (async () => {
				const [a, b] = await Promise.all([bank.get(r.source.bank, r.source.version), bank.get(r.source.bank)]);
				if (request !== r) return;
				if (a.ok) inserted = a.data;
				else if (b.ok) inserted = b.data;
				else error = a.message;
				if (b.ok) current = b.data;
			})();
		});
	});

	const newer = $derived(!!current && !!request && current.version > request.source.version);
	const edited = $derived(!!inserted && !!request?.source.checksum && !!inserted.checksum && inserted.checksum !== request.source.checksum);
	const title = $derived(inserted?.summary.title ?? request?.source.bank ?? '');
</script>

<Dialog bind:open title="From the question bank" size="lg">
	{#if request}
		<div class="body" data-testid="provenance-details">
			<p class="line">
				<strong>{title}</strong>
				{#if inserted?.summary.abbreviation}({inserted.summary.abbreviation}){/if}
				· {SOURCE_LABELS[request.source.library] ?? request.source.library} · version {request.source.version}
				{#if inserted}· {LICENCE_LABELS[inserted.summary.licenceClass] ?? inserted.summary.licenceClass}{/if}
			</p>
			{#if newer && current}
				<p class="note">Version {current.version} is the current one in the bank; this survey holds version {request.source.version}.</p>
			{/if}
			{#if edited}
				<p class="note">The inserted copy was edited after it was inserted (it no longer matches the bank item).</p>
			{/if}
			{#if inserted}
				<BankPreview item={inserted} {lang} />
			{:else if error}
				<p class="error" role="alert">The bank item could not be read: {error}</p>
			{:else}
				<p role="status">Loading…</p>
			{/if}
		</div>
	{/if}
	{#snippet footer()}
		{#if request && ondetach}
			<Button onclick={() => (request && ondetach(request.id), (open = false))}>Detach</Button>
		{/if}
		{#if request && newer && current && onreplace}
			<Button onclick={() => (request && onreplace(request.id, request.source, current!.version), (open = false))}>
				Replace with v{current.version}
			</Button>
		{/if}
		<Button variant="primary" onclick={() => (open = false)}>Close</Button>
	{/snippet}
</Dialog>

<style>
	.body {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.line,
	.note,
	.error {
		margin: 0;
		font-size: var(--text-sm);
	}
	.note {
		color: var(--color-warning);
	}
	.error {
		color: var(--color-danger);
	}
</style>
