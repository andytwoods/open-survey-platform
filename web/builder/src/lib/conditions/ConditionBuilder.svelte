<script lang="ts">
	import { untrack } from 'svelte';
	import GroupEditor from './GroupEditor.svelte';
	import TextEditor from './TextEditor.svelte';
	import type { ExpressionService } from './service';
	import { astToTree, newGroup, treeToAst } from './tree';
	import type {
		ConditionField,
		ConditionOp,
		ExprDiagnostic,
		ExprNode,
		GroupNode,
		QuestionInfo
	} from './types';
	import { requireAnswered, treeWarnings, type RowWarning } from './warnings';

	/**
	 * "Show this question if…" (builder-design §3, task B7). A tree view (nested All of / Any
	 * of / None of groups of question / operator / value rows) and a text view (CodeMirror),
	 * kept in sync through the server's parser and printer. Apply emits one `set_condition`.
	 */
	let {
		questions,
		value = null,
		target,
		field,
		surveyId = null,
		service,
		onOps,
		oncancel,
		applyLabel = 'Apply',
		headingLevel = 3
	}: {
		/** Questions the condition may use (see `questionsFromSurvey`). */
		questions: readonly QuestionInfo[];
		/** The current condition AST (null: none). Read once, when the builder opens. */
		value?: ExprNode | null;
		/** The question (or branch, quota, variable) the condition belongs to. */
		target: string;
		field?: ConditionField;
		/** With a survey id the server also checks references (forward, deleted). */
		surveyId?: string | null;
		service: ExpressionService;
		onOps: (ops: ConditionOp[]) => void;
		oncancel?: () => void;
		applyLabel?: string;
		/** Level of the builder's own heading, to fit the page's outline. */
		headingLevel?: 2 | 3 | 4;
	} = $props();

	const uid = $props.id();
	const DEBOUNCE_MS = 200;

	const initial = untrack(() => astToTree(value));
	let root = $state<GroupNode>(initial.ok ? initial.root : newGroup('all'));
	let mode = $state<'tree' | 'text'>(initial.ok ? 'tree' : 'text');
	let tooComplex = $state<string | null>(initial.ok ? null : initial.reason);

	let text = $state('');
	/** The text the server last answered for, and its answer. */
	let checked = $state<{ text: string; ok: boolean; ast: ExprNode | null; diagnostics: ExprDiagnostic[] } | null>(
		null
	);
	let pending = $state(0);
	let seq = 0;
	let timer: ReturnType<typeof setTimeout> | undefined;
	let notice = $state('');

	const qmap = $derived(new Map(questions.map((q) => [q.id, q])));
	const compiled = $derived(treeToAst(root, qmap));
	const current = $derived(checked !== null && checked.text === text ? checked : null);
	const diagnostics = $derived(current?.diagnostics ?? []);
	const positioned = $derived(diagnostics.filter((d) => typeof d.start === 'number'));
	const warnings = $derived(treeWarnings(root, qmap, mode === 'tree' ? diagnostics : []));
	const warningsByRow = $derived.by(() => {
		const keys = [...new Set(warnings.map((w) => w.rowKey))];
		return new Map<string, RowWarning[]>(keys.map((k) => [k, warnings.filter((w) => w.rowKey === k)]));
	});
	const otherDiagnostics = $derived(
		diagnostics.filter((d) => typeof d.start !== 'number' && !(mode === 'tree' && d.questionId))
	);

	const canApply = $derived.by(() => {
		if (pending > 0) return false;
		if (mode === 'tree') return compiled.incomplete.length === 0;
		return text.trim() === '' || (current?.ok ?? false);
	});
	const applyBlocker = $derived.by(() => {
		if (pending > 0) return 'Checking…';
		if (mode === 'tree' && compiled.incomplete.length) {
			const n = compiled.incomplete.length;
			return `${n} incomplete condition${n === 1 ? '' : 's'}: complete or remove ${n === 1 ? 'it' : 'them'}.`;
		}
		if (mode === 'text' && !canApply) return 'Fix the errors in the text first.';
		return '';
	});

	async function check(t: string, ast: ExprNode | null) {
		const mine = ++seq;
		pending += 1;
		try {
			if (t.trim() === '') {
				if (mine === seq) checked = { text: t, ok: true, ast: null, diagnostics: [] };
				return;
			}
			const res = await service.parse({ text: t, surveyId, target, field });
			if (mine !== seq) return;
			checked = { text: t, ok: res.ok, ast: res.ok ? res.ast : ast, diagnostics: res.diagnostics };
		} finally {
			pending -= 1;
		}
	}

	/** Tree changed: print its AST to text, then check the text (references, types). */
	async function syncFromTree(ast: ExprNode | null) {
		const mine = ++seq;
		pending += 1;
		try {
			let t = '';
			if (ast) {
				const res = await service.print(ast);
				if (mine !== seq) return;
				if (res.text === null) {
					checked = { text, ok: false, ast: null, diagnostics: res.diagnostics };
					return;
				}
				t = res.text;
			}
			text = t;
			await check(t, ast);
		} finally {
			pending -= 1;
		}
	}

	// Tree view is the source while it is shown: every edit re-derives the text.
	$effect(() => {
		if (mode !== 'tree') return;
		const ast = compiled.ast;
		const snapshot = JSON.stringify(ast);
		clearTimeout(timer);
		timer = setTimeout(() => void syncFromTree(snapshot === undefined ? null : JSON.parse(snapshot)), DEBOUNCE_MS);
	});

	// Opening on a condition the tree cannot show: print it for the text view.
	$effect(() => {
		if (untrack(() => initial.ok) || !value) return;
		const ast = untrack(() => value) as ExprNode;
		void (async () => {
			const res = await service.print(ast);
			if (res.text !== null) {
				text = res.text;
				await check(res.text, ast);
			}
		})();
	});

	/** Text changed (typing): parse it; rebuild the tree when it can be shown. */
	async function textEdited(t: string) {
		text = t;
		clearTimeout(timer);
		timer = setTimeout(() => void parseText(t), DEBOUNCE_MS);
	}

	async function parseText(t: string) {
		await check(t, null);
		if (checked?.text !== t || !checked.ok) return;
		const tree = astToTree(checked.ast);
		if (tree.ok) {
			root = tree.root;
			tooComplex = null;
		} else {
			tooComplex = tree.reason;
		}
	}

	async function showTree() {
		if (mode === 'tree') return;
		clearTimeout(timer);
		if (!current) await parseText(text);
		if (!current?.ok) {
			notice = 'Fix the errors in the text before switching to the visual editor.';
			return;
		}
		if (tooComplex) {
			notice = 'This condition is too complex for the visual editor; edit as text.';
			return;
		}
		notice = '';
		mode = 'tree';
	}

	function showText() {
		notice = '';
		mode = 'text';
	}

	function fix(fixKey: string, question: string) {
		root = requireAnswered(root, fixKey, question);
	}

	function apply() {
		if (!canApply) return;
		const ast = mode === 'tree' ? compiled.ast : text.trim() === '' ? null : (current?.ast ?? null);
		onOps([
			{
				op: 'set_condition',
				params: { target, condition: ast, ...(field ? { field } : {}) }
			}
		]);
	}
