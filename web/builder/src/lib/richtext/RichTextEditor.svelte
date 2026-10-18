<script lang="ts">
	import { charCount } from '@osp/engine';
	import { announce } from '@osp/ui-components';
	import { getContext, onDestroy, onMount, tick, untrack } from 'svelte';
	import { BUFFERS, type BufferRegistry } from '../properties/context';
	import { TEXT_DEBOUNCE_MS } from '../properties/logic';
	import { fromDoc, isEmptyValue, normalForm, sameValue, toDoc, type PmNode, type RichValue } from './convert';
	import type { Editor, Range, ToolbarState } from './tiptap';
	import { LIMITS, type Level } from './levels';
	import LinkDialog from './LinkDialog.svelte';
	import { describeReport } from './paste';
	import PipePicker from './PipePicker.svelte';
	import type { PipeCandidate } from './pipes';
	import ReferenceStrip from './ReferenceStrip.svelte';
	import RichView from './RichView.svelte';
	import Toolbar, { type ToolbarAction } from './Toolbar.svelte';

	/**
	 * One rich-text field (planning/rich-text.md §9). At rest it is the read-only renderer
	 * styled as an input (`role=textbox`); focusing it (click, Tab, Enter) loads the editor
	 * chunk once and swaps in a Tiptap editor with its toolbar. The buffering contract is
	 * BufferedInput's: typing never round-trips, the value is committed after a pause, on
	 * blur or on Enter (inline fields), Escape reverts the draft, and a server echo never
	 * clobbers text the researcher is still typing. Commits are the normalised value: a plain
	 * string when there is no formatting (RT-D3), else the tree.
	 *
	 * When another language than the default is edited, `reference` (the default-language
	 * value) is shown read-only above the field with *Copy from <default>* (§5, RT6).
	 */
	let {
		id,
		value,
		level,
		pipes = null,
		problems = new Map<string, string>(),
		placeholder = '',
		label,
		reference = null,
		labelledBy,
		describedBy,
		required = false,
		invalid = false,
		readonly = false,
		compact = false,
		lang,
		delay = TEXT_DEBOUNCE_MS,
		onCommit,
		onDirty
	}: {
		id: string;
		/** The field's value in the editing language: plain, rich, or unset. */
		value: RichValue | undefined | null;
		level: Level;
		/** Pipe candidates for the picker; null when the field may not pipe (consent). */
		pipes?: readonly PipeCandidate[] | null;
		/** Server diagnostics by pipe id, shown on the chips. */
		problems?: ReadonlyMap<string, string>;
		placeholder?: string;
		/** The accessible name, when no visible label element names the field (`aria-label`). */
		label?: string;
		/** The default-language value and its tag, when editing a translation; null otherwise. */
		reference?: { value: RichValue | undefined | null; language: string } | null;
		labelledBy?: string;
		describedBy?: string;
		required?: boolean;
		invalid?: boolean;
		readonly?: boolean;
		/** A row in a list (RT5): the count and status show only while editing or over the limit. */
		compact?: boolean;
		lang?: string;
		delay?: number;
		onCommit: (value: RichValue) => void;
		onDirty?: (dirty: boolean) => void;
	} = $props();

	type EditorModule = typeof import('./tiptap');
	let modulePromise: Promise<EditorModule> | null = null;
	const loadEditor = () => (modulePromise ??= import('./tiptap'));

	let root = $state<HTMLDivElement | null>(null);
	let host = $state<HTMLDivElement | null>(null);
	let active = $state(false);
	let activating = false;
	let mod: EditorModule | null = null;
	let editor: Editor | null = null;
	let tb = $state<ToolbarState | null>(null);
	let toolbar = $state<Toolbar | null>(null);

	/** The last value we know the server holds (received, or sent by us). Not reactive. */
	let sent: RichValue = untrack(() => normalForm(value));
	let draft = $state<RichValue>(untrack(() => normalForm(value)));
	let timer: ReturnType<typeof setTimeout> | null = null;
	/** A dialog or menu of ours has focus: do not leave edit mode. */
	let holding = $state(false);
	let status = $state('');
	let pendingStatus = '';
	let point: { x: number; y: number } | null = null;

	let linkOpen = $state(false);
	let link = $state({ href: '', text: '', needsText: false, hasLink: false });
	let pickerOpen = $state(false);
	let pipeRange: Range | null = null;

	const limit = $derived(LIMITS[level]);
	const count = $derived(charCount(draft));
	const over = $derived(count > limit);
	const near = $derived(count >= limit * 0.9);
	const countId = $derived(`${id}-count`);
	const statusId = $derived(`${id}-status`);
	/** Compact fields draw the foot (count, status) only while editing or over the limit. */
	const foot = $derived(!compact || active || over || !!status);
	const describes = $derived(
		[describedBy, foot ? countId : '', foot && status ? statusId : ''].filter(Boolean).join(' ') || undefined
	);
	const empty = $derived(isEmptyValue(draft));
	/** The reference strip shows when there is a default-language value to translate. */
	const ref = $derived(reference && !isEmptyValue(reference.value) ? { value: normalForm(reference.value), language: reference.language } : null);
	const sameAsRef = $derived(ref !== null && sameValue(draft, ref.value));

	const attrs = (): Record<string, string> => {
		const a: Record<string, string> = {
			id,
			class: 'osp-rt-content',
			role: 'textbox',
			'aria-multiline': level === 'inline' ? 'false' : 'true'
		};
		if (describes) a['aria-describedby'] = describes;
		if (label) a['aria-label'] = label;
		if (labelledBy) a['aria-labelledby'] = labelledBy;
		if (placeholder) a['aria-placeholder'] = placeholder;
		if (required) a['aria-required'] = 'true';
		if (invalid || over) a['aria-invalid'] = 'true';
		if (lang) a.lang = lang;
		return a;
	};

	// --- Buffer -----------------------------------------------------------------------------

	$effect.pre(() => {
		const v = normalForm(value);
		untrack(() => receive(v));
	});

	function receive(v: RichValue) {
		if (sameValue(v, draft)) {
			sent = v;
			return;
		}
		// The researcher is mid-edit: their text wins until it is committed.
		if (timer !== null || (active && !sameValue(draft, sent))) return;
		sent = v;
		draft = v;
		if (editor) setEditorContent(v);
	}

	function setEditorContent(v: RichValue) {
		if (!editor) return;
		const { from, to } = editor.state.selection;
		editor.commands.setContent(toDoc(v, level), { emitUpdate: false });
		const size = editor.state.doc.content.size;
		editor.commands.setTextSelection({ from: Math.min(from, size), to: Math.min(to, size) });
	}

	function onUpdate() {
		if (!editor) return;
		draft = normalForm(fromDoc(editor.getJSON() as PmNode));
		status = pendingStatus;
		pendingStatus = '';
		if (timer === null) onDirty?.(true);
		else clearTimeout(timer);
		timer = setTimeout(flush, delay);
	}

	/** Commit the buffer now, if it holds unsent text. */
	export function flush() {
		if (timer !== null) {
			clearTimeout(timer);
			timer = null;
			onDirty?.(false);
		}
		if (sameValue(draft, sent)) return;
		sent = draft;
		onCommit(draft);
	}

	/**
	 * Copy from <default>: the default-language value (formatting, links and chips included)
	 * becomes this language's value, committed at once; the researcher edits from there.
	 */
	function copyFromReference() {
		if (!ref || readonly) return;
		if (timer !== null) {
			clearTimeout(timer);
			timer = null;
			onDirty?.(false);
		}
		draft = ref.value;
		if (editor) setEditorContent(ref.value);
		flush();
		announce(`Copied from ${ref.language}`);
	}

	/** Escape: throw the unsent text away. True when there was something to revert. */
	function revert(): boolean {
		if (sameValue(draft, sent)) return false;
		if (timer !== null) {
			clearTimeout(timer);
			timer = null;
			onDirty?.(false);
		}
		draft = sent;
		setEditorContent(sent);
		announce('Changes discarded');
		return true;
	}

	const registry = getContext<BufferRegistry | undefined>(BUFFERS);
	const handle = { flush };
	onMount(() => {
		registry?.add(handle);
	});
	onDestroy(() => {
		registry?.delete(handle);
		flush();
		destroyEditor();
	});

	/**
	 * Tiptap's destroy() blurs the view, which dispatches one last transaction; our
	 * onTransaction must not touch state then (teardown may run inside Svelte's render).
	 */
	function destroyEditor() {
		const e = editor;
		editor = null;
		e?.destroy();
	}

	// --- Edit on focus ----------------------------------------------------------------------

	async function activate() {
		if (active || activating || readonly) return;
		activating = true;
		try {
			mod = await loadEditor();
			active = true;
			await tick();
			if (!host || !mod) return;
			const m = mod;
			editor = m.createEditor({
				element: host,
				level,
				pipes: pipes !== null,
				content: toDoc(draft, level),
				placeholder,
				attributes: attrs(),
				onUpdate,
				onTransaction: () => {
					if (editor) tb = m.toolbarState(editor);
				},
				keyboard: {
					onToggle: (name, on) => announce(`${name} ${on ? 'on' : 'off'}`),
					onToolbar: () => toolbar?.focus(),
					onEscape: revert,
					onEnter: level === 'inline' ? flush : undefined
				},
				pipeHooks: {
					onTrigger: (range) => openPicker(range),
					onPaste: (report) => {
						const msg = describeReport(report);
						pendingStatus = msg ?? '';
						if (msg) announce(msg);
					}
				}
			});
			m.setPipeProblems(editor, problems);
			tb = m.toolbarState(editor);
			m.placeCaret(editor, point);
			point = null;
		} finally {
			activating = false;
		}
	}

	function deactivate() {
		if (!active) return;
		flush();
		destroyEditor();
		tb = null;
		active = false;
		status = '';
	}

	function onfocusout(e: FocusEvent) {
		if (holding || activating) return;
		const next = e.relatedTarget as Node | null;
		if (next && root?.contains(next)) return;
		setTimeout(() => {
			if (!holding && !activating && root && !root.contains(document.activeElement)) deactivate();
		}, 0);
	}

	function onkeydown(e: KeyboardEvent) {
		// Escape that reverted a draft (the editor prevented it) stays here: it must not
		// also close the drawer or dialog the field sits in (BufferedInput's contract).
		if (e.key === 'Escape' && e.defaultPrevented) e.stopPropagation();
	}

	$effect(() => {
		if (!linkOpen && !pickerOpen) holding = false;
	});
	$effect(() => {
		const a = attrs();
		if (editor && mod) mod.setAttributes(editor, a);
	});
	$effect(() => {
		const p = problems;
		if (editor && mod) mod.setPipeProblems(editor, p);
	});

	// --- Toolbar, link dialog, pipe picker ----------------------------------------------------

	function act(a: ToolbarAction) {
		if (!editor || !mod) return;
		const m = mod;
		switch (a.kind) {
			case 'bold':
			case 'italic':
				m.toggleMark(editor, a.kind);
				announce(`${a.kind === 'bold' ? 'Bold' : 'Italic'} ${editor.isActive(a.kind) ? 'on' : 'off'}`);
				break;
			case 'link':
				openLink();
				break;
			case 'bulletList':
			case 'orderedList':
				m.toggleList(editor, a.kind);
				break;
			case 'heading':
				m.setHeading(editor, a.level);
				break;
			case 'break':
				m.insertBreak(editor);
				break;
			case 'pipe':
				openPicker(null);
				break;
			case 'clear':
				m.clearFormatting(editor);
				announce('Formatting cleared');
				break;
			case 'undo':
				m.undo(editor);
				break;
			case 'redo':
				m.redo(editor);
				break;
		}
	}

	function openLink() {
		if (!editor || !mod) return;
		const cur = mod.currentLink(editor);
		link = { href: cur.href, text: cur.text, needsText: editor.state.selection.empty && !cur.href, hasLink: !!cur.href };
		holding = true;
		linkOpen = true;
	}

	function openPicker(range: Range | null) {
		if (!pipes) return;
		pipeRange = range;
		holding = true;
		pickerOpen = true;
	}

	function pick(pipeId: string) {
		if (editor && mod) {
			mod.insertPipe(editor, pipeId, pipeRange);
			announce(`Inserted answer ${pipeId}`);
		}
		pipeRange = null;
	}

	const focusEditor = () => editor?.commands.focus();
