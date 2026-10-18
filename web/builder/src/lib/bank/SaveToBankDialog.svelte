<script lang="ts">
	import { Button, Dialog, announce } from '@osp/ui-components';
	import { untrack } from 'svelte';
	import { findObject } from '../model/outline';
	import type { SurveyStore } from '../sync/survey-store.svelte';
	import type { Diagnostic } from '../sync/transport';
	import { bank } from './library.svelte';
	import { KIND_LABELS, parseTags, SAVE_LICENCES, sourceOf, type BankKind, type BankPreviewOut } from './logic';

	export interface SaveRequest {
		id: string;
		type: BankKind;
		name: string;
	}

	/**
	 * "Save to bank…" (question-bank.md §6): title, abbreviation, tags, description and
	 * licence class (default: not stated, with why a shared item needs one); a preview of
	 * what travels with the part (items, shared choice lists, scoring variables) and what
	 * would be cut (references outside it), from `POST /api/bank/preview`. For a part that
	 * came from one of the lab's own bank items, "Save as a new version of…" is offered.
	 */
	let {
		request,
		store,
		canLicense = false,
		onclose
	}: {
		request: SaveRequest | null;
		store: SurveyStore;
		/** The owner may mark an item as licensed to the lab. */
		canLicense?: boolean;
		onclose: (saved: { id: string; title: string } | null) => void;
	} = $props();

	const uid = $props.id();
	const id = (s: string) => `save-bank-${uid}-${s}`;
	let open = $derived(!!request);
	$effect(() => {
		if (!open && untrack(() => request)) onclose(null);
	});

	let title = $state('');
	let abbreviation = $state('');
	let tags = $state('');
	let description = $state('');
	let licence = $state('unknown');
	let mode = $state<'new' | 'version'>('new');
	let preview = $state<BankPreviewOut | null>(null);
	let previewError = $state<string | null>(null);
	let existing = $state<{ id: string; title: string; version: number } | null>(null);
	let busy = $state(false);
	let error = $state<string | null>(null);
	let problems = $state<Diagnostic[]>([]);

	$effect(() => {
		const r = request;
		if (!r) return;
		untrack(() => {
			title = r.name;
			abbreviation = '';
			tags = '';
			description = '';
			licence = 'unknown';
			mode = 'new';
			preview = null;
			previewError = null;
			existing = null;
			error = null;
			problems = [];
			void load(r);
		});
	});

	async function load(r: SaveRequest) {
		store.flushBuffers();
		await store.settled();
		const [p, src] = await Promise.all([bank.preview(store.surveyId, r.id), Promise.resolve(sourceOf(findObject(store.survey, r.id)))]);
		if (request?.id !== r.id) return;
		if (p.ok) preview = p.data;
		else previewError = p.message;
		if (src && src.library === 'lab') {
			const got = await bank.get(src.bank);
			if (got.ok && got.data.summary.canEdit && got.data.summary.kind === r.type) {
				existing = { id: src.bank, title: got.data.summary.title, version: got.data.summary.version };
			}
		}
	}

	const kindName = $derived(request ? KIND_LABELS[request.type].toLowerCase() : 'item');
	const warnings = $derived(preview?.diagnostics ?? []);
	const licences = $derived(SAVE_LICENCES.filter((l) => canLicense || l.value !== 'licensed-to-lab'));
	const licenceHint = $derived(SAVE_LICENCES.find((l) => l.value === licence)?.hint ?? '');

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		const r = request;
		if (!r || busy) return;
		if (!title.trim()) {
			error = 'Give the item a title.';
			return;
		}
		busy = true;
		error = null;
		problems = [];
		const body = {
			surveyId: store.surveyId,
			targetId: r.id,
			title: title.trim(),
			abbreviation: abbreviation.trim() || null,
			description: description.trim() || null,
			tags: parseTags(tags),
			licence: { class: licence }
		};
		const out =
			mode === 'version' && existing
				? await bank.newVersion(existing.id, body)
				: await bank.save(body);
		busy = false;
		if (!out.ok) {
			error = out.message;
			problems = out.diagnostics ?? [];
			announce(out.message, 'assertive');
			return;
		}
		const saved = out.data.item.summary;
		const cut = out.data.diagnostics.length;
		const what = mode === 'version' ? `Saved as version ${saved.version} of ${saved.title}.` : `Saved ${saved.title} to the bank.`;
		announce(cut ? `${what} ${cut} reference${cut === 1 ? '' : 's'} outside it ${cut === 1 ? 'was' : 'were'} cut.` : what);
		void bank.search({ pageSize: 50 });
		onclose({ id: saved.id, title: saved.title });
	}