</script>

<section class="builder" data-testid="condition-builder" aria-labelledby="{uid}-title">
	<div class="bar">
		<svelte:element this={`h${headingLevel}`} id="{uid}-title" class="title">Show this question if…</svelte:element>
		<div class="toggle" role="group" aria-label="Editor view">
			<button
				type="button"
				data-testid="view-tree"
				aria-pressed={mode === 'tree'}
				aria-disabled={tooComplex ? 'true' : undefined}
				onclick={showTree}>Visual</button
			>
			<button type="button" data-testid="view-text" aria-pressed={mode === 'text'} onclick={showText}>Text</button>
		</div>
	</div>

	{#if tooComplex}
		<p class="banner" role="status" data-testid="too-complex">
			This condition is too complex for the visual editor; edit as text.
		</p>
	{:else if notice}
		<p class="banner" role="status">{notice}</p>
	{/if}

	{#if mode === 'tree'}
		<GroupEditor {root} {questions} {qmap} warnings={warningsByRow} onfix={fix} />
	{:else}
		<p class="help" id="{uid}-help">
			Use <code>and</code>, <code>or</code>, <code>not</code>, comparisons such as <code>age &gt;= 18</code>,
			<code>contains(colours, "red")</code> and <code>answered(q3)</code>.
		</p>
		<TextEditor
			value={text}
			label="Condition text"
			describedBy="{uid}-help {uid}-diags"
			diagnostics={positioned}
			onchange={textEdited}
		/>
	{/if}

	<div id="{uid}-diags" class="diags" aria-live="polite" data-testid="condition-diagnostics">
		{#if mode === 'text'}
			{#each positioned as d, i (i)}
				<p class="diag" data-severity={d.severity ?? 'error'} data-code={d.code}>{d.message}</p>
			{/each}
		{/if}
		{#each otherDiagnostics as d, i (i)}
			<p class="diag" data-severity={d.severity ?? 'error'} data-code={d.code}>{d.message}</p>
		{/each}
	</div>

	{#if mode === 'tree'}
		<details class="preview">
			<summary>As text</summary>
			<code data-testid="condition-preview">{text || '(no condition)'}</code>
		</details>
	{/if}

	<div class="footer">
		{#if applyBlocker}<p class="blocker" id="{uid}-blocker">{applyBlocker}</p>{/if}
		{#if oncancel}<button type="button" class="btn" onclick={oncancel}>Cancel</button>{/if}
		<button
			type="button"
			class="btn primary"
			data-testid="condition-apply"
			aria-disabled={canApply ? undefined : 'true'}
			aria-describedby={applyBlocker ? `${uid}-blocker` : undefined}
			onclick={apply}>{applyLabel}</button
		>
	</div>
</section>

<style>
	.builder {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		color: var(--color-text);
	}
	.bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
	}
	.title {
		margin: 0;
		font-size: var(--text-md);
	}
	.toggle {
		display: inline-flex;
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		overflow: hidden;
	}
	.toggle button {
		padding: var(--space-1) var(--space-3);
		border: 0;
		background: var(--color-surface);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
		cursor: pointer;
	}
	.toggle button[aria-pressed='true'] {
		background: var(--color-accent);
		color: var(--color-on-accent);
	}
	.toggle button[aria-disabled='true'] {
		color: var(--color-text-muted);
		cursor: not-allowed;
	}
	.toggle button:focus-visible,
	.btn:focus-visible {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: -2px;
	}
	.banner {
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-warning);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		font-size: var(--text-sm);
	}
	.help {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.help code,
	.preview code {
		font-family: var(--font-mono);
		color: var(--color-text);
	}
	.diags:empty {
		display: none;
	}
	.diag {
		margin: 0;
		font-size: var(--text-sm);
	}
	.diag[data-severity='error']::before {
		content: 'Error: ';
		color: var(--color-danger);
		font-weight: var(--weight-bold);
	}
	.diag[data-severity='warning']::before {
		content: 'Warning: ';
		font-weight: var(--weight-bold);
	}
	.preview {
		font-size: var(--text-sm);
	}
	.preview summary {
		color: var(--color-text-muted);
		cursor: pointer;
	}
	.preview code {
		display: block;
		margin-block-start: var(--space-1);
		white-space: pre-wrap;
		word-break: break-word;
	}
	.footer {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: flex-end;
		gap: var(--space-2);
	}
	.blocker {
		margin: 0 auto 0 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.btn {
		height: var(--control-height);
		padding: 0 var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
		cursor: pointer;
	}
	.btn.primary {
		background: var(--color-accent);
		border-color: var(--color-accent);
		color: var(--color-on-accent);
	}
	.btn[aria-disabled='true'] {
		opacity: 0.55;
		cursor: not-allowed;
	}
</style>
