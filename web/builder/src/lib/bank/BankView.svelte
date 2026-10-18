<script lang="ts">
	import Download from '@lucide/svelte/icons/download';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import Upload from '@lucide/svelte/icons/upload';
	import { Button, Tabs, announce } from '@osp/ui-components';
	import { onMount } from 'svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import type { Diagnostic } from '../sync/transport';
	import BankItemCard from './BankItemCard.svelte';
	import LicensedWizard from './LicensedWizard.svelte';
	import { bank, type BankFile } from './library.svelte';
	import { exportFileName, labelDiff, LICENCE_LABELS, parseTags, type BankItemOut, type BankSummary, type BankVersion } from './logic';

	/**
	 * The Bank page (question-bank.md §6): the lab's items (search, edit metadata, versions
	 * with a plain diff, share with the host or take back, delete, export), import a
	 * `*.osp-bank.json` file, the bundled library with its licence evidence and "Save a copy
	 * to my bank", and the "Add a licensed instrument privately" wizard over the stubs.
	 * Editors manage; owners share and add licensed instruments; everyone may look.
	 */
	const uid = $props.id();
	const id = (s: string) => `bank-${uid}-${s}`;

	let tab = $state('lab');
	let q = $state('');
	let kind = $state<'' | 'question' | 'page' | 'block'>('');
	let message = $state<{ kind: 'ok' | 'error'; text: string } | null>(null);
	let busy = $state(false);
	let timer: ReturnType<typeof setTimeout> | undefined;

	function search() {
		void bank.search({ q: q.trim() || undefined, kind: kind || undefined, pageSize: 200 });
	}
	function later() {
		clearTimeout(timer);
		timer = setTimeout(search, 250);
	}
	onMount(() => {
		search();
		void bank.loadStubs();
		return () => clearTimeout(timer);
	});

	const labItems = $derived((bank.list?.items ?? []).filter((i) => i.source === 'lab'));
	const hostItems = $derived((bank.list?.items ?? []).filter((i) => i.source === 'host'));
	const bundled = $derived((bank.list?.items ?? []).filter((i) => i.source === 'bundled'));

	function done(kind: 'ok' | 'error', text: string) {
		message = { kind, text };
		announce(text, kind === 'error' ? 'assertive' : 'polite');
	}
	async function run(fn: () => Promise<void>) {
		busy = true;
		try {
			await fn();
		} finally {
			busy = false;
		}
	}

	// -- edit metadata ----------------------------------------------------------------------
	let editing = $state<{ id: string; title: string; abbreviation: string; description: string; tags: string } | null>(null);
	function startEdit(s: BankSummary) {
		editing = { id: s.id, title: s.title, abbreviation: s.abbreviation ?? '', description: s.description ?? '', tags: s.tags.join(', ') };
	}
	async function saveEdit(e: SubmitEvent) {
		e.preventDefault();
		const ed = editing;
		if (!ed) return;
		await run(async () => {
			const r = await bank.update(ed.id, {
				title: ed.title.trim(),
				abbreviation: ed.abbreviation.trim() || null,
				description: ed.description.trim() || null,
				tags: parseTags(ed.tags)
			});
			if (!r.ok) return done('error', r.message);
			bank.replace(r.data.summary);
			editing = null;
			done('ok', `${r.data.summary.title} updated.`);
		});
	}

	// -- versions ----------------------------------------------------------------------------
	let versionsOf = $state<{ summary: BankSummary; versions: BankVersion[]; docs: SvelteMap<number, BankItemOut> } | null>(null);
	let compare = $state<number | null>(null);
	async function showVersions(s: BankSummary) {
		await run(async () => {
			const r = await bank.versions(s.id);
			if (!r.ok) return done('error', r.message);
			const docs = new SvelteMap<number, BankItemOut>();
			const cur = await bank.get(s.id);
			if (cur.ok) docs.set(cur.data.version, cur.data);
			versionsOf = { summary: s, versions: [...r.data].sort((a, b) => b.version - a.version), docs };
			compare = null;
		});
	}
	async function pickCompare(v: number) {
		const vo = versionsOf;
		if (!vo) return;
		if (!vo.docs.has(v)) {
			const r = await bank.get(vo.summary.id, v);
			if (r.ok) vo.docs.set(v, r.data);
		}
		compare = v;
	}
	const diff = $derived.by(() => {
		const vo = versionsOf;
		if (!vo || compare === null) return null;
		const older = vo.docs.get(compare)?.document;
		const newer = vo.docs.get(vo.summary.version)?.document;
		return older && newer ? labelDiff(older, newer) : null;
	});

	// -- share, delete, export, copy ------------------------------------------------------------
	let relicense = $state<BankSummary | null>(null);
	async function share(s: BankSummary, visibility: 'lab' | 'host', licenceClass?: string) {
		await run(async () => {
			const r = await bank.share(s.id, visibility, licenceClass);
			if (!r.ok) {
				if (r.code === 'bank.not_shareable' && visibility === 'host' && !licenceClass) {
					relicense = s;
					return;
				}
				return done('error', r.message);
			}
			relicense = null;
			bank.replace(r.data.summary);
			done('ok', visibility === 'host' ? `${s.title} is now shared with every lab on this host.` : `${s.title} is lab-only again.`);
		});
	}
	let confirmDelete = $state<string | null>(null);
	async function remove(s: BankSummary) {
		await run(async () => {
			const r = await bank.remove(s.id);
			confirmDelete = null;
			if (!r.ok) return done('error', r.message);
			bank.drop(s.id);
			done('ok', `${s.title} deleted. Surveys that inserted it keep their provenance.`);
		});
	}
	async function exportItem(s: BankSummary) {
		await run(async () => {
			const r = await bank.exportFile(s.id);
			if (!r.ok) return done('error', r.message);
			download(exportFileName(s), r.data);
			done('ok', `${s.title} exported${r.data.private ? ' (private backup: holds a licensed item)' : ''}.`);
		});
	}
	function download(name: string, file: BankFile) {
		const blob = new Blob([JSON.stringify(file, null, 2)], { type: 'application/json' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = name;
		document.body.append(a);
		a.click();
		a.remove();
		setTimeout(() => URL.revokeObjectURL(url), 0);
	}
	async function copy(s: BankSummary) {
		await run(async () => {
			const r = await bank.copy(s.id);
			if (!r.ok) return done('error', r.message);
			done('ok', `A copy of ${s.title} is in your lab's bank (editable, remembers where it came from).`);
			search();
			tab = 'lab';
		});
	}

	// -- import ------------------------------------------------------------------------------
	let importFile = $state<{ name: string; file: Record<string, unknown>; private: boolean } | null>(null);
	let importError = $state<string | null>(null);
	let importAttest = $state(false);
	let importProblems = $state<Diagnostic[]>([]);
	async function onFile(e: Event) {
		const input = e.currentTarget as HTMLInputElement;
		const f = input.files?.[0];
		input.value = '';
		importError = null;
		importProblems = [];
		importAttest = false;
		if (!f) return;
		if (f.size > 4 * 1024 * 1024) return void (importError = 'That file is too large for a bank file (4 MB at most).');
		try {
			const parsed: unknown = JSON.parse(await f.text());
			if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed) || (parsed as { bankFile?: unknown }).bankFile !== 'osp-bank-file/0.1') {
				importError = 'That is not an osp-bank-file/0.1 document.';
				return;
			}
			importFile = { name: f.name, file: parsed as Record<string, unknown>, private: (parsed as { private?: unknown }).private === true };
		} catch {
			importError = 'That file is not JSON.';
		}
	}
	async function doImport() {
		const f = importFile;
		if (!f) return;
		await run(async () => {
			const r = await bank.importFile(f.file, importAttest);
			if (!r.ok) {
				importError = r.message;
				importProblems = r.diagnostics ?? [];
				return;
			}
			importFile = null;
			done('ok', `${r.data.items.length} item${r.data.items.length === 1 ? '' : 's'} imported from ${f.name}.`);
			search();
		});
	}

	// -- licensed instruments ------------------------------------------------------------------
	let wizardOpen = $state(false);
	let wizardStub = $state<string | null>(null);
	function openWizard(stub: string | null) {
		wizardStub = stub;
		wizardOpen = true;
	}
	function created(item: BankItemOut) {
		done('ok', `${item.summary.title} is in your lab's bank, licensed to this lab.`);
		search();
		tab = 'lab';
	}
	const canManage = $derived(bank.canManage);
	const canShare = $derived(bank.canShare);