</script>

<Dialog bind:open title="Save {kindName} to the bank" size="md">
	{#if request}
		<form id={id('form')} class="form" onsubmit={submit}>
			{#if existing}
				<fieldset class="mode">
					<legend>Save as</legend>
					<label><input type="radio" name={id('mode')} value="new" bind:group={mode} /> A new bank item</label>
					<label>
						<input type="radio" name={id('mode')} value="version" bind:group={mode} />
						Version {existing.version + 1} of <strong>{existing.title}</strong> (where this {kindName} came from)
					</label>
				</fieldset>
			{/if}
			<div class="field">
				<label for={id('title')}>Title</label>
				<input id={id('title')} type="text" bind:value={title} required maxlength="200" autocomplete="off" />
			</div>
			<div class="two">
				<div class="field">
					<label for={id('abbr')}>Abbreviation</label>
					<input id={id('abbr')} type="text" bind:value={abbreviation} maxlength="40" placeholder="e.g. PHQ-9" autocomplete="off" />
				</div>
				<div class="field">
					<label for={id('tags')}>Tags</label>
					<input id={id('tags')} type="text" bind:value={tags} placeholder="depression, screener" autocomplete="off" />
				</div>
			</div>
			<div class="field">
				<label for={id('desc')}>Description</label>
				<textarea id={id('desc')} rows="2" bind:value={description}></textarea>
			</div>
			<div class="field">
				<label for={id('licence')}>Licence</label>
				<select id={id('licence')} bind:value={licence} aria-describedby={id('licence-hint')}>
					{#each licences as l (l.value)}
						<option value={l.value}>{l.label}</option>
					{/each}
				</select>
				<p id={id('licence-hint')} class="hint">{licenceHint} Only items with a known licence can be shared with other labs.</p>
			</div>

			<section class="travel" aria-labelledby={id('travel')} data-testid="save-to-bank-preview">
				<h3 id={id('travel')}>What travels with it</h3>
				{#if preview}
					<p>
						{preview.itemCount} item{preview.itemCount === 1 ? '' : 's'}{#if preview.languages.length}
							in {preview.languages.join(', ')}{/if}{#if preview.choiceLists.length}; shared choice list{preview.choiceLists.length === 1
								? ''
								: 's'}
							{preview.choiceLists.join(', ')}{/if}{#if preview.variables.length}; scoring variable{preview.variables.length === 1 ? '' : 's'}
							{preview.variables.join(', ')}{/if}.
					</p>
					{#if warnings.length}
						<p class="cut"><strong>Will be cut</strong> (they point outside the {kindName}):</p>
						<ul class="cut-list">
							{#each warnings as w, i (i)}<li>{w.message}</li>{/each}
						</ul>
					{:else}
						<p class="ok">Nothing points outside the {kindName}: it is saved whole.</p>
					{/if}
				{:else if previewError}
					<p class="cut" role="alert">{previewError}</p>
				{:else}
					<p role="status">Checking…</p>
				{/if}
			</section>
			{#if error}
				<p class="error" role="alert">
					{error}
					{#if problems.length}<span>{problems[0].message}</span>{/if}
				</p>
			{/if}
		</form>
	{/if}
	{#snippet footer()}
		<Button onclick={() => (open = false)}>Cancel</Button>
		<Button variant="primary" type="submit" form={id('form')} disabled={busy || !!previewError}>
			{busy ? 'Saving…' : mode === 'version' ? 'Save new version' : 'Save to bank'}
		</Button>
	{/snippet}
</Dialog>

<style>
	.form {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}
	.two {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
		gap: var(--space-3);
	}
	label,
	legend {
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}
	input[type='text'],
	textarea,
	select {
		width: 100%;
		min-height: 2.5rem;
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
	}
	textarea {
		resize: vertical;
	}
	.mode {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
	}
	.mode label {
		display: flex;
		gap: var(--space-2);
		align-items: baseline;
		font-weight: var(--weight-normal);
	}
	.hint {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.travel {
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-md);
		background: var(--color-surface-sunken);
		font-size: var(--text-sm);
	}
	.travel h3 {
		margin: 0 0 var(--space-1);
		font-size: var(--text-sm);
	}
	.travel p {
		margin: 0;
	}
	.cut {
		color: var(--color-warning);
	}
	.cut-list {
		margin: var(--space-1) 0 0;
		padding-inline-start: var(--space-4);
	}
	.ok {
		color: var(--color-text-muted);
	}
	.error {
		margin: 0;
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
</style>
