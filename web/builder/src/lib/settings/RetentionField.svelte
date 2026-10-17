<script lang="ts">
	import { Button } from '@osp/ui-components';
	import { retentionOf, retentionValue, type RetentionDraft, type RetentionKind } from './model';

	/**
	 * Data retention (settings.retention): required before publishing, no silent default.
	 * The kinds come from `GET /api/meta/retention`; a complete choice is saved at once.
	 */
	let {
		survey,
		kinds,
		loadError = null,
		onsave
	}: {
		survey: unknown;
		kinds: RetentionKind[];
		loadError?: string | null;
		onsave: (value: Record<string, unknown>) => void;
	} = $props();

	const saved = $derived(retentionOf(survey));
	let draft = $state<RetentionDraft>({ kind: '', days: '', until: '' });
	// Follow the survey when it changes (undo, another tab), not while typing.
	let lastSaved = '';
	$effect(() => {
		const key = JSON.stringify(saved);
		if (key !== lastSaved) {
			lastSaved = key;
			draft = saved ?? { kind: '', days: '', until: '' };
		}
	});

	const chosen = $derived(kinds.find((k) => k.kind === draft.kind));
	const value = $derived(retentionValue(draft, kinds));
	const dirty = $derived(value !== null && JSON.stringify(value) !== JSON.stringify(savedValue()));

	function savedValue() {
		return saved ? retentionValue(saved, kinds) : null;
	}

	function pick(kind: string) {
		draft = { ...draft, kind };
		const k = kinds.find((x) => x.kind === kind);
		if (!k?.field) save(); // no extra field: the choice is complete
	}

	function save() {
		const v = retentionValue(draft, kinds);
		if (v) onsave(v);
	}
</script>

<fieldset class="retention" id="settings-retention" tabindex="-1" aria-describedby="retention-help">
	<legend>How long participant data is kept</legend>
	<p class="help" id="retention-help">
		Required before you can publish: there is no default. Responses are deleted automatically when the
		period ends.
	</p>
	{#if loadError}
		<p class="problem" role="alert">{loadError}</p>
	{/if}
	{#each kinds as k (k.kind)}
		<label class="option">
			<input
				type="radio"
				name="retention-kind"
				value={k.kind}
				checked={draft.kind === k.kind}
				onchange={() => pick(k.kind)}
			/>
			<span>
				<span class="option-label">{k.label}</span>
				<span class="option-help">{k.description.replace(/`/g, '')}</span>
			</span>
		</label>
	{/each}
	{#if chosen?.field === 'days'}
		<label class="field">
			<span>Days after the survey closes</span>
			<input
				type="number"
				inputmode="numeric"
				min="0"
				max="99999"
				bind:value={draft.days}
				onkeydown={(e) => e.key === 'Enter' && save()}
			/>
		</label>
	{:else if chosen?.field === 'until'}
		<label class="field">
			<span>Delete after this date</span>
			<input type="date" bind:value={draft.until} />
		</label>
	{/if}
	{#if chosen?.field}
		<div>
			<Button size="sm" variant="primary" disabled={!dirty} onclick={save}>Save retention</Button>
		</div>
	{/if}
	<p class="status" role="status" data-testid="retention-status">
		{#if saved}
			Retention is set.
		{:else}
			Not set yet: publishing is blocked until you choose.
		{/if}
	</p>
</fieldset>

<style>
	.retention {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		border: 0;
	}
	.retention:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 4px;
	}
	legend {
		padding: 0;
		margin-bottom: var(--space-1);
		font-weight: var(--weight-medium);
	}
	.help,
	.option-help,
	.status {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.option {
		display: flex;
		gap: var(--space-2);
		align-items: flex-start;
		min-block-size: 2.75rem;
		cursor: pointer;
	}
	.option input {
		margin-top: 0.3rem;
	}
	.option > span {
		display: flex;
		flex-direction: column;
	}
	.option-label {
		font-weight: var(--weight-medium);
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		max-width: 16rem;
		font-size: var(--text-sm);
	}
	.field input {
		min-block-size: 2.25rem;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
	}
	.problem {
		margin: 0;
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
</style>
