<script lang="ts">
	import type { Extension } from '@codemirror/state';
	import type { EditorView } from '@codemirror/view';
	import { onMount } from 'svelte';
	import { createEditor, showDiagnostics } from './codemirror';
	import type { ExprDiagnostic } from './types';

	/**
	 * CodeMirror text view of a condition. `value` changes from outside replace the text;
	 * typing calls `onchange`. `diagnostics` (with character positions) are underlined.
	 */
	let {
		value,
		label,
		describedBy,
		diagnostics = [],
		onchange,
		language,
		placeholder,
		testid = 'condition-text'
	}: {
		value: string;
		label: string;
		describedBy?: string;
		diagnostics?: readonly ExprDiagnostic[];
		onchange: (text: string) => void;
		/** Another language than the condition syntax (e.g. JavaScript for researcher hooks). */
		language?: Extension;
		placeholder?: string;
		testid?: string;
	} = $props();

	let host: HTMLDivElement;
	let view = $state<EditorView | null>(null);
	let external = false;

	onMount(() => {
		const v = createEditor(host, {
			doc: value,
			label,
			describedBy,
			language,
			placeholder,
			onChange: (text) => {
				if (!external) onchange(text);
			}
		});
		view = v;
		return () => v.destroy();
	});

	$effect(() => {
		const v = value;
		if (!view || v === view.state.doc.toString()) return;
		external = true;
		view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: v } });
		external = false;
	});

	$effect(() => {
		const d = diagnostics;
		if (view) showDiagnostics(view, d);
	});
</script>

<div class="editor" bind:this={host} data-testid={testid}></div>

<style>
	.editor {
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: var(--color-text);
		font-family: var(--font-mono);
		font-size: var(--text-sm);
	}
	.editor:focus-within {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 1px;
	}
	.editor :global(.cm-editor) {
		min-height: 5rem;
		background: transparent;
	}
	.editor :global(.cm-editor.cm-focused) {
		outline: none;
	}
	.editor :global(.cm-content) {
		padding: var(--space-2);
		caret-color: var(--color-text);
		font-family: var(--font-mono);
	}
	.editor :global(.cm-placeholder) {
		color: var(--color-text-muted);
	}
	.editor :global(.cm-selectionBackground),
	.editor :global(.cm-focused .cm-selectionBackground) {
		background: var(--color-accent-subtle) !important;
	}
	.editor :global(.tok-keyword) {
		color: var(--color-accent);
		font-weight: var(--weight-medium);
	}
	.editor :global(.tok-string) {
		color: var(--color-success);
	}
	.editor :global(.tok-number),
	.editor :global(.tok-atom) {
		color: var(--color-warning);
	}
	.editor :global(.cm-lintRange-error) {
		background-image: none;
		text-decoration: underline wavy var(--color-danger);
		text-decoration-skip-ink: none;
	}
	.editor :global(.cm-lintRange-warning) {
		background-image: none;
		text-decoration: underline wavy var(--color-warning);
	}
	.editor :global(.cm-tooltip) {
		border: 1px solid var(--color-border);
		background: var(--color-surface-raised);
		color: var(--color-text);
	}
</style>
