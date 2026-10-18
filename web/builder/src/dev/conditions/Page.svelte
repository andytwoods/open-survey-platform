<script lang="ts">
	import { theme } from '@osp/ui-components';
	import {
		localExpressionService,
		ConditionBuilder,
		ConditionDialog,
		questionsFromSurvey,
		type ConditionOp
	} from '#lib/conditions/index.js';
	import { onMount } from 'svelte';
	import { PRESETS } from './presets';
	import survey from './sample-survey.json';

	// Developer page for the condition builder (task B7), checked by e2e/conditions.spec.ts.
	// Text ⇄ AST is parsed and checked in the browser (@osp/engine, @osp/ops), as in the editor.
	onMount(() => theme.init());

	const SURVEY_ID = 'dev-conditions';
	const TARGET = 'q_target';
	const service = localExpressionService(() => survey);
	const questions = questionsFromSurvey(survey);

	let preset = $state(new URLSearchParams(location.search).get('preset') ?? 'empty');
	const start = $derived(PRESETS.find((p) => p.id === preset) ?? PRESETS[0]);
	let ops = $state<ConditionOp[]>([]);
	let dialogOpen = $state(false);
</script>


<main class="page">
	<h1>Condition builder</h1>
	<p class="intro">
		Condition for <code>{TARGET}</code> (“Tell us more”), using a sample survey's questions.
	</p>

	<label class="preset">
		Start from
		<select bind:value={preset} data-testid="preset">
			{#each PRESETS as p (p.id)}
				<option value={p.id}>{p.label}</option>
			{/each}
		</select>
	</label>

	{#key preset}
		<ConditionBuilder
			{questions}
			value={start.value}
			target={TARGET}
			surveyId={SURVEY_ID}
			{service}
			headingLevel={2}
			onOps={(o) => (ops = o)}
		/>
	{/key}

	<h2>Emitted ops</h2>
	<pre data-testid="ops-log">{ops.length ? JSON.stringify(ops, null, 2) : 'none yet'}</pre>

	<h2>As a dialog</h2>
	<button type="button" class="open" onclick={() => (dialogOpen = true)}>Edit condition…</button>
	<ConditionDialog
		bind:open={dialogOpen}
		title="Edit condition for “Tell us more”"
		{questions}
		value={start.value}
		target={TARGET}
		surveyId={SURVEY_ID}
		{service}
		onOps={(o) => (ops = o)}
	/>
</main>

<style>
	:global(body) {
		background: var(--color-bg);
	}
	.page {
		max-width: 52rem;
		margin: 0 auto;
		padding: var(--space-5);
		color: var(--color-text);
	}
	h1 {
		font-size: var(--text-xl);
	}
	h2 {
		font-size: var(--text-md);
		margin-block-start: var(--space-5);
	}
	.intro {
		color: var(--color-text-muted);
	}
	.preset {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		margin-block-end: var(--space-3);
		font-size: var(--text-sm);
	}
	.preset select,
	.open {
		height: var(--control-height);
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
	}
	pre {
		padding: var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-sunken);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		white-space: pre-wrap;
	}
</style>
