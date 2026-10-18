<script lang="ts">
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import { Button, Dialog, announce } from '@osp/ui-components';
	import { untrack } from 'svelte';
	import type { Diagnostic } from '../sync/transport';
	import { bank } from './library.svelte';
	import { itemLines, type BankItemOut, type InstrumentStub } from './logic';

	/**
	 * "Add a licensed instrument privately" (question-bank.md §1.7, §6). Three steps: pick a
	 * stub (an instrument the project may not bundle: its metadata, response format and
	 * scoring recipe, no item text) or start blank; paste the lab's own copy of the items,
	 * one per line (`text | option | …` when each item has its own options), the stem and
	 * the response labels; then the owner ticks the attestation and the server builds a
	 * private `licensed-to-lab` bank item with the scoring recipe as computed variables.
	 */
	let {
		open = $bindable(false),
		stubs,
		initialStub = null,
		oncreated
	}: {
		open?: boolean;
		stubs: InstrumentStub[];
		initialStub?: string | null;
		oncreated: (item: BankItemOut) => void;
	} = $props();

	const uid = $props.id();
	const id = (s: string) => `licwiz-${uid}-${s}`;

	let step = $state<1 | 2 | 3>(1);
	let stubId = $state<string>('');
	let filter = $state('');
	let title = $state('');
	let abbreviation = $state('');
	let items = $state('');
	let stem = $state('');
	let layout = $state<'matrix' | 'single'>('matrix');
	let labels = $state('');
	let scaleMin = $state(0);
	let scaleMax = $state(3);
	let reversed = $state('');
	let aggregate = $state<'sum' | 'mean' | 'none'>('sum');
	let attest = $state(false);
	let busy = $state(false);
	let error = $state<string | null>(null);
	let problems = $state<Diagnostic[]>([]);

	$effect(() => {
		if (!open) return;
		untrack(() => {
			step = 1;
			stubId = initialStub ?? '';
			filter = '';
			title = abbreviation = items = stem = labels = reversed = '';
			layout = 'matrix';
			scaleMin = 0;
			scaleMax = 3;
			aggregate = 'sum';
			attest = false;
			busy = false;
			error = null;
			problems = [];
		});
	});

	const stub = $derived(stubs.find((s) => s.id === stubId) ?? null);
	const shown = $derived.by(() => {
		const q = filter.trim().toLowerCase();
		return q ? stubs.filter((s) => `${s.title} ${s.abbreviation} ${s.tags.join(' ')}`.toLowerCase().includes(q)) : stubs;
	});
	const lines = $derived(itemLines(items));
	const perItem = $derived(stub?.response.kind === 'per-item');
	const min = $derived(stub ? stub.response.min : scaleMin);
	const max = $derived(stub ? stub.response.max : scaleMax);
	const points = $derived(Math.max(0, max - min + 1));
	const expected = $derived(stub?.itemCount ?? null);
	const countOk = $derived(expected === null ? lines.length > 0 : lines.length === expected);
	const labelList = $derived(itemLines(labels));
	const labelsOk = $derived(perItem || labelList.length === 0 || labelList.length === points);
	const canContinue = $derived(step === 1 ? true : step === 2 ? countOk && labelsOk && (stub ? true : !!title.trim() && points >= 2) : attest);

	function next() {
		error = null;
		if (step === 1) {
			if (stub) {
				title = stub.title;
				abbreviation = stub.abbreviation;
				layout = perItem ? 'single' : 'matrix';
			}
			step = 2;
		} else if (step === 2) step = 3;
	}
	function back() {
		error = null;
		if (step > 1) step = (step - 1) as 1 | 2;
	}

	async function create() {
		if (busy || !attest) return;
		busy = true;
		error = null;
		problems = [];
		const body: Parameters<typeof bank.composeLicensed>[0] = {
			items: lines,
			attest: true,
			layout,
			stem: stem.trim() || null,
			labels: perItem || labelList.length === 0 ? null : labelList
		};
		if (stub) {
			body.stubId = stub.id;
			if (title.trim() && title.trim() !== stub.title) body.title = title.trim();
			if (abbreviation.trim() && abbreviation.trim() !== stub.abbreviation) body.abbreviation = abbreviation.trim();
		} else {
			body.title = title.trim();
			body.abbreviation = abbreviation.trim() || null;
			body.scale = { min: scaleMin, max: scaleMax };
			const rev = reversed
				.split(/[,\s]+/)
				.map((x) => Number.parseInt(x, 10))
				.filter((n) => Number.isInteger(n) && n > 0);
			body.scoring = { aggregate: aggregate === 'none' ? null : aggregate, reversed: rev, subscales: {}, total: aggregate !== 'none', offset: 0, factor: null };
		}
		const r = await bank.composeLicensed(body);
		busy = false;
		if (!r.ok) {
			error = r.message;
			problems = r.diagnostics ?? [];
			announce(r.message, 'assertive');
			return;
		}
		announce(`${r.data.summary.title} added to the lab's bank as a licensed instrument.`);
		oncreated(r.data);
		open = false;
	}
