<script lang="ts">
	import X from '@lucide/svelte/icons/x';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import { comparableQuestions, operatorsForRow } from './operators';
	import {
		choiceLiteral,
		fitRowToOperator,
		fitRowToQuestion,
		literalText,
		numberLiteral,
		rowProblem,
		rowValueKind
	} from './tree';
	import type { QuestionInfo, RowNode, OperatorId } from './types';
	import type { RowWarning } from './warnings';

	/** One "question / operator / value" row. Edits mutate `row` (a $state proxy). */
	let {
		row,
		label,
		questions,
		qmap,
		warnings = [],
		onremove,
		onfix
	}: {
		row: RowNode;
		/** e.g. "Condition 1.2": names the row's controls for assistive tech. */
		label: string;
		questions: readonly QuestionInfo[];
		qmap: ReadonlyMap<string, QuestionInfo>;
		warnings?: readonly RowWarning[];
		onremove: () => void;
		onfix: (fixKey: string, question: string) => void;
	} = $props();

	const uid = $props.id();
	const question = $derived(qmap.get(row.question));
	const operators = $derived(operatorsForRow(question, row.op));
	const valueKind = $derived(rowValueKind(row, question));
	const problem = $derived(rowProblem(row, question));
	const unknown = $derived(row.question !== '' && !question);
	const others = $derived(comparableQuestions(questions, question));
	const choiceValue = $derived(row.value ? literalText(row.value) : '');
	const choiceKnown = $derived(question?.choices.some((c) => String(c.value) === choiceValue) ?? false);

	function optionLabel(q: QuestionInfo): string {
		return q.label ? `${q.id}: ${q.label}` : q.id;
	}

	function setQuestion(id: string) {
		const previousType = question?.type;
		row.question = id;
		fitRowToQuestion(row, qmap.get(id), previousType);
	}

	function setOperator(op: string) {
		const previousKind = valueKind;
		row.op = (op || null) as OperatorId | null;
		fitRowToOperator(row, question, previousKind);
	}

	function setNumber(text: string) {
		row.draft = text;
		row.value = numberLiteral(text);
	}

	function setText(text: string) {
		row.draft = text;
		row.value = text === '' ? null : { kind: 'text', value: text };
	}

	function setChoice(v: string) {
		const choice = question?.choices.find((c) => String(c.value) === v);
		row.value = choice ? choiceLiteral(choice.value) : null;
	}

	function setRef(id: string) {
		row.value = id ? { kind: 'ref', id } : null;
	}
</script>

