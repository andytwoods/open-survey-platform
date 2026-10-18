<script lang="ts">
	import { json } from '@codemirror/lang-json';
	import { bracketMatching, defaultHighlightStyle, foldGutter, syntaxHighlighting } from '@codemirror/language';
	import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
	import { forceLinting, linter, lintGutter, type Diagnostic as CmDiagnostic } from '@codemirror/lint';
	import { EditorState } from '@codemirror/state';
	import { EditorView, highlightActiveLine, keymap, lineNumbers } from '@codemirror/view';
	import { Button, announce } from '@osp/ui-components';
	import { onDestroy, onMount } from 'svelte';
	import type { JsonDraft, PlacedDiagnostic } from './json-draft.svelte';
	import { parseJson } from './source';

	/**
	 * The JSON view (builder-design §4, task B9): the survey JSON in CodeMirror 6. Edits stay
	 * local until Apply (one `replace_survey`); Revert discards them. Syntax errors are marked
	 * as you type; a rejected Apply's diagnostics are marked at their JSON pointers.
	 */
	let { draft }: { draft: JsonDraft } = $props();

	let host: HTMLDivElement;
	let view: EditorView | null = null;

	// Follow the server while there are no local edits.
	$effect(() => {
		draft.sync();
	});

	const severity = (s: string): CmDiagnostic['severity'] =>
		s === 'error' ? 'error' : s === 'warning' ? 'warning' : 'info';

	function lint(v: EditorView): CmDiagnostic[] {
		const text = v.state.doc.toString();
		const parsed = parseJson(text);
		if (!parsed.ok) {
			const from = Math.min(parsed.offset, text.length);
			return [{ from, to: Math.min(from + 1, text.length), severity: 'error', message: parsed.message }];
		}
		return draft.current
			.filter((d) => d.span)
			.map((d) => ({
				from: d.span!.from,
				to: d.span!.to,
				severity: severity(d.severity),
				source: d.code,
				message: d.pointer ? `${d.message} (${d.pointer})` : d.message
			}));
	}

	onMount(() => {
		view = new EditorView({
			parent: host,
			state: EditorState.create({
				doc: draft.text,
				extensions: [
					lineNumbers(),
					foldGutter(),
					history(),
					bracketMatching(),
					highlightActiveLine(),
					syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
					keymap.of([...defaultKeymap, ...historyKeymap]),
					json(),
					linter(lint, { delay: 300 }),
					lintGutter(),
					EditorView.lineWrapping,
					EditorView.contentAttributes.of({
						'aria-label': 'Survey JSON',
						'aria-describedby': 'json-view-help'
					}),
					EditorView.updateListener.of((u) => {
						if (u.docChanged) draft.edit(u.state.doc.toString());
					})
				]
			})
		});
	});

	onDestroy(() => view?.destroy());

	// Text replaced from outside (revert, sync, applied): put it in the editor.
	$effect(() => {
		const text = draft.text;
		if (view && view.state.doc.toString() !== text) {
			view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } });
		}
	});

	// Re-mark when a rejection's diagnostics arrive.
	$effect(() => {
		void draft.rejected;
		if (view) forceLinting(view);
	});

	function goTo(d: { from: number; to?: number }) {
		if (!view) return;
		const from = Math.min(d.from, view.state.doc.length);
		view.dispatch({ selection: { anchor: from }, scrollIntoView: true });
		view.focus();
	}

	async function apply(force = false) {
		const r = await draft.apply({ force });
		announce(draft.message, r === 'applied' ? 'polite' : 'assertive');
		if (r === 'invalid' && draft.syntaxError) goTo({ from: draft.syntaxError.offset });
		if (view) forceLinting(view);
	}

	function revert() {
		draft.revert();
		announce(draft.message);
	}

	const where = (d: PlacedDiagnostic) => (d.position ? `Line ${d.position.line}, column ${d.position.col}` : 'Survey');
</script>

