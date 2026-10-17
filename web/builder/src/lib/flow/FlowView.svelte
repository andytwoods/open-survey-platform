<script lang="ts">
	import LayersPlus from '@lucide/svelte/icons/layers-plus';
	import Plus from '@lucide/svelte/icons/plus';
	import { announce, Button, Dialog } from '@osp/ui-components';
	import { onMount, tick, untrack } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { api } from '../api';
	import { apiExpressionService, ConditionDialog, questionsFromSurvey } from '../conditions';
	import type { ConditionOp, ExprNode, QuestionInfo } from '../conditions';
	import type { SurveyStore } from '../sync/survey-store.svelte';
	import type { Diagnostic } from '../sync/transport';
	import { addBlockPlan } from '../structure/ops';
	import { setFlowCtx } from './context';
	import FlowList from './FlowList.svelte';
	import { flowUi } from './flow-ui.svelte';
	import {
		assignedVariables,
		blocks,
		defaultLanguage,
		describeSlot,
		descendantCount,
		diagnosticsByNode,
		dropTarget,
		emptyForm,
		flowOf,
		formError,
		insertOps,
		keyMoveTarget,
		moveOp,
		NODE_TYPES,
		parseGap,
		nodeLabel,
		quotas,
		TYPE_LABEL,
		unavailable,
		unusedBlocks,
		walk,
		type ListRef,
		type NewNodeForm
	} from './model';

	/**
	 * The flow editor (builder-design §3, task B8): the survey flow as a nested list of
	 * block, branch, randomiser, assign, quotaCheck and end cards. Every edit is an op
	 * through the store; validity and reachability come from the server's diagnostics.
	 * `onOpenConditionEditor` replaces the built-in condition dialog for branch conditions.
	 */
	let {
		store,
		onOpenConditionEditor,
		onOpenEnding
	}: {
		store: SurveyStore;
		onOpenConditionEditor?: (nodeId: string) => void;
		/** Opens Survey settings → Endings at an outcome (the End card's "Edit ending"). */
		onOpenEnding?: (outcome: string) => void;
	} = $props();

	const uid = $props.id();
	const survey = $derived(store.survey);
	const rows = $derived(walk(survey));
	const language = $derived(defaultLanguage(survey));

	// The store only learns diagnostics from edits; on open, ask the server for them.
	let loaded = $state<{ revision: number; diagnostics: Diagnostic[] } | null>(null);
	onMount(() => {
		const id = untrack(() => store.surveyId);
		void api
			.GET('/api/surveys/{survey_id}', { params: { path: { survey_id: id } } })
			.then(({ data }) => {
				if (data) loaded = { revision: data.revision, diagnostics: data.diagnostics ?? [] };
			})
			.catch(() => {});
	});
	const diagnostics = $derived(
		loaded && store.revision <= loaded.revision ? loaded.diagnostics : store.diagnostics
	);
	const byNode = $derived(diagnosticsByNode(rows, diagnostics));
	const problems = $derived([...byNode.values()].reduce((n, d) => n + d.length, 0));
	const unused = $derived(unusedBlocks(survey));

	const collapsed = new SvelteSet<string>();
	let dragging = $state<string | null>(null);
	let overGap = $state<string | null>(null);

	async function focusNode(id: string) {
		await tick();
		document.querySelector<HTMLElement>(`[data-flow-handle="${CSS.escape(id)}"]`)?.focus();
	}

	async function moveTo(id: string, to: ListRef & { index: number }) {
		const out = await store.submit([moveOp(id, to)]);
		if (out.status !== 'applied') return;
		const row = walk(store.survey).find((r) => r.id === id);
		announce(`Moved to ${row ? describeSlot(store.survey, row) : 'new position'}.`);
		void focusNode(id);
	}

	// --- add ---------------------------------------------------------------------------
	let addOpen = $state(false);
	let addAt = $state<ListRef & { index: number }>({ parent: null, arm: null, index: 0 });
	let form = $state<NewNodeForm>(emptyForm(null));
	let addError = $state('');
	let focusAfterClose: string | null = null;

	function openAdd(at: ListRef & { index: number }) {
		addAt = at;
		const keep = form.type;
		form = emptyForm(store.survey, unavailable(store.survey, keep) ? 'end' : keep);
		addError = '';
		addOpen = true;
	}

	async function submitAdd(e: SubmitEvent) {
		e.preventDefault();
		const err = formError(form);
		if (err) {
			addError = err;
			return;
		}
		const { id, ops } = insertOps(store.survey, form, addAt, language);
		const out = await store.submit(ops);
		if (out.status === 'rejected') {
			addError = [out.message, ...out.diagnostics.map((d) => d.message)].join(' ');
			return;
		}
		if (out.status !== 'applied') return;
		focusAfterClose = id;
		addOpen = false;
		announce(`${TYPE_LABEL[form.type]} added.`);
	}

	$effect(() => {
		if (flowUi.addRequests === 0) return;
		untrack(() => openAdd({ parent: null, arm: null, index: flowOf(store.survey).length }));
	});

	// --- add block (B20): a new block with one page, shown at the end of the flow --------
	async function addBlock() {
		const plan = addBlockPlan(store.survey, []);
		const out = await store.submit(plan.ops);
		if (out.status !== 'applied') return;
		const row = walk(store.survey).find((r) => r.type === 'block' && r.node.block === plan.id);
		announce('Block added at the end of the flow, with one page. Add its questions in the Questions view.');
		if (row) void focusNode(row.id);
	}

	$effect(() => {
		if (flowUi.addBlockRequests === 0) return;
		untrack(() => void addBlock());
	});

	// --- delete ------------------------------------------------------------------------
	let confirmId = $state<string | null>(null);
	let confirmOpen = $state(false);
	const confirmRow = $derived(rows.find((r) => r.id === confirmId));

	async function doDelete(id: string) {
		const row = walk(store.survey).find((r) => r.id === id);
		const label = row ? nodeLabel(row.node, store.survey) : id;
		const out = await store.submit([{ op: 'delete_flow_node', params: { id } }]);
		confirmOpen = false;
		if (out.status !== 'applied') return;
		announce(`Deleted ${label}.`);
		// Focus the node now at the same place, else the add button there.
		await tick();
		const list = row ? document.querySelectorAll<HTMLElement>('[data-flow-handle]') : null;
		const next = row
			? walk(store.survey).find((r) => r.parent === row.parent && r.arm === row.arm && r.index === row.index)
			: undefined;
		if (next) void focusNode(next.id);
		else list?.[0]?.focus();
	}

	function remove(id: string) {
		const row = rows.find((r) => r.id === id);
		if (row && descendantCount(row.node) > 0) {
			confirmId = id;
			confirmOpen = true;
		} else void doDelete(id);
	}

	// --- conditions (B7's builder) -----------------------------------------------------
	let condOpen = $state(false);
	let condId = $state('');
	const condRow = $derived(rows.find((r) => r.id === condId));
	const service = apiExpressionService(api);
	const questions = $derived<QuestionInfo[]>([
		...questionsFromSurvey(survey, language),
		// Assigned variables can be tested like single-choice questions over their levels.
		...assignedVariables(survey).map((v) => ({
			id: v.id,
			type: 'single',
			label: `${v.id} (assigned variable)`,
			choices: v.levels.map((l) => ({ value: l, label: l })),
			required: true,
			conditional: false
		}))
	]);

	function openCondition(id: string) {
		if (onOpenConditionEditor) return onOpenConditionEditor(id);
		condId = id;
		condOpen = true;
	}

	async function applyCondition(ops: ConditionOp[]) {
		const out = await store.submit(ops as unknown as { op: string; params: Record<string, unknown> }[]);
		if (out.status === 'applied') announce('Condition updated.');
	}

	setFlowCtx({
		get store() {
			return store;
		},
		get survey() {
			return store.survey;
		},
		get language() {
			return language;
		},
		get diagnostics() {
			return byNode;
		},
		get dragging() {
			return dragging;
		},
		get overGap() {
			return overGap;
		},
		isCollapsed: (id) => collapsed.has(id),
		toggle: (id) => {
			if (collapsed.has(id)) collapsed.delete(id);
			else collapsed.add(id);
		},
		openAdd,
		remove,
		moveBy: (id, dir) => {
			const to = keyMoveTarget(store.survey, id, dir);
			if (!to) return announce(dir < 0 ? 'Already at the start of the flow.' : 'Already at the end of the flow.');
			void moveTo(id, to);
		},
		dragStart: (id) => (dragging = id),
		dragOver: (gap) => (overGap = gap),
		dragEnd: () => {
			if (dragging) announce('Move cancelled.');
			dragging = overGap = null;
		},
		drop: () => {
			const id = dragging;
			const gap = parseGap(overGap);
			dragging = overGap = null;
			if (!id || !gap) return;
			const to = dropTarget(store.survey, id, gap);
			if (to) void moveTo(id, to);
		},
		openCondition,
		openEnding: (outcome) => onOpenEnding?.(outcome)
	});

	const typeReasons = $derived(Object.fromEntries(NODE_TYPES.map((t) => [t, unavailable(survey, t)])));
	const blockList = $derived(blocks(survey));
	const varList = $derived(assignedVariables(survey));
	const quotaList = $derived(quotas(survey));
