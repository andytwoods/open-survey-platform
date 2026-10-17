<script lang="ts">
	import ArrowDown from '@lucide/svelte/icons/arrow-down';
	import ArrowUp from '@lucide/svelte/icons/arrow-up';
	import Plus from '@lucide/svelte/icons/plus';
	import Trash from '@lucide/svelte/icons/trash';
	import { Button, announce } from '@osp/ui-components';
	import { onMount } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { localised } from '../properties/logic';
	import { ProfileLibrary, type ProfileDiagnostic } from './library.svelte';
	import {
		CUSTOM_KINDS,
		DEFAULTABLE_KINDS,
		emptyRow,
		localProblems,
		moveKey,
		optionsToText,
		parseOptions,
		questionTypes,
		sameProfile,
		stockSchemas,
		toDraft,
		toProfile,
		type ProfileDraft
	} from './logic';

	/**
	 * The lab's property panel profile (task B21, planning/property-profiles.md §6): which
	 * properties researchers see in the panel and in what order, renamed group headings,
	 * defaults for new questions, and the lab's own (custom) properties. Edits are local
	 * until Save sends the whole profile; the server validates and answers with diagnostics.
	 * Owners save; everyone else can look.
	 */
	const lib = new ProfileLibrary();
	const language = 'en';
	const uid = $props.id();
	const id = (s: string) => `profile-${uid}-${s}`;

	let draft = $state<ProfileDraft | null>(null);
	let type = $state('single');
	let busy = $state(false);
	let message = $state<{ kind: 'ok' | 'error'; text: string } | null>(null);
	let problems = $state<string[]>([]);
	let serverDiagnostics = $state<ProfileDiagnostic[]>([]);
	let confirmClear = $state(false);

	const stock = $derived(lib.stock ? stockSchemas(lib.stock) : {});
	const types = $derived(lib.stock ? lib.stock.schemas.map((s) => s.type) : []);
	const qTypes = $derived(lib.stock ? questionTypes(lib.stock) : []);
	const current = $derived(stock[type]);
	const isQuestion = $derived(current?.entity === 'question');
	const dirty = $derived(draft && lib.stock ? !sameProfile(toProfile(draft, stock, language), lib.profile) : false);
	const canEdit = $derived(lib.canManage && !busy);

	function reset() {
		if (!lib.stock) return;
		const d = toDraft(lib.profile, stockSchemas(lib.stock), language);
		draft = { ...d, hidden: new SvelteSet(d.hidden) };
		serverDiagnostics = lib.diagnostics;
		problems = [];
	}

	onMount(() => {
		void lib.load().then(reset);
	});

	function ref(key: string) {
		return `${type}.${key}`;
	}
	function toggleHidden(key: string, shown: boolean) {
		if (!draft) return;
		if (shown) draft.hidden.delete(ref(key));
		else draft.hidden.add(ref(key));
	}
	function move(key: string, dir: -1 | 1) {
		if (!draft) return;
		draft.order[type] = moveKey(draft.order[type], key, dir);
		announce(`${labelOf(key)} moved ${dir < 0 ? 'up' : 'down'}.`);
	}
	function labelOf(key: string): string {
		return localised(current?.properties[key]?.label, language) || key;
	}
	function defaultOf(key: string): string {
		return draft?.defaults[type]?.[key] ?? '';
	}
	function setDefault(key: string, text: string) {
		if (!draft) return;
		(draft.defaults[type] ??= {})[key] = text;
	}

	function addCustom() {
		if (!draft) return;
		draft.custom.push(emptyRow());
		const n = draft.custom.length;
		announce(`Custom property ${n} added.`);
		setTimeout(() => document.getElementById(id(`c${n - 1}-key`))?.focus(), 0);
	}
	function removeCustom(i: number) {
		if (!draft) return;
		draft.custom.splice(i, 1);
		announce('Custom property removed.');
	}
	function toggleType(i: number, t: string, on: boolean) {
		if (!draft) return;
		const row = draft.custom[i];
		row.types = on ? [...row.types, t] : row.types.filter((x) => x !== t);
	}

	async function save() {
		if (!draft || !lib.stock) return;
		problems = localProblems(draft);
		if (problems.length) {
			message = { kind: 'error', text: 'Fix the problems listed below first.' };
			announce(message.text, 'assertive');
			return;
		}
		busy = true;
		const r = await lib.save(toProfile(draft, stock, language));
		busy = false;
		if (!r.ok) {
			message = { kind: 'error', text: r.message };
			if (r.diagnostics) serverDiagnostics = r.diagnostics;
			announce(r.message, 'assertive');
			return;
		}
		reset();
		message = { kind: 'ok', text: 'Profile saved. Researchers see it on their next page load.' };
		announce(message.text);
	}

	async function clearProfile() {
		busy = true;
		const r = await lib.clear();
		busy = false;
		confirmClear = false;
		if (!r.ok) {
			message = { kind: 'error', text: r.message };
			return;
		}
		reset();
		message = { kind: 'ok', text: 'Profile removed. The panel is back to the stock one.' };
		announce(message.text);
	}
