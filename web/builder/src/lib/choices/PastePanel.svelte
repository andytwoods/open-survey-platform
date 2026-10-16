<script lang="ts">
	import { Button, announce } from '@osp/ui-components';
	import { onMount } from 'svelte';
	import type { ChoiceOp, SpecChoice } from './model';
	import { parsePaste, pasteOps, type PasteMode } from './paste';

	/** Bulk paste: one choice per line, previewed, applied as one `bulk_paste_choices`. */
	let {
		owner,
		existing,
		publishedVersions = 0,
		onOps,
		onclose
	}: {
		owner: string;
		existing: readonly SpecChoice[];
		publishedVersions?: number;
		onOps: (ops: ChoiceOp[]) => void;
		onclose: () => void;
	} = $props();

	const uid = $props.id();
	let text = $state('');
	let box = $state<HTMLTextAreaElement | null>(null);
	// The panel was just opened for typing.
	onMount(() => box?.focus());
	let mode = $state<PasteMode>('replace');
	const preview = $derived(parsePaste(text, existing, mode));
	const ready = $derived(text.trim() !== '');

	function apply() {
		const ops = pasteOps(owner, preview, mode);
		if (!ops.length) return;
		onOps(ops);
		const n = preview.rows.length;
		announce(`${mode === 'replace' ? 'Replaced the list with' : 'Appended'} ${n} choice${n === 1 ? '' : 's'}`);
		onclose();
	}
</script>

<div class="paste" role="group" aria-labelledby="{uid}-title">
	<h3 id="{uid}-title">Paste choices</h3>
	<label for="{uid}-text">One choice per line</label>
	<p id="{uid}-hint" class="hint">
		"Strongly disagree" gets the next number as its code. "1 Strongly disagree" or a
		spreadsheet's code and label columns keep their codes.
	</p>
	<textarea
		id="{uid}-text"
		bind:value={text}
		rows="6"
		aria-describedby="{uid}-hint"
		spellcheck="false"
		bind:this={box}
		onkeydown={(e) => {
			if (e.key === 'Escape') {
				e.preventDefault();
				e.stopPropagation();
				onclose();
			}
		}}
	></textarea>

	<fieldset>
		<legend>Pasted choices</legend>
		<label><input type="radio" bind:group={mode} value="replace" /> Replace the list</label>
		<label><input type="radio" bind:group={mode} value="append" /> Add to the end</label>
	</fieldset>

	{#if ready}
		<table aria-label="Preview">
			<thead>
				<tr><th scope="col">Line</th><th scope="col">Code</th><th scope="col">Label</th><th scope="col">Note</th></tr>
			</thead>
			<tbody>
				{#each preview.rows as r (r.line)}
					<tr data-error={r.error ? 'true' : undefined}>
						<td>{r.line}</td>
						<td><code>{r.code}</code>{#if r.auto}<span class="auto">(auto)</span>{/if}</td>
						<td>{r.label}</td>
						<td class="note">{r.error ?? r.warning ?? ''}</td>
					</tr>
				{/each}
			</tbody>
		</table>
		<div class="summary" role="status">
			{#each preview.problems as p (p)}<p class="error">{p}</p>{/each}
			{#if preview.errors}
				<p class="error">Fix {preview.errors} problem{preview.errors === 1 ? '' : 's'} before applying.</p>
			{:else if mode === 'replace' && existing.length}
				<p>
					Replaces the {existing.length} current choice{existing.length === 1 ? '' : 's'}.
					{#if publishedVersions > 0}Collected data keeps the old codes.{/if}
				</p>
			{/if}
			{#if preview.mixed}<p class="warning">The list will mix number and text codes.</p>{/if}
		</div>
	{/if}

	<div class="actions">
		<Button variant="primary" size="sm" disabled={!ready || preview.errors > 0} onclick={apply}>
			{mode === 'replace' ? 'Replace with' : 'Add'}
			{preview.rows.length} choice{preview.rows.length === 1 ? '' : 's'}
		</Button>
		<Button variant="ghost" size="sm" onclick={onclose}>Cancel</Button>
	</div>
</div>

<style>
	.paste {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}
	h3 {
		margin: 0;
		font-size: var(--text-md);
	}
	label {
		font-weight: var(--weight-medium);
	}
	fieldset label {
		font-weight: normal;
		margin-inline-end: var(--space-3);
	}
	.hint {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	textarea {
		padding: var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-family: var(--font-mono, ui-monospace, monospace);
		resize: vertical;
	}
	fieldset {
		margin: 0;
		padding: 0;
		border: 0;
	}
	legend {
		padding: 0;
		margin-block-end: var(--space-1);
		font-weight: var(--weight-medium);
	}
	table {
		border-collapse: collapse;
		font-size: var(--text-xs);
	}
	th,
	td {
		padding: var(--space-1) var(--space-2);
		border-bottom: 1px solid var(--color-border);
		text-align: start;
	}
	tr[data-error] td.note,
	.error {
		color: var(--color-danger);
	}
	.warning,
	.note {
		color: var(--color-warning);
	}
	.auto {
		margin-inline-start: var(--space-1);
		color: var(--color-text-muted);
	}
	.summary p {
		margin: 0;
	}
	.actions {
		display: flex;
		gap: var(--space-2);
	}
</style>