</script>

<!-- svelte-ignore a11y_no_static_element_interactions (a wrapper: keydown only keeps a handled Escape from closing the drawer) -->
<div
	bind:this={root}
	class="osp-rt"
	data-level={level}
	data-active={active || undefined}
	data-over={over || undefined}
	{onfocusout}
	{onkeydown}
>
	{#if ref && !readonly}
		<ReferenceStrip {id} value={ref.value} language={ref.language} inline={level === 'inline'} same={sameAsRef} onCopy={copyFromReference} />
	{/if}
	<div class="osp-rt-box" class:invalid={invalid || over}>
		{#if active}
			{#if tb}
				<!-- Named without the field's label: a name containing it would also match label lookups for the field. -->
				<Toolbar bind:this={toolbar} {level} state={tb} pipes={pipes !== null} label="Text formatting" onAction={act} onEscape={focusEditor} />
			{/if}
			<div bind:this={host} class="osp-rt-host"></div>
		{:else}
			<div
				{id}
				class="osp-rt-idle"
				class:empty
				role="textbox"
				tabindex={readonly ? -1 : 0}
				aria-multiline={level !== 'inline'}
				aria-label={label}
				aria-labelledby={labelledBy}
				aria-describedby={describes}
				aria-placeholder={placeholder || undefined}
				aria-required={required || undefined}
				aria-invalid={invalid || over || undefined}
				aria-readonly={readonly || undefined}
				{lang}
				onfocus={() => void activate()}
				onmousedown={(e) => (point = { x: e.clientX, y: e.clientY })}
			>
				{#if empty}<span class="osp-rt-placeholder">{placeholder}</span>{:else}<RichView value={draft} inline={level === 'inline'} />{/if}
			</div>
		{/if}
	</div>
	{#if foot}
		<div class="osp-rt-foot">
			{#if status}<p class="osp-rt-status" id={statusId}>{status}</p>{/if}
			<p class="osp-rt-count" id={countId} aria-live={near ? 'polite' : 'off'} data-over={over || undefined}>
				<span class="osp-visually-hidden">Length:</span>
				{count.toLocaleString()} / {limit.toLocaleString()}{#if over}<span class="osp-rt-too-long"> – too long</span>{/if}
			</p>
		</div>
	{/if}
</div>

{#if pipes}
	<PipePicker bind:open={pickerOpen} candidates={pipes} onPick={pick} onClose={() => (pipeRange = null)} />
{/if}
<LinkDialog
	bind:open={linkOpen}
	href={link.href}
	text={link.text}
	needsText={link.needsText}
	hasLink={link.hasLink}
	onApply={(href, text) => {
		if (editor && mod) mod.applyLink(editor, href, text);
		announce(link.hasLink ? 'Link changed' : 'Link added');
	}}
	onRemove={() => {
		if (editor && mod) mod.removeLink(editor);
		announce('Link removed');
	}}
/>

<style>
	.osp-rt {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}
	.osp-rt-box {
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font-size: var(--text-sm);
		line-height: 1.4;
	}
	.osp-rt-box.invalid {
		border-color: var(--color-danger);
	}
	.osp-rt-box:focus-within {
		outline: 2px solid var(--color-focus, var(--color-accent));
		outline-offset: 1px;
	}
	.osp-rt-idle,
	.osp-rt-host :global(.osp-rt-content) {
		box-sizing: border-box;
		width: 100%;
		padding: var(--space-2) var(--space-3);
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		outline: none;
	}
	.osp-rt-idle {
		cursor: text;
	}
	/* A list of rows may ask for taller lines (`--osp-rt-height`: 44 px targets). */
	.osp-rt[data-level='inline'] .osp-rt-idle,
	.osp-rt[data-level='inline'] .osp-rt-host :global(.osp-rt-content) {
		min-height: var(--osp-rt-height, var(--control-height));
		padding-block: calc((var(--osp-rt-height, var(--control-height)) - 1.4em) / 2);
	}
	.osp-rt[data-level='stem'] .osp-rt-idle,
	.osp-rt[data-level='stem'] .osp-rt-host :global(.osp-rt-content) {
		min-height: 4.5rem;
	}
	.osp-rt[data-level='block'] .osp-rt-idle,
	.osp-rt[data-level='block'] .osp-rt-host :global(.osp-rt-content) {
		min-height: 7rem;
	}
	.osp-rt-placeholder,
	.osp-rt-host :global(.osp-rt-content .is-editor-empty:first-child::before) {
		color: var(--color-text-muted);
		pointer-events: none;
	}
	.osp-rt-host :global(.osp-rt-content .is-editor-empty:first-child::before) {
		content: attr(data-placeholder);
		float: left;
		height: 0;
	}
	.osp-rt-host :global(.osp-rt-content p),
	.osp-rt-host :global(.osp-rt-content h1),
	.osp-rt-host :global(.osp-rt-content h2),
	.osp-rt-host :global(.osp-rt-content h3),
	.osp-rt-host :global(.osp-rt-content ul),
	.osp-rt-host :global(.osp-rt-content ol) {
		margin: 0;
	}
	.osp-rt-host :global(.osp-rt-content > * + *) {
		margin-block-start: var(--space-2);
	}
	.osp-rt-host :global(.osp-rt-content h1),
	.osp-rt-host :global(.osp-rt-content h2),
	.osp-rt-host :global(.osp-rt-content h3) {
		font-weight: var(--weight-bold);
		line-height: var(--leading-tight);
	}
	.osp-rt-host :global(.osp-rt-content h1) {
		font-size: 1.25em;
	}
	.osp-rt-host :global(.osp-rt-content h2) {
		font-size: 1.1em;
	}
	.osp-rt-host :global(.osp-rt-content h3) {
		font-size: 1em;
	}
	.osp-rt-host :global(.osp-rt-content ul),
	.osp-rt-host :global(.osp-rt-content ol) {
		padding-inline-start: 1.5em;
	}
	.osp-rt-host :global(.osp-rt-content li > p) {
		margin: 0;
	}
	.osp-rt-host :global(.osp-rt-content .ProseMirror-selectednode) {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}
	.osp-rt-foot {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		gap: var(--space-1) var(--space-3);
	}
	.osp-rt-status,
	.osp-rt-count {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.osp-rt-count {
		margin-inline-start: auto;
		font-variant-numeric: tabular-nums;
	}
	.osp-rt-count[data-over] {
		color: var(--color-danger);
		font-weight: var(--weight-medium);
	}
</style>