</script>

<div class="profile">
	<header>
		<h2 id="profile-heading" tabindex="-1">Property panel profile</h2>
		<p class="lead">
			Choose which properties researchers in your lab see in the property panel, in what order and under
			which headings; set defaults for new questions; and add your lab's own properties, which are stored
			on each question and listed in the codebook.
		</p>
	</header>

	{#if lib.error}
		<p class="note error" role="alert">{lib.error}</p>
	{:else if !lib.loaded || !draft}
		<p class="note" role="status">Loading…</p>
	{:else}
		<p class="note" data-testid="profile-status">
			{#if !lib.canManage}
				Only lab owners can change the profile; you can look.
			{:else if lib.profile}
				Your lab uses its own profile{lib.updatedBy ? `, last changed by ${lib.updatedBy}` : ''}.
			{:else}
				Your lab uses the stock panel. Changes take effect when you save.
			{/if}
		</p>

		<section class="card" aria-labelledby="h-properties">
			<h3 id="h-properties">Properties</h3>
			<p class="help">Untick a property to hide it. Required properties cannot be hidden. Move properties with the arrows.</p>
			<label class="field" for={id('type')}>Question type or object</label>
			<select id={id('type')} bind:value={type} data-testid="profile-type">
				{#each types as t (t)}
					<option value={t}>{localised(stock[t].label, language) || t}</option>
				{/each}
			</select>
			{#if current}
				<ul class="props" aria-label="Properties of {localised(current.label, language) || type}">
					{#each draft.order[type] as key, i (key)}
						{@const spec = current.properties[key]}
						{@const shown = !draft.hidden.has(ref(key))}
						<li class="prop" data-key={key} data-hidden={!shown || undefined}>
							<label class="shown">
								<input
									type="checkbox"
									checked={shown}
									disabled={!!spec.required || !canEdit}
									onchange={(e) => toggleHidden(key, (e.currentTarget as HTMLInputElement).checked)}
								/>
								<span class="name">{labelOf(key)}</span>
								<code>{key}</code>
								{#if spec.required}<span class="tag">required</span>{/if}
							</label>
							<span class="moves">
								<button
									type="button"
									class="move"
									aria-label="Move {labelOf(key)} up"
									disabled={i === 0 || !canEdit}
									onclick={() => move(key, -1)}><ArrowUp size={14} aria-hidden="true" /></button
								>
								<button
									type="button"
									class="move"
									aria-label="Move {labelOf(key)} down"
									disabled={i === draft.order[type].length - 1 || !canEdit}
									onclick={() => move(key, 1)}><ArrowDown size={14} aria-hidden="true" /></button
								>
							</span>
							{#if isQuestion && DEFAULTABLE_KINDS.has(spec.kind)}
								{@const did = id(`d-${type}-${key}`)}
								<span class="default">
									<label for={did}>Default for new questions</label>
									{#if spec.kind === 'bool'}
										<select id={did} value={defaultOf(key)} disabled={!canEdit} onchange={(e) => setDefault(key, e.currentTarget.value)}>
											<option value="">Stock ({spec.default === true ? 'yes' : 'no'})</option>
											<option value="true">Yes</option>
											<option value="false">No</option>
										</select>
									{:else if spec.kind === 'enum' && spec.options}
										<select id={did} value={defaultOf(key)} disabled={!canEdit} onchange={(e) => setDefault(key, e.currentTarget.value)}>
											<option value="">Stock</option>
											{#each spec.options as o (o.value)}
												<option value={o.value}>{localised(o.label, language) || o.value}</option>
											{/each}
										</select>
									{:else}
										<input
											id={did}
											type={spec.kind === 'number' ? 'number' : 'text'}
											value={defaultOf(key)}
											placeholder={typeof spec.default === 'string' || typeof spec.default === 'number' ? String(spec.default) : 'Stock'}
											disabled={!canEdit}
											oninput={(e) => setDefault(key, e.currentTarget.value)}
										/>
									{/if}
								</span>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
		</section>

		<section class="card" aria-labelledby="h-groups">
			<h3 id="h-groups">Group headings</h3>
			<p class="help">Rename the panel's section headings. Leave one empty to keep its name.</p>
			<div class="grid">
				{#each lib.stock?.groups ?? [] as g (g)}
					<label class="field" for={id(`g-${g}`)}>{g}</label>
					<input id={id(`g-${g}`)} type="text" placeholder={g} value={draft.groups[g] ?? ''} disabled={!canEdit} oninput={(e) => (draft!.groups[g] = e.currentTarget.value)} />
				{/each}
			</div>
		</section>

		<section class="card" aria-labelledby="h-custom">
			<h3 id="h-custom">Custom properties</h3>
			<p class="help">
				Your lab's own properties, shown in the panel on the question types you choose and stored on each
				question (the codebook lists them). They never change how a survey runs.
			</p>
			{#each draft.custom as row, i (i)}
				<fieldset class="custom" data-testid="custom-row">
					<legend>Custom property {i + 1}{row.key ? `: ${row.key}` : ''}</legend>
					<div class="grid">
						<label class="field" for={id(`c${i}-key`)}>Key</label>
						<input id={id(`c${i}-key`)} type="text" bind:value={row.key} disabled={!canEdit} pattern="[a-z][a-z0-9_]*" spellcheck="false" />
						<label class="field" for={id(`c${i}-label`)}>Label</label>
						<input id={id(`c${i}-label`)} type="text" bind:value={row.label} disabled={!canEdit} />
						<label class="field" for={id(`c${i}-help`)}>Help text</label>
						<input id={id(`c${i}-help`)} type="text" bind:value={row.help} disabled={!canEdit} />
						<label class="field" for={id(`c${i}-kind`)}>Kind</label>
						<select id={id(`c${i}-kind`)} bind:value={row.kind} disabled={!canEdit}>
							{#each CUSTOM_KINDS as k (k)}
								<option value={k}>{{ text: 'Text', number: 'Number', bool: 'Yes / no', choice: 'Choice' }[k]}</option>
							{/each}
						</select>
						{#if row.kind === 'choice'}
							<label class="field" for={id(`c${i}-options`)}>Options (one per line, <code>value = label</code>)</label>
							<textarea
								id={id(`c${i}-options`)}
								rows="3"
								value={optionsToText(row.options)}
								disabled={!canEdit}
								onchange={(e) => (row.options = parseOptions(e.currentTarget.value))}
							></textarea>
						{/if}
						<label class="field" for={id(`c${i}-default`)}>Default</label>
						{#if row.kind === 'bool'}
							<select id={id(`c${i}-default`)} bind:value={row.defaultText} disabled={!canEdit}>
								<option value="">None</option>
								<option value="true">Yes</option>
								<option value="false">No</option>
							</select>
						{:else if row.kind === 'choice'}
							<select id={id(`c${i}-default`)} bind:value={row.defaultText} disabled={!canEdit}>
								<option value="">None</option>
								{#each row.options as o (o.value)}
									<option value={o.value}>{o.label || o.value}</option>
								{/each}
							</select>
						{:else}
							<input id={id(`c${i}-default`)} type={row.kind === 'number' ? 'number' : 'text'} bind:value={row.defaultText} disabled={!canEdit} />
						{/if}
						<label class="field" for={id(`c${i}-group`)}>Panel section</label>
						<select id={id(`c${i}-group`)} bind:value={row.group} disabled={!canEdit}>
							{#each lib.stock?.groups ?? [] as g (g)}
								<option value={g}>{draft.groups[g] || g}</option>
							{/each}
						</select>
					</div>
					<fieldset class="types">
						<legend>Applies to (none ticked: every question type)</legend>
						{#each qTypes as t (t)}
							<label class="type">
								<input type="checkbox" checked={row.types.includes(t)} disabled={!canEdit} onchange={(e) => toggleType(i, t, e.currentTarget.checked)} />
								{localised(stock[t].label, language) || t}
							</label>
						{/each}
					</fieldset>
					<div class="row-actions">
						<label class="type">
							<input type="checkbox" bind:checked={row.required} disabled={!canEdit} />
							Required (a warning when a question has no value)
						</label>
						<Button size="sm" variant="ghost" disabled={!canEdit} onclick={() => removeCustom(i)}>
							<Trash size={14} aria-hidden="true" />
							Remove
						</Button>
					</div>
				</fieldset>
			{/each}
			<Button size="sm" disabled={!canEdit} onclick={addCustom}>
				<Plus size={14} aria-hidden="true" />
				Add custom property
			</Button>
		</section>

		{#if problems.length}
			<ul class="problems" role="alert" aria-label="Problems">
				{#each problems as p, i (i)}<li>{p}</li>{/each}
			</ul>
		{/if}
		{#if serverDiagnostics.length}
			<ul class="diagnostics" aria-label="Profile warnings">
				{#each serverDiagnostics as d, i (i)}
					<li data-severity={d.severity}><strong>{d.severity}</strong> {d.message} <code>{d.code}</code></li>
				{/each}
			</ul>
		{/if}

		<div class="actions">
			<Button variant="primary" disabled={!canEdit || !dirty} onclick={() => void save()}>Save profile</Button>
			<Button disabled={!canEdit || !dirty} onclick={reset}>Discard changes</Button>
			{#if lib.profile && lib.canManage}
				{#if confirmClear}
					<span class="confirm" role="group" aria-label="Confirm removing the profile">
						Remove the lab profile and use the stock panel?
						<Button size="sm" variant="danger" disabled={busy} onclick={() => void clearProfile()}>Remove</Button>
						<Button size="sm" variant="ghost" disabled={busy} onclick={() => (confirmClear = false)}>Keep</Button>
					</span>
				{:else}
					<Button variant="ghost" disabled={busy} onclick={() => (confirmClear = true)}>Remove profile…</Button>
				{/if}
			{/if}
			{#if message}
				<p class="note" class:error={message.kind === 'error'} role="status" data-testid="profile-message">{message.text}</p>
			{/if}
		</div>
	{/if}
</div>

<style>
	.profile {
		max-width: 60rem;
		margin: 0 auto;
		padding: var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}
	h2 {
		margin: 0 0 var(--space-2);
		font-size: var(--text-xl);
	}
	h3 {
		margin: 0 0 var(--space-2);
		font-size: var(--text-md);
	}
	.lead,
	.help,
	.note {
		margin: 0 0 var(--space-3);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.note.error {
		color: var(--color-danger);
	}
	.card {
		padding: var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}
	.field {
		display: block;
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}
	select,
	input[type='text'],
	input[type='number'],
	textarea {
		min-height: 2.5rem;
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
	}
	.props {
		list-style: none;
		margin: var(--space-3) 0 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.prop {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: var(--space-2) var(--space-3);
		align-items: center;
		padding: var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
	}
	.prop[data-hidden] .name {
		color: var(--color-text-muted);
		text-decoration: line-through;
	}
	.shown {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-height: 2.5rem;
	}
	.shown input {
		width: 1.25rem;
		height: 1.25rem;
	}
	code {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		padding: 0.1rem 0.3rem;
		border-radius: var(--radius-sm);
		background: var(--color-surface-sunken);
	}
	.tag {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.moves {
		display: flex;
		gap: var(--space-1);
	}
	.move {
		width: 2.5rem;
		height: 2.5rem;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
		color: var(--color-text);
		cursor: pointer;
	}
	.move:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.move:focus-visible,
	.shown input:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}
	.default {
		grid-column: 1 / -1;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
	}
	.grid {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: var(--space-2) var(--space-3);
		align-items: center;
	}
	.custom {
		margin: 0 0 var(--space-3);
		padding: var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
	}
	.custom legend {
		font-weight: var(--weight-medium);
		font-size: var(--text-sm);
	}
	.types {
		margin: var(--space-3) 0 0;
		padding: var(--space-2);
		border: 1px dashed var(--color-border);
		border-radius: var(--radius-sm);
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-3);
	}
	.types legend {
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}
	.type {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		min-height: 2.5rem;
		font-size: var(--text-sm);
	}
	.row-actions {
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin-top: var(--space-2);
	}
	.problems,
	.diagnostics {
		margin: 0;
		padding-left: var(--space-4);
		font-size: var(--text-sm);
	}
	.problems {
		color: var(--color-danger);
	}
	.diagnostics strong {
		text-transform: capitalize;
	}
	[data-severity='warning'] strong {
		color: var(--color-warning);
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
	}
	.confirm {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
	}
	@media (max-width: 600px) {
		.grid {
			grid-template-columns: 1fr;
		}
	}
</style>
