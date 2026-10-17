<script lang="ts">
	import X from '@lucide/svelte/icons/x';
	import { Button } from '@osp/ui-components';
	import type { ConditionVariable } from './model';
	import type { ResultsController } from './results.svelte';

	/**
	 * The results filter bar (task V2): versions, completion status, submission dates,
	 * assigned condition, answers to choice questions, split by, denominator and label
	 * language. Edits change the draft; "Show results" applies them (each query may scan
	 * every response, so nothing is sent per keystroke). Below 720 px it folds behind a
	 * "Filters" button.
	 */
	let {
		controller,
		conditions,
		publishedVersions,
		narrow
	}: {
		controller: ResultsController;
		conditions: ConditionVariable[];
		publishedVersions: number;
		narrow: boolean;
	} = $props();

	const uid = $props.id();
	const id = (s: string) => `${uid}-${s}`;
	const draft = $derived(controller.draft);
	const choices = $derived(controller.choices);
	const languages = $derived(controller.response?.languages ?? []);
	const problems = $derived(controller.problems);
	const problem = (field: 'from' | 'to') => problems.find((p) => p.field === field)?.message;
	const versionNumbers = $derived(Array.from({ length: publishedVersions }, (_, i) => i + 1));
	const MAX_FILTERS = 20;

	let open = $state(false);
	const shown = $derived(!narrow || open);

	function toggleVersion(n: number, on: boolean) {
		const rest = draft.versions.filter((v) => v !== n);
		draft.versions = (on ? [...rest, n] : rest).sort((a, b) => a - b);
	}

	const SEP = '\u0000';
	const conditionValue = $derived(draft.condition ? `${draft.condition.variable}${SEP}${draft.condition.levels[0] ?? ''}` : '');
	function setCondition(v: string) {
		if (!v) return void (draft.condition = null);
		const [variable, level] = v.split(SEP);
		draft.condition = { variable, levels: [level] };
	}

	const splitValue = $derived(draft.split ? `${draft.split.kind}${SEP}${draft.split.id}` : '');
	function setSplit(v: string) {
		if (!v) return void (draft.split = null);
		const [kind, sid] = v.split(SEP);
		draft.split = { kind: kind as 'question' | 'condition', id: sid };
	}

	function addFilter() {
		const used = new Set(draft.answers.map((a) => a.question));
		const next = choices.find((c) => !used.has(c.id)) ?? choices[0];
		if (!next) return;
		draft.answers.push({ question: next.id, codes: [] });
	}

	function toggleCode(i: number, key: string, on: boolean) {
		const a = draft.answers[i];
		a.codes = on ? [...new Set([...a.codes, key])] : a.codes.filter((k) => k !== key);
	}

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		const ok = await controller.apply();
		if (!ok && problems.length) document.getElementById(id(problems[0].field))?.focus();
	}
</script>

