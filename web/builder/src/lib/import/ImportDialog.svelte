<script lang="ts">
	import { Button, Dialog, Input, announce } from '@osp/ui-components';
	import { leaveTo, link } from '../host/links';
	import {
		ACCEPT,
		apiImportClient,
		FORMAT_LABELS,
		groupDiagnostics,
		readSurveyFile,
		summaryLines,
		validationNote,
		type ImportClient,
		type ImportDiagnostic,
		type ImportPreview
	} from './model';

	/**
	 * Import a survey from Qualtrics (.qsf), LimeSurvey (.lss) or SurveyJS JSON (task IM1).
	 * Picking a file sends it for a preview: what will be created, what will not carry over
	 * (losses), what will behave differently (warnings) and notes. Import creates the draft
	 * and opens it in the editor.
	 */
	let {
		open = $bindable(false),
		tenantId,
		client = apiImportClient,
		onimported
	}: {
		open?: boolean;
		/** The lab the draft goes into (omit when the server can tell). */
		tenantId?: string;
		client?: ImportClient;
		/** Default: open the editor on the new survey. */
		onimported?: (surveyId: string) => void;
	} = $props();

	type Phase =
		| { kind: 'pick' }
		| { kind: 'reading'; filename: string }
		| { kind: 'unreadable'; filename: string; message: string }
		| { kind: 'previewing'; filename: string }
		| { kind: 'failed'; filename: string; message: string; diagnostics: ImportDiagnostic[] }
		| { kind: 'ready'; filename: string; content: string; preview: ImportPreview }
		| { kind: 'importing'; filename: string; content: string; preview: ImportPreview };

	let phase = $state<Phase>({ kind: 'pick' });
	let title = $state('');
	let importError = $state<string | null>(null);
	let fileInput = $state<HTMLInputElement | null>(null);
	let request = 0;

	const uid = $props.id();
	const groups = $derived(
		phase.kind === 'ready' || phase.kind === 'importing' ? groupDiagnostics(phase.preview.diagnostics) : null
	);

	$effect(() => {
		if (!open) reset();
	});

	function reset() {
		phase = { kind: 'pick' };
		title = '';
		importError = null;
		request++;
		if (fileInput) fileInput.value = '';
	}

	async function pick(e: Event) {
		const file = (e.currentTarget as HTMLInputElement).files?.[0];
		if (!file) return;
		const mine = ++request;
		importError = null;
		phase = { kind: 'reading', filename: file.name };
		const read = await readSurveyFile(file);
		if (mine !== request) return;
		if ('error' in read) {
			phase = { kind: 'unreadable', filename: file.name, message: read.error };
			return;
		}
		phase = { kind: 'previewing', filename: file.name };
		const outcome = await client.preview({ filename: file.name, content: read.content });
		if (mine !== request) return;
		if (outcome.kind === 'failed') {
			phase = { kind: 'failed', filename: file.name, message: outcome.message, diagnostics: [] };
			return;
		}
		if (!outcome.preview.ok) {
			phase = {
				kind: 'failed',
				filename: file.name,
				message: 'This file could not be read as a survey.',
				diagnostics: groupDiagnostics(outcome.preview.diagnostics).errors
			};
			return;
		}
		title = outcome.preview.title;
		phase = { kind: 'ready', filename: file.name, content: read.content, preview: outcome.preview };
		announce(`Preview ready: ${summaryLines(outcome.preview.summary!)[0]}.`);
	}

	async function doImport() {
		if (phase.kind !== 'ready') return;
		const { filename, content, preview } = phase;
		const mine = ++request;
		importError = null;
		phase = { kind: 'importing', filename, content, preview };
		const t = title.trim();
		const outcome = await client.create({
			filename,
			content,
			format: preview.format,
			...(t && t !== preview.title ? { title: t } : {}),
			...(tenantId ? { tenantId } : {})
		});
		if (mine !== request) return;
		if (outcome.kind === 'failed') {
			phase = { kind: 'ready', filename, content, preview };
			importError = outcome.message;
			return;
		}
		announce(`Imported ${outcome.survey.title}. Opening the editor.`);
		if (onimported) onimported(outcome.survey.id);
		else await leaveTo(link('editor', { id: outcome.survey.id }));
	}
</script>

<Dialog
	bind:open
	title="Import a survey"
	size="lg"
	placement="top"
	description="Qualtrics (.qsf), LimeSurvey (.lss) or SurveyJS JSON. You see what will carry over before anything is created."