</script>

<div class="flow-view">
	<div class="head">
		<div>
			<h2 id="flow-heading">Survey flow</h2>
			<p class="muted" id="flow-move-hint">
				Participants go through these nodes from top to bottom. Drag a card by its handle, or focus the
				handle and press Alt+Up or Alt+Down, to move it (also into and out of branches).
			</p>
		</div>
		<div class="head-actions">
			<Button onclick={() => void addBlock()}>
				<LayersPlus size={16} aria-hidden="true" />
				Add block
			</Button>
			<Button variant="primary" onclick={() => openAdd({ parent: null, arm: null, index: flowOf(survey).length })}>
				<Plus size={16} aria-hidden="true" />
				Add node
			</Button>
		</div>
	</div>

	{#if problems || unused.length}
		<p class="summary" role="status">
			{#if problems}{problems} flow {problems === 1 ? 'problem' : 'problems'} flagged below.{/if}
			{#if unused.length}
				Not in the flow: {unused.map((b) => b.label).join(', ')}.
			{/if}
		</p>
	{/if}

	<FlowList nodes={flowOf(survey)} label="Survey flow" />
</div>

<Dialog
	bind:open={addOpen}
	title="Add flow node"
	description="Insert at {describeSlot(survey, addAt)}."
	onCloseAutoFocus={(e) => {
		if (focusAfterClose) {
			e.preventDefault();
			void focusNode(focusAfterClose);
			focusAfterClose = null;
		}
	}}
>
	<form id="flow-add-form" class="add-form" onsubmit={submitAdd}>
		<div class="field">
			<label for="{uid}-f1">Node type</label>
			<select id="{uid}-f1" bind:value={form.type} onchange={() => (form = emptyForm(store.survey, form.type))}>
				{#each NODE_TYPES as t (t)}
					<option value={t} disabled={!!typeReasons[t]}>{TYPE_LABEL[t]}{typeReasons[t] ? ` (${typeReasons[t]})` : ''}</option>
				{/each}
			</select>
		</div>

		{#if form.type === 'block'}
			<div class="field">
				<label for="{uid}-f2">Block</label>
				<select id="{uid}-f2" bind:value={form.block}>
					{#each blockList as b (b.id)}
						<option value={b.id}>{b.label}{b.placed ? ' (already in the flow)' : ''}</option>
					{/each}
				</select>
			</div>
		{:else if form.type === 'branch'}
			<div class="field">
				<label for="{uid}-f3">Condition</label>
				<input id="{uid}-f3" bind:value={form.condition} placeholder="consent == 0" autocomplete="off" spellcheck="false" />
			</div>
			<p class="muted">Write the condition as text; refine it later with “Edit condition…”.</p>
		{:else if form.type === 'randomiser'}
			<div class="field">
				<label for="{uid}-f4">First block</label>
				<select id="{uid}-f4" bind:value={form.randomiserBlock}>
					{#each blockList as b (b.id)}
						<option value={b.id}>{b.label}{b.placed ? ' (already in the flow)' : ''}</option>
					{/each}
				</select>
			</div>
			<p class="muted">A randomiser needs at least one child. Add more with its “+” buttons.</p>
		{:else if form.type === 'assign'}
			<fieldset class="field">
				<legend>Variables to assign</legend>
				{#each varList as v (v.id)}
					<label class="check">
						<input type="checkbox" value={v.id} bind:group={form.variables} />
						{v.id} <span class="muted">({v.levels.join(' / ')})</span>
					</label>
				{/each}
			</fieldset>
		{:else if form.type === 'quotaCheck'}
			<div class="field">
				<label for="{uid}-f5">Quota</label>
				<select id="{uid}-f5" bind:value={form.quota}>
					{#each quotaList as q (q.id)}<option value={q.id}>{q.id} (limit {q.limit ?? '?'})</option>{/each}
				</select>
			</div>
		{:else if form.type === 'end'}
			<div class="field">
				<label for="{uid}-f6">Outcome</label>
				<input id="{uid}-f6" bind:value={form.outcome} autocomplete="off" spellcheck="false" />
			</div>
			<div class="field">
				<label for="{uid}-f7">Message (optional)</label>
				<input id="{uid}-f7" bind:value={form.message} autocomplete="off" />
			</div>
		{/if}

		{#if addError}<p class="error" role="alert">{addError}</p>{/if}
	</form>
	{#snippet footer()}
		<Button onclick={() => (addOpen = false)}>Cancel</Button>
		<Button variant="primary" type="submit" form="flow-add-form">Add</Button>
	{/snippet}
</Dialog>

<Dialog
	bind:open={confirmOpen}
	title="Delete {confirmRow ? nodeLabel(confirmRow.node, survey) : 'node'}?"
	description={confirmRow
		? `This also deletes the ${descendantCount(confirmRow.node)} ${descendantCount(confirmRow.node) === 1 ? 'node' : 'nodes'} inside it. Blocks stay in the survey. You can undo this.`
		: undefined}
	size="sm"
>
	{#snippet footer()}
		<Button onclick={() => (confirmOpen = false)}>Cancel</Button>
		<Button variant="danger" onclick={() => confirmId && void doDelete(confirmId)}>Delete</Button>
	{/snippet}
</Dialog>

{#if condRow}
	<ConditionDialog
		bind:open={condOpen}
		title="Edit branch condition"
		description="Participants go down “Then” when this is true, otherwise down “Otherwise”."
		{questions}
		value={(condRow.node.if ?? null) as ExprNode | null}
		target={condRow.id}
		field="if"
		heading="Branch if…"
		surveyId={store.surveyId}
		{service}
		onOps={(ops) => void applyCondition(ops)}
	/>
{/if}

<style>
	.flow-view {
		max-width: 56rem;
		margin: 0 auto;
		padding: var(--space-4);
	}
	.head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-4);
		margin-block-end: var(--space-2);
	}
	.head-actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		justify-content: flex-end;
	}
	h2 {
		margin: 0;
		font-size: var(--text-lg);
	}
	.muted {
		margin: var(--space-1) 0 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.summary {
		margin: 0 0 var(--space-2);
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-sm);
		background: var(--color-surface-sunken);
		font-size: var(--text-sm);
	}
	.add-form {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		margin: 0;
		padding: 0;
		border: 0;
		font-size: var(--text-sm);
	}
	.field > label,
	legend {
		font-weight: var(--weight-bold);
	}
	.field select,
	.field input:not([type='checkbox']) {
		min-height: 2.25rem;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-sm);
		background: var(--color-bg);
		color: var(--color-text);
		font: inherit;
	}
	.field select:focus-visible,
	.field input:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}
	.check {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.error {
		margin: 0;
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
</style>