<section class="filter-bar" aria-labelledby={id('h')}>
	<div class="bar-head">
		<h3 id={id('h')}>Filters</h3>
		{#if narrow}
			<Button aria-expanded={open} aria-controls={id('form')} onclick={() => (open = !open)}>
				{open ? 'Hide filters' : 'Show filters'}
			</Button>
		{/if}
	</div>
	<form id={id('form')} class="filters" hidden={!shown} onsubmit={submit} novalidate>
		<fieldset class="group">
			<legend>Survey version</legend>
			{#each versionNumbers as n (n)}
				<label class="check">
					<input
						type="checkbox"
						checked={draft.versions.includes(n)}
						onchange={(e) => toggleVersion(n, (e.currentTarget as HTMLInputElement).checked)}
					/>
					Version {n}{n === publishedVersions ? ' (latest)' : ''}
				</label>
			{/each}
			{#if !draft.versions.length}<p class="hint">None ticked: the latest version.</p>{/if}
		</fieldset>

		<div class="field">
			<label for={id('status')}>Responses</label>
			<select id={id('status')} bind:value={draft.status}>
				<option value="complete">Complete only</option>
				<option value="all">All submitted</option>
			</select>
		</div>

		<div class="field">
			<label for={id('from')}>Submitted from</label>
			<input
				id={id('from')}
				type="date"
				bind:value={draft.from}
				aria-invalid={problem('from') ? 'true' : undefined}
				aria-describedby={problem('from') ? id('from-err') : undefined}
			/>
			{#if problem('from')}<p id={id('from-err')} class="error">{problem('from')}</p>{/if}
		</div>
		<div class="field">
			<label for={id('to')}>Submitted to (inclusive)</label>
			<input
				id={id('to')}
				type="date"
				bind:value={draft.to}
				aria-invalid={problem('to') ? 'true' : undefined}
				aria-describedby={problem('to') ? id('to-err') : undefined}
			/>
			{#if problem('to')}<p id={id('to-err')} class="error">{problem('to')}</p>{/if}
		</div>

		{#if conditions.length}
			<div class="field">
				<label for={id('condition')}>Condition</label>
				<select
					id={id('condition')}
					value={conditionValue}
					onchange={(e) => setCondition((e.currentTarget as HTMLSelectElement).value)}
				>
					<option value="">Any condition</option>
					{#each conditions as c (c.id)}
						{#each c.levels as l (l)}<option value="{c.id}{SEP}{l}">{c.id} = {l}</option>{/each}
					{/each}
				</select>
			</div>
		{/if}

		<div class="field">
			<label for={id('split')}>Split by</label>
			<select id={id('split')} value={splitValue} onchange={(e) => setSplit((e.currentTarget as HTMLSelectElement).value)}>
				<option value="">No split</option>
				{#if choices.some((c) => c.splittable)}
					<optgroup label="Question">
						{#each choices.filter((c) => c.splittable) as c (c.id)}
							<option value="question{SEP}{c.id}">{c.label}</option>
						{/each}
					</optgroup>
				{/if}
				{#if conditions.length}
					<optgroup label="Condition">
						{#each conditions as c (c.id)}<option value="condition{SEP}{c.id}">{c.id}</option>{/each}
					</optgroup>
				{/if}
			</select>
		</div>

		<fieldset class="group">
			<legend>Denominator</legend>
			<label class="check"><input type="radio" value="answered" bind:group={draft.denominator} /> Answered</label>
			<label class="check">
				<input type="radio" value="shown" bind:group={draft.denominator} /> Shown (answered + unanswered)
			</label>
		</fieldset>

		{#if languages.length > 1}
			<div class="field">
				<label for={id('lang')}>Labels in</label>
				<select
					id={id('lang')}
					value={draft.language ?? ''}
					onchange={(e) => (draft.language = (e.currentTarget as HTMLSelectElement).value || null)}
				>
					<option value="">Main language</option>
					{#each languages as l (l)}<option value={l}>{l}</option>{/each}
				</select>
			</div>
		{/if}

		<fieldset class="group answers">
			<legend>Answer filters</legend>
			{#each draft.answers as a, i (i)}
				{@const v = choices.find((c) => c.id === a.question)}
				<div class="answer-filter">
					<div class="field">
						<label for={id(`aq-${i}`)}>Question</label>
						<select
							id={id(`aq-${i}`)}
							value={a.question}
							onchange={(e) => {
								a.question = (e.currentTarget as HTMLSelectElement).value;
								a.codes = [];
							}}
						>
							{#each choices as c (c.id)}<option value={c.id}>{c.label}</option>{/each}
						</select>
					</div>
					{#if v}
						<fieldset class="codes">
							<legend>Keep responses that answered</legend>
							{#each v.codes as c (c.key)}
								<label class="check">
									<input
										type="checkbox"
										checked={a.codes.includes(c.key)}
										onchange={(e) => toggleCode(i, c.key, (e.currentTarget as HTMLInputElement).checked)}
									/>
									{c.label}
								</label>
							{/each}
						</fieldset>
					{/if}
					<button
						type="button"
						class="remove"
						aria-label="Remove answer filter {i + 1}"
						onclick={() => draft.answers.splice(i, 1)}
					>
						<X size={16} aria-hidden="true" />
					</button>
				</div>
			{/each}
			<div>
				<Button
					type="button"
					disabled={!choices.length || draft.answers.length >= MAX_FILTERS}
					onclick={addFilter}>Add answer filter</Button
				>
			</div>
		</fieldset>

		<div class="actions">
			<Button type="submit" variant="primary">Show results</Button>
			<Button type="button" onclick={() => void controller.reset(publishedVersions)}>Reset filters</Button>
			{#if controller.dirty}<span class="hint" role="status">Changes not applied yet.</span>{/if}
		</div>
	</form>
</section>

<style>
	.filter-bar {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding: var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}
	.bar-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
	}
	h3 {
		margin: 0;
		font-size: var(--text-md);
	}
	.filters {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr));
		gap: var(--space-3) var(--space-4);
		align-items: start;
	}
	.filters[hidden] {
		display: none;
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}
	label,
	legend {
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}
	.group {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
		margin: 0;
		padding: 0;
		border: 0;
	}
	.group > legend {
		margin-bottom: var(--space-1);
		padding: 0;
	}
	.check {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-height: 2.75rem;
		font-weight: var(--weight-normal);
	}
	.check input {
		width: 1.125rem;
		height: 1.125rem;
		margin: 0;
		accent-color: var(--color-accent);
	}
	select,
	input[type='date'] {
		width: 100%;
		min-width: 0;
		min-height: 2.75rem;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		color-scheme: light dark;
	}
	select:focus-visible,
	input:focus-visible,
	.remove:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}
	.answers,
	.actions {
		grid-column: 1 / -1;
	}
	.answer-filter {
		display: grid;
		grid-template-columns: minmax(0, 16rem) minmax(0, 1fr) auto;
		gap: var(--space-2) var(--space-3);
		align-items: start;
		padding: var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
	}
	.codes {
		display: flex;
		flex-wrap: wrap;
		gap: 0 var(--space-3);
		min-width: 0;
		margin: 0;
		padding: 0;
		border: 0;
	}
	.codes legend {
		width: 100%;
		padding: 0;
	}
	.remove {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 2.75rem;
		height: 2.75rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		cursor: pointer;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
	}
	.hint {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.error {
		margin: 0;
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
	@media (max-width: 40rem) {
		.answer-filter {
			grid-template-columns: minmax(0, 1fr) auto;
		}
		.answer-filter .codes {
			grid-column: 1 / -1;
			grid-row: 2;
		}
	}
</style>