>
	<div class="body">
		<label class="file" for="{uid}-file">
			<span>Survey file</span>
			<input
				id="{uid}-file"
				type="file"
				accept={ACCEPT}
				bind:this={fileInput}
				onchange={pick}
				disabled={phase.kind === 'importing'}
			/>
		</label>

		{#if phase.kind === 'reading' || phase.kind === 'previewing'}
			<p class="muted" role="status">
				{phase.kind === 'reading' ? 'Reading' : 'Checking'} {phase.filename}…
			</p>
		{:else if phase.kind === 'unreadable'}
			<p class="bad" role="alert">{phase.message}</p>
		{:else if phase.kind === 'failed'}
			<div role="alert" data-testid="import-failed">
				<p class="bad"><strong>{phase.message}</strong></p>
				{#if phase.diagnostics.length}
					<ul class="plain">
						{#each phase.diagnostics as d (d.code + d.pointer)}
							<li>{d.message}</li>
						{/each}
					</ul>
				{/if}
			</div>
		{:else if (phase.kind === 'ready' || phase.kind === 'importing') && groups && phase.preview.summary}
			{@const p = phase.preview}
			{@const summary = phase.preview.summary}
			<div class="preview" data-testid="import-preview">
				<p class="muted">
					Read as <strong>{FORMAT_LABELS[p.format]}</strong>.
				</p>
				<Input label="Title" bind:value={title} maxlength={500} disabled={phase.kind === 'importing'} />

				<section aria-labelledby="{uid}-created">
					<h3 id="{uid}-created">What will be created</h3>
					<ul class="created" data-testid="import-summary">
						{#each summaryLines(summary) as line (line)}
							<li>{line}</li>
						{/each}
					</ul>
					{#if validationNote(p)}
						<p class="muted">{validationNote(p)}</p>
					{/if}
				</section>

				<section aria-labelledby="{uid}-lost" data-testid="import-losses">
					<h3 id="{uid}-lost">
						What will not carry over
						<span class="count" data-severity="loss">{groups.losses.length}</span>
					</h3>
					{#if groups.losses.length === 0}
						<p class="muted">Everything in this file has a counterpart here.</p>
					{:else}
						<ul class="diagnostics">
							{#each groups.losses as d (d.code + d.feature + d.pointer)}
								<li data-code={d.code}><span class="feature">{d.feature}</span> {d.message}</li>
							{/each}
						</ul>
					{/if}
				</section>

				{#if groups.warnings.length}
					<section aria-labelledby="{uid}-changed" data-testid="import-warnings">
						<h3 id="{uid}-changed">
							What will behave differently
							<span class="count" data-severity="warning">{groups.warnings.length}</span>
						</h3>
						<ul class="diagnostics">
							{#each groups.warnings as d (d.code + d.feature + d.pointer)}
								<li data-code={d.code}><span class="feature">{d.feature}</span> {d.message}</li>
							{/each}
						</ul>
					</section>
				{/if}

				{#if groups.infos.length}
					<details data-testid="import-notes">
						<summary>Notes ({groups.infos.length})</summary>
						<ul class="diagnostics">
							{#each groups.infos as d (d.code + d.feature + d.pointer)}
								<li data-code={d.code}><span class="feature">{d.feature}</span> {d.message}</li>
							{/each}
						</ul>
					</details>
				{/if}
			</div>
		{/if}

		{#if importError}
			<p class="bad" role="alert">{importError}</p>
		{/if}
	</div>

	{#snippet footer()}
		<Button onclick={() => (open = false)} disabled={phase.kind === 'importing'}>Cancel</Button>
		<Button
			variant="primary"
			onclick={() => void doImport()}
			disabled={phase.kind !== 'ready' || !title.trim()}
		>
			{phase.kind === 'importing' ? 'Importing…' : 'Import'}
		</Button>
	{/snippet}
</Dialog>

<style>
	.body {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.file {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}
	.file input {
		font: inherit;
		font-weight: var(--weight-regular, 400);
		color: var(--color-text);
	}
	.preview {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	h3 {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin: 0 0 var(--space-1);
		font-size: var(--text-sm);
		font-weight: var(--weight-semibold, 600);
	}
	.count {
		display: inline-block;
		min-width: 1.5em;
		padding: 0 var(--space-1);
		border-radius: var(--radius-sm);
		background: var(--color-surface-muted, var(--color-border));
		color: var(--color-text);
		font-size: var(--text-xs, 0.75rem);
		text-align: center;
	}
	.count[data-severity='loss'] {
		background: color-mix(in srgb, var(--color-danger) 15%, transparent);
		color: var(--color-danger);
	}
	.count[data-severity='warning'] {
		background: color-mix(in srgb, var(--color-warning, #b45309) 15%, transparent);
		color: var(--color-warning, #b45309);
	}
	ul {
		margin: 0;
		padding-left: 1.25rem;
	}
	ul.plain {
		padding-left: 1.25rem;
	}
	.diagnostics li + li {
		margin-top: var(--space-1);
	}
	.diagnostics,
	.created {
		font-size: var(--text-sm);
	}
	.feature {
		display: inline-block;
		margin-right: var(--space-1);
		padding: 0 var(--space-1);
		border-radius: var(--radius-sm);
		background: var(--color-surface-muted, var(--color-border));
		font-family: var(--font-mono, monospace);
		font-size: var(--text-xs, 0.75rem);
	}
	details summary {
		cursor: pointer;
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}
	details ul {
		margin-top: var(--space-2);
	}
	.muted {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.bad {
		margin: 0;
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
</style>