<section class="json-view" aria-labelledby="json-view-heading">
	<div class="bar">
		<h2 id="json-view-heading">Survey JSON</h2>
		<span class="state" data-testid="json-state">
			{#if draft.applying}Applying…{:else if draft.dirty}Unapplied edits{:else}Revision {draft.serverRevision}{/if}
		</span>
		<div class="actions">
			<Button onclick={revert} disabled={!draft.dirty || draft.applying}>Revert</Button>
			<Button variant="primary" onclick={() => void apply()} disabled={!draft.dirty || draft.applying}>Apply</Button>
		</div>
	</div>
	<p id="json-view-help" class="help">
		Edits stay here until you press Apply, which replaces the survey in one undoable step.
		Invalid JSON is never sent.
	</p>

	{#if draft.stale}
		<div class="notice warning" role="alert" data-testid="json-stale">
			<p>
				This survey changed on the server while you were editing (you started from revision
				{draft.baseRevision}; it is now at {draft.serverRevision}). Applying replaces those changes.
			</p>
			<div class="notice-actions">
				<Button onclick={revert}>Discard my edits and show the latest</Button>
				<Button variant="danger" onclick={() => void apply(true)}>Apply anyway</Button>
			</div>
		</div>
	{/if}

	<p class="message" role="status" data-testid="json-message">{draft.message}</p>

	{#if draft.syntaxError}
		<div class="notice error" data-testid="json-syntax-error">
			<p>
				<strong>Invalid JSON</strong> at
				<button type="button" class="link" onclick={() => goTo({ from: draft.syntaxError!.offset })}
					>line {draft.syntaxError.position.line}, column {draft.syntaxError.position.col}</button
				>: {draft.syntaxError.message}
			</p>
		</div>
	{/if}

	{#if draft.current.length}
		<div class="notice error" data-testid="json-diagnostics">
			<h3>The server did not apply this survey</h3>
			<ul>
				{#each draft.current as d, i (i)}
					<li data-severity={d.severity}>
						{#if d.span}
							<button type="button" class="link" onclick={() => goTo(d.span!)}>{where(d)}</button>
						{:else}
							<span>{where(d)}</span>
						{/if}
						<code>{d.pointer || '/'}</code>
						<span>{d.message}</span>
					</li>
				{/each}
			</ul>
		</div>
	{/if}

	<div class="editor" bind:this={host} data-testid="json-editor"></div>
</section>

<style>
	.json-view {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		max-width: 60rem;
		margin: 0 auto;
		padding: var(--space-3) var(--space-5) var(--space-6);
	}
	.bar {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		flex-wrap: wrap;
	}
	h2 {
		margin: 0;
		font-size: var(--text-md);
	}
	h3 {
		margin: 0 0 var(--space-1);
		font-size: var(--text-sm);
	}
	.state {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.actions {
		display: flex;
		gap: var(--space-2);
		margin-inline-start: auto;
	}
	.help,
	.message {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.message:empty {
		display: none;
	}
	.notice {
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-border);
		border-inline-start-width: 4px;
		border-radius: var(--radius-md);
		background: var(--color-surface);
		font-size: var(--text-sm);
	}
	.notice p {
		margin: 0;
	}
	.notice.warning {
		border-inline-start-color: var(--color-warning);
	}
	.notice.error {
		border-inline-start-color: var(--color-danger);
	}
	.notice-actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin-top: var(--space-2);
	}
	.notice ul {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.notice li {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		align-items: baseline;
	}
	code {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		overflow-wrap: anywhere;
	}
	.link {
		padding: 0;
		border: 0;
		background: none;
		color: var(--color-accent);
		font: inherit;
		text-decoration: underline;
		cursor: pointer;
	}
	.editor {
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		overflow: hidden;
	}
	.editor :global(.cm-editor) {
		/* No max-height: the pane scrolls, not the editor (a scrollable region inside it
		   would need its own tab stop). Lines wrap, so there is no sideways scroll either. */
		min-height: 20rem;
		font-size: var(--text-sm);
	}
	.editor :global(.cm-editor.cm-focused) {
		outline: 2px solid var(--color-focus);
		outline-offset: -2px;
	}
	.editor :global(.cm-scroller) {
		font-family: var(--font-mono);
	}
	.editor :global(.cm-gutters) {
		background: var(--color-surface);
		color: var(--color-text-muted);
		border-inline-end: 1px solid var(--color-border);
	}
	.editor :global(.cm-content) {
		color: var(--color-text);
		caret-color: var(--color-text);
	}
	.editor :global(.cm-activeLine) {
		background: color-mix(in srgb, var(--color-accent) 6%, transparent);
	}
	.editor :global(.cm-activeLineGutter) {
		background: color-mix(in srgb, var(--color-accent) 10%, transparent);
	}
</style>