</script>

<div class="page">
	<header class="head">
		<h2 id="bank-heading" tabindex="-1">Question bank</h2>
		<p class="lede">
			Your lab's saved questions, pages and blocks, items other labs share on this host, and the bundled instruments. Insert any of
			them from the editor's Bank section; a card remembers which item and version it came from.
		</p>
	</header>
	{#if bank.error}
		<p class="status error" role="alert">{bank.error}</p>
	{:else if !bank.list}
		<p class="status" role="status">Loading…</p>
	{/if}
	{#if message}
		<p class="status" class:error={message.kind === 'error'} role="status" data-testid="bank-message">{message.text}</p>
	{/if}

	{#snippet labTab()}
		<section class="section" aria-labelledby={id('lab-h')}>
			<div class="toolbar">
				<h3 id={id('lab-h')}>My lab's items</h3>
				<label class="search">
					<span class="osp-visually-hidden">Search</span>
					<input type="search" placeholder="Search title, text, tags…" bind:value={q} oninput={later} autocomplete="off" />
				</label>
				<label>
					<span class="osp-visually-hidden">Kind</span>
					<select bind:value={kind} onchange={search}>
						<option value="">Any kind</option>
						<option value="question">Questions</option>
						<option value="page">Pages</option>
						<option value="block">Blocks</option>
					</select>
				</label>
				{#if canManage}
					<label class="import">
						<Upload size={14} aria-hidden="true" />
						Import a bank file…
						<input type="file" accept=".json,application/json" class="osp-visually-hidden" onchange={onFile} />
					</label>
				{/if}
			</div>
			{#if !canManage && bank.list}
				<p class="note">Only owners and editors can save, edit, import or delete items. You can look and insert.</p>
			{/if}
			{#if importError}
				<p class="status error" role="alert">
					{importError}
					{#if importProblems.length}<span>{importProblems[0].message}</span>{/if}
				</p>
			{/if}
			{#if importFile}
				<div class="import-box" role="group" aria-label="Import {importFile.name}">
					<p>
						<strong>{importFile.name}</strong>: {(importFile.file.items as unknown[] | undefined)?.length ?? 0} item(s).
						{#if importFile.private}This file holds a licensed instrument: only an owner who attests the lab holds the licence may import it.{/if}
					</p>
					{#if importFile.private}
						<label class="attest"><input type="checkbox" bind:checked={importAttest} /> Our lab holds the licence for the instrument(s) in this file.</label>
					{/if}
					<div class="row">
						<Button variant="primary" disabled={busy || (importFile.private && !importAttest)} onclick={doImport}>Import</Button>
						<Button onclick={() => (importFile = null)}>Cancel</Button>
					</div>
				</div>
			{/if}
			{#if bank.list && labItems.length === 0}
				<p class="note">No items yet. In the editor, open a question, page or block's menu and choose "Save to bank…".</p>
			{/if}
			<ul class="list" aria-label="My lab's bank items">
				{#each labItems as s (s.id)}
					<li>
						<BankItemCard summary={s}>
							{#snippet actions(summary)}
								{#if summary.canEdit}
									<Button size="sm" disabled={busy} onclick={() => startEdit(summary)}>Edit…</Button>
									<Button size="sm" disabled={busy} onclick={() => void showVersions(summary)}>Versions</Button>
									{#if canShare}
										{#if summary.visibility === 'host'}
											<Button size="sm" disabled={busy} onclick={() => void share(summary, 'lab')}>Stop sharing</Button>
										{:else}
											<Button size="sm" disabled={busy} onclick={() => void share(summary, 'host')}>Share with host</Button>
										{/if}
									{/if}
									<Button size="sm" disabled={busy} aria-label="Export {summary.title}" onclick={() => void exportItem(summary)}>
										<Download size={14} aria-hidden="true" /> Export
									</Button>
									{#if confirmDelete === summary.id}
										<span class="confirm" role="group" aria-label="Delete {summary.title}?">
											<Button size="sm" variant="danger" disabled={busy} onclick={() => void remove(summary)}>Delete</Button>
											<Button size="sm" onclick={() => (confirmDelete = null)}>Keep</Button>
										</span>
									{:else}
										<Button size="sm" variant="ghost" disabled={busy} onclick={() => (confirmDelete = summary.id)}>Delete…</Button>
									{/if}
								{:else}
									<Button size="sm" disabled={busy} onclick={() => void showVersions(summary)}>Versions</Button>
								{/if}
							{/snippet}
						</BankItemCard>
						{#if editing?.id === s.id}
							<form class="edit" onsubmit={saveEdit} aria-label="Edit {s.title}">
								<div class="two">
									<label class="field"><span>Title</span><input type="text" bind:value={editing.title} required maxlength="200" /></label>
									<label class="field"><span>Abbreviation</span><input type="text" bind:value={editing.abbreviation} maxlength="40" /></label>
								</div>
								<label class="field"><span>Description</span><textarea rows="2" bind:value={editing.description}></textarea></label>
								<label class="field"><span>Tags</span><input type="text" bind:value={editing.tags} /></label>
								<div class="row">
									<Button variant="primary" type="submit" disabled={busy}>Save</Button>
									<Button onclick={() => (editing = null)}>Cancel</Button>
								</div>
							</form>
						{/if}
						{#if relicense?.id === s.id}
							<div class="relicense" role="group" aria-label="Share {s.title}">
								<p>
									Say what licence the item is under before sharing it. Its class is <strong>{LICENCE_LABELS[s.licenceClass] ?? s.licenceClass}</strong>.
									If these are your lab's own words, share them under CC BY 4.0.
								</p>
								<div class="row">
									<Button variant="primary" disabled={busy} onclick={() => void share(s, 'host', 'cc-by-4.0')}>These are our own words: share under CC BY 4.0</Button>
									<Button onclick={() => (relicense = null)}>Cancel</Button>
								</div>
							</div>
						{/if}
						{#if versionsOf?.summary.id === s.id}
							<div class="versions" role="group" aria-label="Versions of {s.title}">
								<ol class="vlist">
									{#each versionsOf.versions as v (v.version)}
										<li>
											<span><strong>v{v.version}</strong> {v.title} · {v.createdBy} · {new Date(v.createdAt).toLocaleDateString()}</span>
											{#if v.version !== versionsOf.summary.version}
												<Button size="sm" onclick={() => void pickCompare(v.version)}>Compare with current</Button>
											{:else}
												<span class="current">current</span>
											{/if}
										</li>
									{/each}
								</ol>
								{#if compare !== null}
									{#if diff}
										<p class="diffline"><strong>v{compare} → v{versionsOf.summary.version}:</strong>
											{#if !diff.added.length && !diff.removed.length}the item texts are the same (other properties may differ).{/if}
										</p>
										{#if diff.added.length}<p class="diffline">Added: {diff.added.join(' · ')}</p>{/if}
										{#if diff.removed.length}<p class="diffline">Removed: {diff.removed.join(' · ')}</p>{/if}
									{:else}
										<p class="diffline" role="status">Loading…</p>
									{/if}
								{/if}
								<div class="row"><Button size="sm" onclick={() => (versionsOf = null)}>Close</Button></div>
							</div>
						{/if}
					</li>
				{/each}
			</ul>
			{#if hostItems.length}
				<h3>Shared by other labs on this host</h3>
				<ul class="list" aria-label="Items shared on this host">
					{#each hostItems as s (s.id)}
						<li>
							<BankItemCard summary={s}>
								{#snippet actions(summary)}
									{#if canManage}<Button size="sm" disabled={busy} onclick={() => void copy(summary)}>Save a copy to my bank</Button>{/if}
								{/snippet}
							</BankItemCard>
						</li>
					{/each}
				</ul>
			{/if}
		</section>
	{/snippet}

	{#snippet libraryTab()}
		<section class="section" aria-labelledby={id('lib-h')}>
			<h3 id={id('lib-h')}>Bundled instruments</h3>
			<p class="note">
				Validated instruments whose item text may be redistributed (public domain or CC0), with the rights holder's statement and the
				page it was read on. Read-only: "Save a copy to my bank" makes an editable lab version that remembers where it came from.
			</p>
			<ul class="list" aria-label="Bundled instruments">
				{#each bundled as s (s.id)}
					<li>
						<BankItemCard summary={s}>
							{#snippet actions(summary)}
								{#if canManage}<Button size="sm" disabled={busy} onclick={() => void copy(summary)}>Save a copy to my bank</Button>{/if}
							{/snippet}
						</BankItemCard>
					</li>
				{/each}
			</ul>
		</section>
	{/snippet}

	{#snippet licensedTab()}
		<section class="section" aria-labelledby={id('lic-h')}>
			<div class="toolbar">
				<h3 id={id('lic-h')}>Licensed instruments</h3>
				{#if canShare}
					<Button variant="primary" onclick={() => openWizard(null)}>Add a licensed instrument…</Button>
				{/if}
			</div>
			<p class="note">
				Instruments the platform may not bundle: proprietary ones (BDI-II, STAI, HADS…) and ones free for research whose text may not
				be redistributed. Each stub carries the citation, the holder's page, the response format and the scoring recipe, and no item
				text. A lab that holds a licence pastes its own copy of the items; the result is a private, licensed-to-lab bank item with
				scoring for free.{#if !canShare} Only a lab owner can add one.{/if}
			</p>
			{#if bank.stubs}
				<ul class="list stubs" aria-label="Instrument stubs">
					{#each bank.stubs as s (s.id)}
						<li class="stub" data-stub={s.id}>
							<div class="stub-head">
								<span class="stitle">{s.title} <span class="abbr">{s.abbreviation}</span></span>
								<span class="smeta">
									{s.itemCount} items · {s.response.min}–{s.response.max}
									{s.response.kind === 'per-item' ? '(item-specific options)' : ''} ·
									<span class="terms" data-terms={s.terms}>{s.terms === 'licensed' ? 'Licence required' : 'Ask the rights holder'}</span>
								</span>
							</div>
							<p class="sdesc">{s.description}</p>
							<p class="scite">
								{s.citation.text}
								{#if s.holder.url}
									<a href={s.holder.url} target="_blank" rel="noreferrer">{s.holder.name} <ExternalLink size={12} aria-hidden="true" /><span class="osp-visually-hidden">(opens in a new tab)</span></a>
								{:else}
									<span>{s.holder.name}.</span>
								{/if}
							</p>
							{#if canShare}
								<div class="row"><Button size="sm" onclick={() => openWizard(s.id)}>Add our copy…</Button></div>
							{/if}
						</li>
					{/each}
				</ul>
			{:else}
				<p class="status" role="status">Loading the stubs…</p>
			{/if}
		</section>
	{/snippet}

	<Tabs
		label="Question bank"
		bind:value={tab}
		tabs={[
			{ value: 'lab', label: 'Lab bank', content: labTab },
			{ value: 'library', label: 'Bundled library', content: libraryTab },
			{ value: 'licensed', label: 'Licensed instruments', content: licensedTab }
		]}
	/>
</div>

{#if bank.stubs}
	<LicensedWizard bind:open={wizardOpen} stubs={bank.stubs} initialStub={wizardStub} oncreated={created} />
{/if}

<style>
	.page {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		max-width: 64rem;
		margin: 0 auto;
		padding: var(--space-4);
	}
	.head h2 {
		margin: 0 0 var(--space-1);
	}
	.lede,
	.note,
	.status {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.status.error {
		color: var(--color-danger);
	}
	.section {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding-block: var(--space-3);
	}
	.section h3 {
		margin: 0;
		font-size: var(--text-md);
	}
	.toolbar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
	}
	.toolbar h3 {
		margin-inline-end: auto;
	}
	.toolbar label {
		min-width: 0;
	}
	.toolbar .search {
		flex: 1 1 12rem;
	}
	.toolbar input[type='search'],
	.toolbar select {
		width: 100%;
		min-height: 2.5rem;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
	}
	.import {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		min-height: 2.5rem;
		padding: 0 var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		font-size: var(--text-sm);
		cursor: pointer;
	}
	.import:has(:focus-visible) {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}
	.list {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.edit,
	.relicense,
	.versions,
	.import-box {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin-top: var(--space-1);
		padding: var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-sunken);
		font-size: var(--text-sm);
	}
	.relicense p,
	.import-box p,
	.diffline {
		margin: 0;
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}
	.field > span {
		font-weight: var(--weight-medium);
	}
	.two {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
		gap: var(--space-2);
	}
	.edit input,
	.edit textarea {
		width: 100%;
		min-height: 2.5rem;
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.confirm {
		display: inline-flex;
		gap: var(--space-1);
	}
	.attest {
		display: flex;
		gap: var(--space-2);
		align-items: baseline;
	}
	.vlist {
		margin: 0;
		padding-inline-start: var(--space-4);
	}
	.vlist li {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		min-height: 2.5rem;
	}
	.current {
		color: var(--color-text-muted);
	}
	.stub {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		font-size: var(--text-sm);
	}
	.stub-head {
		display: flex;
		flex-direction: column;
	}
	.stitle {
		font-weight: var(--weight-medium);
	}
	.abbr {
		color: var(--color-text-muted);
		font-weight: var(--weight-normal);
	}
	.smeta,
	.sdesc,
	.scite {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.terms[data-terms='licensed'] {
		color: var(--color-warning);
	}
	a {
		color: var(--color-accent);
	}
	@media (max-width: 480px) {
		.page {
			padding: var(--space-2);
		}
	}
</style>
