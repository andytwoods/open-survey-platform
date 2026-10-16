<script lang="ts">
	import Copy from '@lucide/svelte/icons/copy';
	import GripVertical from '@lucide/svelte/icons/grip-vertical';
	import Plus from '@lucide/svelte/icons/plus';
	import ClipboardPaste from '@lucide/svelte/icons/clipboard-paste';
	import Trash from '@lucide/svelte/icons/trash';
	import { Button, IconButton, announce } from '@osp/ui-components';
	import { tick, untrack } from 'svelte';
	import CodeChangeDialog from './CodeChangeDialog.svelte';
	import PastePanel from './PastePanel.svelte';
	import SharedLists from './SharedLists.svelte';
	import {
		codeErrors,
		codeKey,
		labelFallback,
		labelIn,
		mixedTypes,
		splitDiagnostics,
		type ChoiceDiagnostic,
		type ChoiceOp,
		type ChoiceQuestion,
		type SpecChoice,
		type SpecChoiceList
	} from './model';
	import {
		addChoiceOps,
		deleteChoiceOps,
		duplicateChoiceOps,
		moveChoiceOps,
		setCodeOps,
		setLabelOps
	} from './ops';
	import { dropIndex, dropSlot, keyMoveTarget } from './reorder';

	/**
	 * Choice list editor (builder-design §3): codes + labels, reorder by drag or Alt+↑/↓,
	 * add / duplicate / delete, bulk paste, shared lists. Holds no survey state: it shows
	 * `question` (inline choices, or its shared list from `choiceLists`) and reports every
	 * gesture as one transaction through `onOps`. Typed text is buffered and sent on blur
	 * or Enter; invalid codes are flagged and never sent.
	 */
	let {
		question,
		choiceLists = [],
		usage = {},
		lang,
		defaultLanguage,
		publishedVersions = 0,
		diagnostics = [],
		pointer,
		onOps
	}: {
		/** The single/multi question whose choices are edited. */
		question: ChoiceQuestion;
		/** The survey's shared choice lists. */
		choiceLists?: readonly SpecChoiceList[];
		/** Shared list id → ids of the questions using it (see `listUsage`). */
		usage?: Readonly<Record<string, readonly string[]>>;
		/** Language the labels are edited in (default: the default language). */
		lang?: string;
		defaultLanguage?: string;
		/** Published versions of the survey: changing a code then asks for confirmation. */
		publishedVersions?: number;
		/** Server diagnostics; those under `pointer` are shown on their row. */
		diagnostics?: readonly ChoiceDiagnostic[] | null;
		/** RFC 6901 pointer to the shown choices (see `choicesPointer`). */
		pointer?: string;
		onOps: (ops: ChoiceOp[]) => void;
	} = $props();

	const uid = $props.id();
	const shared = $derived(
		question.choiceList ? (choiceLists.find((l) => l.id === question.choiceList) ?? null) : null
	);
	const owner = $derived(question.choiceList ?? question.id);
	const choices: readonly SpecChoice[] = $derived(
		question.choiceList ? (shared?.choices ?? []) : (question.choices ?? [])
	);
	const editLang = $derived(lang ?? defaultLanguage);

	/** Stable row keys: the code as text (codes are unique; a repeat gets a suffix). */
	const keys = $derived.by(() => {
		// Local to this computation, not state.
		// eslint-disable-next-line svelte/prefer-svelte-reactivity
		const seen = new Map<string, number>();
		return choices.map((c) => {
			const k = codeKey(c.value);
			const n = seen.get(k) ?? 0;
			seen.set(k, n + 1);
			return n ? `${k}#${n}` : k;
		});
	});

	// --- typed text buffers ----------------------------------------------------------------

	type Draft = { value: string; sent: boolean };
	let codeDrafts = $state<Record<string, Draft>>({});
	let labelDrafts = $state<Record<string, Draft>>({});

	const codeText = (i: number) => codeDrafts[keys[i]]?.value ?? codeKey(choices[i]?.value);
	const labelText = (i: number) => labelDrafts[keys[i]]?.value ?? labelIn(choices[i]?.label, editLang);

	const errors = $derived(codeErrors(choices.map((_, i) => codeText(i))));
	const serverDiags = $derived(splitDiagnostics(diagnostics, pointer));
	const mixed = $derived(mixedTypes(choices.map((c) => c.value)));

	// New props (the server applied something): drop buffers that were sent.
	$effect(() => {
		void choices;
		untrack(() => {
			for (const m of [codeDrafts, labelDrafts]) for (const k of Object.keys(m)) if (m[k].sent) delete m[k];
		});
	});

	// --- focus kept across patches (builder-design §7) ---------------------------------------

	let root = $state<HTMLElement | null>(null);
	let pendingFocus: { index: number; field: string; at: number } | null = null;

	function focusAfterPatch(index: number, field: string) {
		pendingFocus = { index, field, at: Date.now() };
	}

	$effect(() => {
		void choices;
		const pf = untrack(() => pendingFocus);
		if (!pf) return;
		pendingFocus = null;
		if (Date.now() - pf.at > 5000) return;
		void tick().then(() => {
			const active = document.activeElement;
			if (active && active !== document.body && !root?.contains(active)) return;
			const sel =
				pf.field === 'add'
					? '[data-field="add"]'
					: `[data-row][data-index="${pf.index}"] [data-field="${pf.field}"]`;
			root?.querySelector<HTMLElement>(sel)?.focus();
		});
	});

	function send(ops: ChoiceOp[]): boolean {
		if (!ops.length) return false;
		onOps(ops);
		return true;
	}

	const nameOf = (i: number) => labelText(i) || `code ${codeText(i)}`;

	// --- row edits -------------------------------------------------------------------------

	let confirm = $state<{ index: number; key: string; from: string; to: string } | null>(null);

	function sendCode(i: number) {
		const k = keys[i];
		const d = codeDrafts[k];
		if (!d) return;
		const refocus = document.activeElement?.getAttribute('data-field') === 'code';
		if (send(setCodeOps(owner, choices, i, d.value))) {
			d.sent = true;
			if (refocus) focusAfterPatch(i, 'code');
		}
	}

	function commitCode(i: number) {
		const k = keys[i];
		const d = codeDrafts[k];
		if (!d || d.sent) return;
		if (d.value.trim() === codeKey(choices[i]?.value)) {
			delete codeDrafts[k];
			return;
		}
		if (errors[i]) {
			announce(`Code not saved: ${errors[i]}`);
			return;
		}
		if (publishedVersions > 0) {
			confirm = { index: i, key: k, from: codeKey(choices[i].value), to: d.value.trim() };
			return;
		}
		sendCode(i);
	}

	function resolveConfirm(ok: boolean) {
		const c = confirm;
		confirm = null;
		if (!c) return;
		if (ok && keys[c.index] === c.key) sendCode(c.index);
		else delete codeDrafts[c.key];
	}

	function commitLabel(i: number) {
		const k = keys[i];
		const d = labelDrafts[k];
		if (!d || d.sent) return;
		if (send(setLabelOps(owner, choices, i, d.value, { lang, defaultLanguage }))) d.sent = true;
		else delete labelDrafts[k];
	}

	function onInputKey(e: KeyboardEvent, i: number, field: 'code' | 'label') {
		const drafts = field === 'code' ? codeDrafts : labelDrafts;
		if (e.key === 'Enter') {
			e.preventDefault();
			if (field === 'code') commitCode(i);
			else commitLabel(i);
		} else if (e.key === 'Escape' && drafts[keys[i]] && !drafts[keys[i]].sent) {
			e.preventDefault();
			e.stopPropagation();
			delete drafts[keys[i]];
		}
	}

	function add() {
		focusAfterPatch(choices.length, 'label');
		if (send(addChoiceOps(owner))) announce('Choice added');
	}

	function duplicate(i: number) {
		focusAfterPatch(i + 1, 'label');
		if (send(duplicateChoiceOps(owner, choices, i))) announce(`Duplicated ${nameOf(i)}`);
	}

	function remove(i: number) {
		const name = nameOf(i);
		focusAfterPatch(Math.min(i, choices.length - 2), 'label');
		if (send(deleteChoiceOps(owner, choices, i))) announce(`Deleted ${name}`);
	}

	function move(from: number, to: number, field: string) {
		const name = nameOf(from);
		focusAfterPatch(to, field);
		if (send(moveChoiceOps(owner, choices, from, to)))
			announce(`Moved ${name} to position ${to + 1} of ${choices.length}`);
	}

	function onRowKey(e: KeyboardEvent, i: number) {
		if (!e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
		e.preventDefault();
		const to = keyMoveTarget(e, i, choices.length);
		const field = (e.target as HTMLElement | null)?.getAttribute('data-field') ?? 'handle';
		if (field === 'code') commitCode(i);
		if (field === 'label') commitLabel(i);
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

	let pasting = $state(false);
	const handleHint = `${uid}-handle-hint`;
</script>

<div class="choice-editor" bind:this={root} data-testid="choice-editor">
	<SharedLists {question} {choiceLists} {usage} {choices} {onOps} />

	{#if serverDiags.general.length || mixed}
		<ul class="diags" aria-label="Problems with these choices">
			{#each serverDiags.general as d, n (n)}
				<li data-severity={d.severity}>{d.message}</li>
			{/each}
			{#if mixed}
				<li data-severity="warning">This list mixes number and text codes.</li>
			{/if}
		</ul>
	{/if}

	<p id={handleHint} class="osp-visually-hidden">
		Drag to reorder, or press Alt+Up or Alt+Down in a row.
	</p>
	<div class="head" aria-hidden="true">
		<span></span><span>Code</span><span>Label{editLang ? ` (${editLang})` : ''}</span>
	</div>
	<ol class="rows" bind:this={list} aria-label="Choices">
		{#each choices as c, i (keys[i])}
			{@const err = errors[i]}
			{@const rowDiags = serverDiags.rows.get(i) ?? []}
			{@const errId = `${uid}-err-${i}`}
			<!-- svelte-ignore a11y_no_noninteractive_element_interactions (Alt+arrow keys from the row's controls bubble here) -->
			<li
				data-row
				data-index={i}
				data-code={codeKey(c.value)}
				class:dragging={drag?.from === i}
				data-drop={slot === i ? 'before' : slot === choices.length && i === choices.length - 1 ? 'after' : undefined}
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
				<input
					class="code"
					data-field="code"
					aria-label="Code for choice {i + 1}"
					aria-invalid={err || rowDiags.some((d) => d.severity === 'error') ? 'true' : undefined}
					aria-describedby={err || rowDiags.length ? errId : undefined}
					autocomplete="off"
					spellcheck="false"
					value={codeText(i)}
					oninput={(e) => (codeDrafts[keys[i]] = { value: e.currentTarget.value, sent: false })}
					onblur={() => commitCode(i)}
					onkeydown={(e) => onInputKey(e, i, 'code')}
				/>
				<input
					class="label"
					data-field="label"
					aria-label="Label for choice {i + 1}"
					placeholder={labelFallback(c.label, editLang)}
					value={labelText(i)}
					oninput={(e) => (labelDrafts[keys[i]] = { value: e.currentTarget.value, sent: false })}
					onblur={() => commitLabel(i)}
					onkeydown={(e) => onInputKey(e, i, 'label')}
				/>
				<IconButton icon={Copy} label="Duplicate {nameOf(i)}" data-field="duplicate" onclick={() => duplicate(i)} />
				<IconButton
					icon={Trash}
					label="Delete {nameOf(i)}"
					data-field="delete"
					disabled={choices.length <= 1}
					onclick={() => remove(i)}
				/>
				{#if err || rowDiags.length}
					<div class="row-msgs" id={errId}>
						{#if err}<p class="msg" data-severity="error">{err}</p>{/if}
						{#each rowDiags as d, n (n)}
							<p class="msg" data-severity={d.severity}>{d.message}</p>
						{/each}
					</div>
				{/if}
			</li>
		{/each}
	</ol>
	{#if !choices.length}
		<p class="empty">No choices yet.</p>
	{/if}

	<div class="actions">
		<Button size="sm" data-field="add" onclick={add} disabled={!!question.choiceList && !shared}>
			<Plus size={16} aria-hidden="true" /> Add choice
		</Button>
		<Button size="sm" variant="ghost" data-field="paste" aria-expanded={pasting} onclick={() => (pasting = !pasting)}>
			<ClipboardPaste size={16} aria-hidden="true" /> Paste list…
		</Button>
	</div>

	{#if pasting}
		<PastePanel
			{owner}
			existing={choices}
			{publishedVersions}
			{onOps}
			onclose={() => {
				pasting = false;
				void tick().then(() => root?.querySelector<HTMLElement>('[data-field="paste"]')?.focus());
			}}
		/>
	{/if}

	<CodeChangeDialog
		change={confirm}
		{publishedVersions}
		onresolve={resolveConfirm}
	/>
</div>

<style>
	.choice-editor {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		color: var(--color-text);
		font-size: var(--text-sm);
	}
	.head,
	.rows > li {
		display: grid;
		grid-template-columns: 2rem 6rem minmax(0, 1fr) auto auto;
		align-items: center;
		gap: var(--space-2);
	}
	.head {
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
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
		width: 2rem;
		height: var(--control-height);
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
	input {
		min-width: 0;
		height: var(--control-height);
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
	}
	input.code {
		font-family: var(--font-mono, ui-monospace, monospace);
	}
	input[aria-invalid='true'] {
		border-color: var(--color-danger);
		border-width: 2px;
	}
	input::placeholder {
		color: var(--color-text-muted);
		font-style: italic;
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
	.empty {
		margin: 0;
		color: var(--color-text-muted);
	}
	.actions {
		display: flex;
		gap: var(--space-2);
	}
</style>
