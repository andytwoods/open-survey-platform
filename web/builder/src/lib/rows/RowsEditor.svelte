<script lang="ts">
	import GripVertical from '@lucide/svelte/icons/grip-vertical';
	import Plus from '@lucide/svelte/icons/plus';
	import Trash from '@lucide/svelte/icons/trash';
	import { Button, IconButton, announce } from '@osp/ui-components';
	import { tick, untrack } from 'svelte';
	import { labelFallback, labelIn, labelValueIn, splitDiagnostics } from '../choices/model';
	import { dropIndex, dropSlot, keyMoveTarget } from '../choices/reorder';
	import { pipeProblems, RichTextEditor, type PipeCandidate, type RichValue } from '../richtext';
	import RowDeleteDialog from './RowDeleteDialog.svelte';
	import {
		addRowOps,
		deleteRowOps,
		moveRowOps,
		referencingSites,
		renameRowOps,
		rowRequired,
		rowVariable,
		setRequiredOps,
		type RowDiagnostic,
		type RowOp,
		type RowsOutcome,
		type RowsQuestion,
		type RowsSubmit,
		type SpecMatrixRow
	} from './model';

	/**
	 * Grid (matrix) rows editor (task B15): labels in the editing language, reorder by drag
	 * or Alt+↑/↓, add, delete, and a per-row required switch. Holds no survey state: it
	 * shows `question` and sends each gesture as one transaction through `submit`. Labels
	 * are inline rich text (planning/rich-text.md RT5): each row is a read-only textbox until
	 * focused, buffered and sent on blur or Enter. Row ids never change (each row is the
	 * variable `<grid id>_<row id>`). Deleting a row that conditions or piping use asks
	 * first, then deletes with `force`.
	 */
	let {
		question,
		lang,
		defaultLanguage,
		diagnostics = [],
		pointer,
		survey = null,
		pipes = null,
		submit
	}: {
		question: RowsQuestion;
		/** Language the labels are edited in (default: the default language). */
		lang?: string;
		defaultLanguage?: string;
		/** Server diagnostics; those under `pointer` are shown on their row. */
		diagnostics?: readonly RowDiagnostic[] | null;
		/** RFC 6901 pointer to the grid's `rows`. */
		pointer?: string;
		/** The survey, to name the places that refer to a row being deleted. */
		survey?: unknown;
		/** Pipe candidates for the labels' picker (`pipeCandidates`); null offers no chips. */
		pipes?: readonly PipeCandidate[] | null;
		submit: RowsSubmit;
	} = $props();

	const uid = $props.id();
	const rows = $derived(question.rows);
	const editLang = $derived(lang ?? defaultLanguage);

	// --- labels (buffered inside their rich-text fields, keyed by row id: ids are stable) -----

	/** The label fields by row id, to flush a draft before the row moves. */
	let labelFields = $state<Record<string, RichTextEditor | undefined>>({});
	const labelText = (i: number) => labelIn(rows[i]?.label, editLang);
	const nameOf = (i: number) => labelText(i) || `row ${rows[i]?.id ?? i + 1}`;
	const serverDiags = $derived(splitDiagnostics(diagnostics, pointer));
	/** Server diagnostics on a row's pipe chips (planning/rich-text.md §4). */
	const problemsOf = (r: SpecMatrixRow, i: number) =>
		pipes && pointer ? pipeProblems(r.label, editLang ?? 'en', diagnostics ?? [], `${pointer}/${i}/label`) : undefined;

	// --- focus kept across patches (builder-design §7) ---------------------------------------

	let root = $state<HTMLElement | null>(null);
	let pendingFocus: { index: number; field: string; at: number } | null = null;
	const focusAfterPatch = (index: number, field: string) => (pendingFocus = { index, field, at: Date.now() });

	$effect(() => {
		void rows;
		const pf = untrack(() => pendingFocus);
		if (!pf) return;
		pendingFocus = null;
		if (Date.now() - pf.at > 5000) return;
		void tick().then(() => {
			const active = document.activeElement;
			if (active && active !== document.body && !root?.contains(active)) return;
			const sel =
				pf.field === 'add' ? '[data-field="add"]' : `[data-row][data-index="${pf.index}"] [data-field="${pf.field}"]`;
			const el = root?.querySelector<HTMLElement>(sel);
			// A label is a rich-text field: focus its textbox (idle, or the open editor).
			(pf.field === 'label' ? el?.querySelector<HTMLElement>('[role="textbox"]') : el)?.focus();
		});
	});

	function send(ops: RowOp[], options?: { quiet?: readonly string[] }): Promise<RowsOutcome | void> | null {
		if (!ops.length) return null;
		return Promise.resolve(submit(ops, options));
	}

	// --- row edits -------------------------------------------------------------------------

	/**
	 * A label field committed (after a pause, on blur, Enter or teardown). Found by row id,
	 * not index: the row may have moved, or be gone, since the field was typed into.
	 */
	function commitLabel(id: string, value: RichValue) {
		const i = rows.findIndex((r) => r.id === id);
		if (i >= 0) send(renameRowOps(question, i, value, { lang, defaultLanguage }));
	}

	function add() {
		focusAfterPatch(rows.length, 'label');
		if (send(addRowOps(question.id))) announce('Row added');
	}

	function toggleRequired(i: number) {
		const next = !rowRequired(question, rows[i]);
		const name = nameOf(i);
		if (send(setRequiredOps(question, i, next))) announce(`${name} is ${next ? 'required' : 'optional'}`);
	}

	let confirm = $state<{ id: string; name: string; variable: string; sites: string[] } | null>(null);

	async function remove(i: number) {
		const r = rows[i];
		if (!r) return;
		const name = nameOf(i);
		focusAfterPatch(Math.min(i, rows.length - 2), 'label');
		const sent = send(deleteRowOps(question, i), { quiet: ['op.dangling_ref'] });
		if (!sent) return;
		const out = await sent;
		if (!out || out.status === 'applied') return announce(`Deleted ${name}`);
		if (out.status === 'rejected' && out.diagnostics?.[0]?.code === 'op.dangling_ref') {
			pendingFocus = null;
			confirm = {
				id: r.id,
				name,
				variable: rowVariable(question.id, r.id),
				sites: referencingSites(survey, out.diagnostics, editLang)
			};
		}
	}

	async function resolveConfirm(ok: boolean) {
		const c = confirm;
		confirm = null;
		if (!c) return;
		const i = rows.findIndex((r) => r.id === c.id);
		if (!ok || i < 0) {
			announce(`Kept ${c.name}`);
			return;
		}
		focusAfterPatch(Math.min(i, rows.length - 2), 'label');
		const sent = send(deleteRowOps(question, i, true));
		const out = sent && (await sent);
		if (sent && (!out || out.status === 'applied')) announce(`Deleted ${c.name}`);
	}

	function move(from: number, to: number, field: string) {
		const name = nameOf(from);
		focusAfterPatch(to, field);
		if (send(moveRowOps(question, from, to))) announce(`Moved ${name} to position ${to + 1} of ${rows.length}`);
	}

	function onRowKey(e: KeyboardEvent, i: number) {
		if (!e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
		e.preventDefault();
		const to = keyMoveTarget(e, i, rows.length);
		const field = (e.target as HTMLElement | null)?.closest('[data-field]')?.getAttribute('data-field') ?? 'handle';
		if (field === 'label') labelFields[rows[i]?.id]?.flush();
		if (to !== null) move(i, to, field);
	}

	// --- drag (pointer) ----------------------------------------------------------------------

	let list = $state<HTMLElement | null>(null);
	let drag = $state<{ from: number; to: number; dy: number; startY: number; mids: number[]; id: number } | null>(null);
	const slot = $derived(drag ? dropSlot(drag.from, drag.to) : null);

	function dragStart(e: PointerEvent, i: number) {
		if (e.button !== 0 || !list) return;
		e.preventDefault();
		const handle = e.currentTarget as HTMLElement;
		handle.focus();
		handle.setPointerCapture?.(e.pointerId);
		const mids = [...list.querySelectorAll<HTMLElement>(':scope > [data-row]')].map((r) => {
			const b = r.getBoundingClientRect();
			return b.top + b.height / 2;
		});
		drag = { from: i, to: i, dy: 0, startY: e.clientY, mids, id: e.pointerId };
	}

	function dragMove(e: PointerEvent) {
		if (!drag || e.pointerId !== drag.id) return;
		drag.dy = e.clientY - drag.startY;
		drag.to = dropIndex(drag.mids, drag.mids[drag.from] + drag.dy, drag.from);
	}

	function dragEnd(e: PointerEvent) {
		if (!drag || e.pointerId !== drag.id) return;
		const { from, to } = drag;
		drag = null;
		if (from !== to) move(from, to, 'handle');
	}

	function dragCancel() {
		if (drag) announce('Move cancelled');
		drag = null;
	}

	function onHandleKey(e: KeyboardEvent) {
		if (e.key !== 'Escape' || !drag) return;
		e.preventDefault();
		e.stopPropagation();
		dragCancel();
	}

	const handleHint = `${uid}-handle-hint`;
	const gridDefault = $derived(question.required ? 'required' : 'optional');
</script>

<div class="rows-editor" bind:this={root} data-testid="rows-editor">
	{#if serverDiags.general.length}
		<ul class="diags" aria-label="Problems with these rows">
			{#each serverDiags.general as d, n (n)}
				<li data-severity={d.severity}>{d.message}</li>
			{/each}
		</ul>
	{/if}

	<p id={handleHint} class="osp-visually-hidden">Drag to reorder, or press Alt+Up or Alt+Down in a row.</p>
	<p class="hint">
		Each row is its own answer in the data. Rows follow the grid's Required setting ({gridDefault}) unless
		switched here.
	</p>
	<ol class="rows" bind:this={list} aria-label="Rows">
		{#each rows as r, i (r.id)}
			{@const rowDiags = serverDiags.rows.get(i) ?? []}
			{@const msgId = `${uid}-msg-${i}`}
			{@const req = rowRequired(question, r)}
			<!-- svelte-ignore a11y_no_noninteractive_element_interactions (Alt+arrow keys from the row's controls bubble here) -->
			<li
				data-row
				data-index={i}
				data-row-id={r.id}
				class:dragging={drag?.from === i}
				data-drop={slot === i ? 'before' : slot === rows.length && i === rows.length - 1 ? 'after' : undefined}
				style:transform={drag?.from === i ? `translateY(${drag.dy}px)` : undefined}
				onkeydown={(e) => onRowKey(e, i)}
			>
				<button
					type="button"
					class="handle"
					data-field="handle"
					aria-label="Move {nameOf(i)}"
					aria-describedby={handleHint}
					aria-keyshortcuts="Alt+ArrowUp Alt+ArrowDown"
					onpointerdown={(e) => dragStart(e, i)}
					onpointermove={dragMove}
					onpointerup={dragEnd}
					onpointercancel={dragCancel}
					onlostpointercapture={dragCancel}
					onkeydown={onHandleKey}
				>
					<GripVertical size={16} aria-hidden="true" />
				</button>
				<div class="label" data-field="label">
					<RichTextEditor
						bind:this={labelFields[r.id]}
						id="{uid}-label-{r.id}"
						value={labelValueIn(r.label, editLang)}
						level="inline"
						{pipes}
						problems={problemsOf(r, i)}
						label="Label for row {i + 1}"
						placeholder={labelFallback(r.label, editLang)}
						describedBy={rowDiags.length ? msgId : undefined}
						invalid={rowDiags.some((d) => d.severity === 'error')}
						compact
						lang={editLang}
						onCommit={(v) => commitLabel(r.id, v)}
					/>
				</div>
				<IconButton
					icon={Trash}
					label="Delete {nameOf(i)}"
					data-field="delete"
					disabled={rows.length <= 1}
					onclick={() => void remove(i)}
				/>
				<div class="meta">
					<code class="var" title="Variable in the data">{rowVariable(question.id, r.id)}</code>
					<button
						type="button"
						role="switch"
						class="switch"
						data-field="required"
						aria-checked={req}
						aria-label="Required: {nameOf(i)}"
						onclick={() => toggleRequired(i)}
					>
						<span class="track" aria-hidden="true"><span class="thumb"></span></span>
						<span aria-hidden="true">Required</span>
						{#if typeof r.required === 'boolean'}<span class="own" aria-hidden="true">(this row)</span>{/if}
					</button>
				</div>
				{#if rowDiags.length}
					<div class="row-msgs" id={msgId}>
						{#each rowDiags as d, n (n)}
							<p class="msg" data-severity={d.severity}>{d.message}</p>
						{/each}
					</div>
				{/if}
			</li>
		{/each}
	</ol>

	<div class="actions">
		<Button size="sm" data-field="add" onclick={add}>
			<Plus size={16} aria-hidden="true" /> Add row
		</Button>
	</div>

	<RowDeleteDialog request={confirm} onresolve={(ok) => void resolveConfirm(ok)} />
</div>

<style>
	.rows-editor {
		--target: 2.75rem; /* 44 px touch targets */
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		color: var(--color-text);
		font-size: var(--text-sm);
	}
	.hint {
		margin: 0;
		color: var(--color-text-muted);
	}
	.rows {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.rows > li {
		position: relative;
		display: grid;
		grid-template-columns: var(--target) minmax(0, 1fr) var(--target);
		align-items: center;
		gap: var(--space-1) var(--space-2);
		padding: var(--space-1);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
	}
	.rows > li.dragging {
		z-index: 2;
		box-shadow: var(--shadow-lg);
		opacity: 0.92;
	}
	.rows > li[data-drop]::before {
		content: '';
		position: absolute;
		inset-inline: 0;
		height: 3px;
		border-radius: 2px;
		background: var(--color-accent);
	}
	.rows > li[data-drop='before']::before {
		top: -3px;
	}
	.rows > li[data-drop='after']::before {
		bottom: -3px;
	}
	.handle {
		display: inline-grid;
		place-items: center;
		width: var(--target);
		height: var(--target);
		padding: 0;
		border: 0;
		border-radius: var(--radius-sm);
		background: transparent;
		color: var(--color-text-muted);
		cursor: grab;
		touch-action: none;
	}
	.handle:hover {
		background: var(--color-surface-sunken);
		color: var(--color-text);
	}
	.dragging .handle {
		cursor: grabbing;
	}
	.rows-editor :global(.osp-icon-button) {
		width: var(--target);
		height: var(--target);
	}
	.rows-editor :global([data-field='add']) {
		min-height: var(--target);
	}
	.label {
		--osp-rt-height: var(--target);
		min-width: 0;
	}
	.meta {
		grid-column: 2 / -1;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-1) var(--space-3);
		min-width: 0;
	}
	.var {
		min-width: 0;
		overflow-wrap: anywhere;
		font-family: var(--font-mono, ui-monospace, monospace);
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.switch {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		min-height: var(--target);
		padding: 0 var(--space-1);
		border: 0;
		border-radius: var(--radius-sm);
		background: none;
		color: var(--color-text);
		font: inherit;
		cursor: pointer;
	}
	.switch:hover {
		background: var(--color-surface-sunken);
	}
	.switch:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}
	.track {
		position: relative;
		width: 2.25rem;
		height: 1.25rem;
		border-radius: var(--radius-full);
		background: var(--color-surface-sunken);
		border: 1px solid var(--color-border-strong);
	}
	.thumb {
		position: absolute;
		top: 1px;
		left: 1px;
		width: calc(1.25rem - 4px);
		height: calc(1.25rem - 4px);
		border-radius: var(--radius-full);
		background: var(--color-text-muted);
		transition: transform 120ms;
	}
	.switch[aria-checked='true'] .track {
		background: var(--color-accent);
		border-color: var(--color-accent);
	}
	.switch[aria-checked='true'] .thumb {
		background: var(--color-on-accent);
		transform: translateX(1rem);
	}
	.own {
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.row-msgs {
		grid-column: 2 / -1;
	}
	.msg {
		margin: 0;
		font-size: var(--text-xs);
	}
	.msg[data-severity='error'],
	.diags [data-severity='error'] {
		color: var(--color-danger);
	}
	.msg[data-severity='warning'],
	.diags [data-severity='warning'] {
		color: var(--color-warning);
	}
	.diags {
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		list-style: none;
	}
	.actions {
		display: flex;
		gap: var(--space-2);
	}
</style>