<li class="row" data-key={row.key} data-testid="condition-row" data-incomplete={problem ? 'true' : undefined}>
	<div class="controls" role="group" aria-label={label}>
		<label class="field">
			<span class="osp-visually-hidden">{label}: question</span>
			<select
				class="ctl question"
				data-role="question"
				value={row.question}
				aria-invalid={unknown ? 'true' : undefined}
				onchange={(e) => setQuestion(e.currentTarget.value)}
			>
				<option value="">Choose a question…</option>
				{#each questions as q (q.id)}
					<option value={q.id}>{optionLabel(q)}</option>
				{/each}
				{#if unknown}
					<option value={row.question}>{row.question} (deleted)</option>
				{/if}
			</select>
		</label>

		{#if row.question}
			<label class="field">
				<span class="osp-visually-hidden">{label}: operator</span>
				<select
					class="ctl op"
					data-role="operator"
					value={row.op ?? ''}
					onchange={(e) => setOperator(e.currentTarget.value)}
				>
					{#if !row.op}<option value="">Choose…</option>{/if}
					{#each operators as o (o.id)}
						<option value={o.id}>{o.label}</option>
					{/each}
				</select>
			</label>
		{/if}

		{#if row.op && valueKind !== 'none'}
			<label class="field">
				<span class="osp-visually-hidden">{label}: value</span>
				{#if valueKind === 'number'}
					<input
						class="ctl value"
						data-role="value"
						type="text"
						inputmode="decimal"
						autocomplete="off"
						placeholder="number"
						value={row.draft ?? literalText(row.value)}
						aria-invalid={row.draft && !row.value ? 'true' : undefined}
						oninput={(e) => setNumber(e.currentTarget.value)}
					/>
				{:else if valueKind === 'text'}
					<input
						class="ctl value"
						data-role="value"
						type="text"
						autocomplete="off"
						placeholder="text"
						value={row.draft ?? literalText(row.value)}
						oninput={(e) => setText(e.currentTarget.value)}
					/>
				{:else if valueKind === 'choice'}
					<select
						class="ctl value"
						data-role="value"
						value={choiceValue}
						onchange={(e) => setChoice(e.currentTarget.value)}
					>
						<option value="">Choose a choice…</option>
						{#each question?.choices ?? [] as c (c.value)}
							<option value={String(c.value)}>{c.label}</option>
						{/each}
						{#if row.value && !choiceKnown}
							<option value={choiceValue}>{choiceValue} (not a choice)</option>
						{/if}
					</select>
				{:else}
					<select
						class="ctl value"
						data-role="value"
						value={row.value?.kind === 'ref' ? String(row.value.id) : ''}
						onchange={(e) => setRef(e.currentTarget.value)}
					>
						<option value="">Choose a question…</option>
						{#each others as q (q.id)}
							<option value={q.id}>{optionLabel(q)}</option>
						{/each}
						{#if row.value?.kind === 'ref' && !qmap.has(String(row.value.id))}
							<option value={String(row.value.id)}>{row.value.id} (deleted)</option>
						{/if}
					</select>
				{/if}
			</label>
		{/if}

		<button type="button" class="remove" aria-label="Remove {label.toLowerCase()}" title="Remove" onclick={onremove}>
			<X size={16} aria-hidden="true" />
		</button>
	</div>

	{#if problem && row.question}
		<p class="hint" id="{uid}-problem">{problem}</p>
	{/if}
	{#if warnings.length}
		<ul class="warnings">
			{#each warnings as w, i (i)}
				<li class="warning" data-kind={w.kind} data-code={w.code}>
					<TriangleAlert size={14} aria-hidden="true" />
					<span>{w.message}</span>
					{#if w.kind === 'may-be-unanswered' && w.fixKey}
						<button type="button" class="fix" onclick={() => onfix(w.fixKey as string, w.question)}>
							Also require answered
						</button>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</li>

<style>
	.row {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		padding: var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
	}
	.controls {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
	}
	.field {
		display: contents;
	}
	.ctl {
		height: var(--control-height);
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
	}
	.question {
		min-width: 12rem;
		max-width: 20rem;
	}
	.value {
		min-width: 7rem;
	}
	input.value {
		width: 9rem;
	}
	.ctl[aria-invalid='true'] {
		border-color: var(--color-danger);
	}
	.ctl:focus-visible,
	.remove:focus-visible,
	.fix:focus-visible {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 1px;
	}
	.remove {
		display: inline-grid;
		place-items: center;
		width: 2rem;
		height: 2rem;
		margin-inline-start: auto;
		border: 0;
		border-radius: var(--radius-sm);
		background: transparent;
		color: var(--color-text-muted);
		cursor: pointer;
	}
	.remove:hover {
		background: var(--color-surface-sunken);
		color: var(--color-text);
	}
	.hint {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.warnings {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.warning {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
		color: var(--color-text);
		font-size: var(--text-xs);
	}
	.warning :global(svg) {
		color: var(--color-warning);
		flex: none;
	}
	.warning[data-kind='unknown-question'] :global(svg),
	.warning[data-code^='ref.'] :global(svg) {
		color: var(--color-danger);
	}
	.fix {
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
		color: var(--color-text);
		font: inherit;
		cursor: pointer;
	}
	.fix:hover {
		background: var(--color-surface-sunken);
	}
</style>
