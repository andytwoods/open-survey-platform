<script lang="ts">
	import { Announcer, Button, theme } from '@osp/ui-components';
	import { ChoiceListDialog, ChoiceListEditor, editorInputs, type ChoiceDiagnostic, type ChoiceOp } from '#lib/choices/index.js';
	import { onMount } from 'svelte';
	import { SURVEY, applyOps } from './mock-server';

	// Developer sandbox for the choice list editor (task B6), driven by a mock op endpoint.
	// Checked by e2e/choices.spec.ts. The op log shows each transaction the editor emitted.
	onMount(() => theme.init());

	let survey = $state.raw(SURVEY);
	let questionId = $state('q_mood');
	let published = $state(false);
	let diagnostics = $state.raw<ChoiceDiagnostic[]>([]);
	let log = $state.raw<ChoiceOp[][]>([]);
	let dialogOpen = $state(false);

	const inputs = $derived(editorInputs(survey, questionId));
	const QUESTIONS = ['q_mood', 'q_work', 'q_team', 'q_pets'];

	function onOps(ops: ChoiceOp[]) {
		log = [...log, ops];
		const r = applyOps(survey, ops);
		if (r.ok) {
			survey = r.survey;
			diagnostics = [];
		} else diagnostics = r.diagnostics;
	}
</script>

<svelte:head>
	<title>Choice list editor · Open Survey Platform</title>
</svelte:head>

<Announcer />
<main class="sandbox">
	<h1>Choice list editor</h1>
	<div class="controls">
		<fieldset>
			<legend>Question</legend>
			{#each QUESTIONS as id (id)}
				<label><input type="radio" bind:group={questionId} value={id} /> {id}</label>
			{/each}
		</fieldset>
		<label><input type="checkbox" bind:checked={published} /> Survey has published versions</label>
		<Button size="sm" onclick={() => (dialogOpen = true)}>Edit choices…</Button>
	</div>

	{#if inputs.question}
		<section aria-label="Editor" class="editor">
			{#key questionId}
				<ChoiceListEditor
					question={inputs.question}
					choiceLists={inputs.choiceLists}
					usage={inputs.usage}
					pointer={inputs.pointer}
					defaultLanguage={inputs.defaultLanguage}
					publishedVersions={published ? 2 : 0}
					{diagnostics}
					{onOps}
				/>
			{/key}
		</section>
		<ChoiceListDialog
			bind:open={dialogOpen}
			question={inputs.question}
			choiceLists={inputs.choiceLists}
			usage={inputs.usage}
			pointer={inputs.pointer}
			defaultLanguage={inputs.defaultLanguage}
			publishedVersions={published ? 2 : 0}
			{diagnostics}
			{onOps}
		/>
	{/if}

	<section aria-labelledby="h-log">
		<h2 id="h-log">Transactions</h2>
		<ol data-testid="op-log" class="log">
			{#each log as txn, i (i)}
				<li>{JSON.stringify(txn)}</li>
			{/each}
		</ol>
	</section>
</main>

<style>
	.sandbox {
		max-width: 44rem;
		margin: 0 auto;
		padding: var(--space-5);
		color: var(--color-text);
	}
	h1 {
		font-size: var(--text-xl);
	}
	h2 {
		font-size: var(--text-md);
	}
	.controls {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-4);
		margin-block-end: var(--space-4);
	}
	fieldset {
		display: flex;
		gap: var(--space-3);
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
	}
	.log {
		font-family: var(--font-mono, ui-monospace, monospace);
		font-size: var(--text-xs);
		overflow-wrap: anywhere;
	}
</style>