</script>

<Dialog bind:open title="Add a licensed instrument privately" size="lg">
	<div class="wizard" data-testid="licensed-wizard" data-step={step}>
		<ol class="steps" aria-label="Steps">
			<li aria-current={step === 1 ? 'step' : undefined}>1. Instrument</li>
			<li aria-current={step === 2 ? 'step' : undefined}>2. Your copy</li>
			<li aria-current={step === 3 ? 'step' : undefined}>3. Licence</li>
		</ol>

		{#if step === 1}
			<p class="intro">
				For instruments the platform may not bundle (proprietary, or free for research without the right to redistribute). Pick one
				to get its response format and scoring recipe; you type the items from the copy your lab holds a licence for. The item stays
				private to this lab.
			</p>
			<label class="field">
				<span>Find an instrument</span>
				<input type="search" bind:value={filter} placeholder="Search by name or tag" autocomplete="off" />
			</label>
			<div class="choices" role="radiogroup" aria-label="Instrument">
				<label class="choice">
					<input type="radio" name={id('stub')} value="" bind:group={stubId} />
					<span class="ctitle">Start blank</span>
					<span class="cmeta">Your own scale: you set the response values and the scoring.</span>
				</label>
				{#each shown as s (s.id)}
					<label class="choice">
						<input type="radio" name={id('stub')} value={s.id} bind:group={stubId} />
						<span class="ctitle">{s.title} <span class="abbr">{s.abbreviation}</span></span>
						<span class="cmeta">
							{s.itemCount} items · {s.response.min}–{s.response.max} · {s.terms === 'licensed' ? 'licence required' : 'ask the holder'} ·
							{s.holder.name}
						</span>
					</label>
				{/each}
			</div>
		{:else if step === 2}
			{#if stub}
				<div class="about">
					<p><strong>{stub.title}</strong> ({stub.abbreviation}): {stub.description}</p>
					<p>
						{stub.citation.text}
						{#if stub.holder.url}
							<a href={stub.holder.url} target="_blank" rel="noreferrer">Rights holder <ExternalLink size={12} aria-hidden="true" /></a>
						{/if}
					</p>
					<p><strong>Scoring:</strong> {stub.scoring.text}</p>
					{#if stub.note}<p class="note">{stub.note}</p>{/if}
				</div>
			{/if}
			<div class="two">
				<label class="field">
					<span>Title</span>
					<input type="text" bind:value={title} maxlength="200" required />
				</label>
				<label class="field">
					<span>Abbreviation</span>
					<input type="text" bind:value={abbreviation} maxlength="40" />
				</label>
			</div>
			<label class="field">
				<span>
					Items, one per line{#if expected !== null}
						({lines.length} of {expected}){/if}{#if perItem}
						— each with its {points} options after a |, in score order{/if}
				</span>
				<textarea
					rows="8"
					bind:value={items}
					placeholder={perItem ? 'Item text | option 0 | option 1 | option 2 | option 3' : 'One item per line'}
					aria-invalid={items && !countOk ? 'true' : undefined}
				></textarea>
			</label>
			{#if items && !countOk && expected !== null}
				<p class="warn" role="alert">{stub?.abbreviation} has {expected} items; you have {lines.length} lines.</p>
			{/if}
			<label class="field">
				<span>Instruction above the items (optional)</span>
				<input type="text" bind:value={stem} placeholder="Over the last two weeks, how often…" />
			</label>
			{#if !perItem}
				<div class="two">
					{#if !stub}
						<label class="field">
							<span>Lowest value</span>
							<input type="number" bind:value={scaleMin} />
						</label>
						<label class="field">
							<span>Highest value</span>
							<input type="number" bind:value={scaleMax} />
						</label>
					{/if}
					<label class="field">
						<span>Response options, one per line ({points} points, {min}–{max}; leave blank for the numbers)</span>
						<textarea rows="4" bind:value={labels} aria-invalid={!labelsOk ? 'true' : undefined}></textarea>
					</label>
				</div>
				{#if !labelsOk}<p class="warn" role="alert">Give {points} option labels, one per line, or none.</p>{/if}
				<fieldset class="layout">
					<legend>Layout</legend>
					<label><input type="radio" name={id('layout')} value="matrix" bind:group={layout} /> One grid (a row per item)</label>
					<label><input type="radio" name={id('layout')} value="single" bind:group={layout} /> One question per item</label>
				</fieldset>
			{/if}
			{#if !stub}
				<div class="two">
					<label class="field">
						<span>Reversed items (numbers, comma-separated)</span>
						<input type="text" bind:value={reversed} placeholder="2, 5, 6" />
					</label>
					<label class="field">
						<span>Total score</span>
						<select bind:value={aggregate}>
							<option value="sum">Sum of the items</option>
							<option value="mean">Mean of the items</option>
							<option value="none">No total</option>
						</select>
					</label>
				</div>
			{/if}
		{:else}
			<div class="about">
				<p><strong>{title}</strong>{#if abbreviation}({abbreviation}){/if}: {lines.length} items, {layout === 'matrix' ? 'one grid' : 'one question per item'}.</p>
				<p>
					The item is saved with the licence class <strong>licensed to this lab</strong>: it is never shared with other labs on this host
					and leaves the lab only in your own backup file. Every insert shows a reminder not to share the survey JSON. Your
					attestation is recorded in the lab's audit log (never shown to participants).
				</p>
			</div>
			<label class="attest">
				<input type="checkbox" bind:checked={attest} />
				<span>Our lab holds a licence for this instrument; it stays private to this lab.</span>
			</label>
		{/if}
		{#if error}
			<p class="error" role="alert">
				{error}
				{#if problems.length}<span>{problems[0].message}</span>{/if}
			</p>
		{/if}
	</div>
	{#snippet footer()}
		<Button onclick={() => (open = false)}>Cancel</Button>
		{#if step > 1}<Button onclick={back}>Back</Button>{/if}
		{#if step < 3}
			<Button variant="primary" disabled={!canContinue} onclick={next}>Continue</Button>
		{:else}
			<Button variant="primary" disabled={!attest || busy} onclick={create}>{busy ? 'Adding…' : 'Add to my bank'}</Button>
		{/if}
	{/snippet}
</Dialog>

<style>
	.wizard {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		font-size: var(--text-sm);
	}
	.steps {
		display: flex;
		gap: var(--space-3);
		margin: 0;
		padding: 0;
		list-style: none;
		color: var(--color-text-muted);
	}
	.steps li[aria-current='step'] {
		color: var(--color-text);
		font-weight: var(--weight-bold);
	}
	.intro,
	.about p,
	.warn,
	.error,
	.note {
		margin: 0;
	}
	.about {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-md);
		background: var(--color-surface-sunken);
	}
	.note {
		color: var(--color-warning);
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}
	.field > span,
	legend {
		font-weight: var(--weight-medium);
	}
	.two {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
		gap: var(--space-3);
	}
	input[type='text'],
	input[type='search'],
	input[type='number'],
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
	.choices {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		max-height: 18rem;
		overflow: auto;
		padding: var(--space-1);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
	}
	.choice {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 0 var(--space-2);
		align-items: baseline;
		min-height: 2.75rem;
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-sm);
	}
	.choice:hover {
		background: var(--color-surface-sunken);
	}
	.ctitle {
		font-weight: var(--weight-medium);
	}
	.abbr {
		color: var(--color-text-muted);
		font-weight: var(--weight-normal);
	}
	.cmeta {
		grid-column: 2;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.layout {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
	}
	.layout label,
	.attest {
		display: flex;
		gap: var(--space-2);
		align-items: baseline;
	}
	.attest {
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-warning);
		border-radius: var(--radius-md);
		font-weight: var(--weight-medium);
	}
	.warn {
		color: var(--color-warning);
	}
	.error {
		color: var(--color-danger);
	}
	a {
		color: var(--color-accent);
	}
</style>
