/**
 * CodeMirror 6 (MIT) setup for the condition text view: a small stream highlighter for the
 * osp-expr text syntax and server diagnostics → lint underlines. Parsing is the server's.
 */
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
import { StreamLanguage, syntaxHighlighting } from '@codemirror/language';
import { setDiagnostics, type Diagnostic } from '@codemirror/lint';
import { EditorState, type Extension } from '@codemirror/state';
import { EditorView, keymap, placeholder } from '@codemirror/view';
import { classHighlighter } from '@lezer/highlight';
import type { ExprDiagnostic } from './types';

const KEYWORDS = new Set(['and', 'or', 'not']);
const ATOMS = new Set(['null', 'true', 'false']);
const FUNCTIONS = new Set(['answered', 'contains', 'if']);

export const exprLanguage = StreamLanguage.define<null>({
	name: 'osp-expr',
	startState: () => null,
	token(stream) {
		if (stream.eatSpace()) return null;
		if (stream.match(/^"(?:[^"\\]|\\.)*"?/)) return 'string';
		if (stream.match(/^\d+(?:\.\d+)?/)) return 'number';
		const word = stream.match(/^[A-Za-z_$][A-Za-z0-9_.]*/) as RegExpMatchArray | null;
		if (word) {
			const w = word[0];
			if (KEYWORDS.has(w) || FUNCTIONS.has(w)) return 'keyword';
			if (ATOMS.has(w)) return 'atom';
			return 'variableName';
		}
		if (stream.match(/^(?:==|!=|<=|>=|[<>+\-*/])/)) return 'operator';
		stream.next();
		return null;
	}
});

/** Code-point offset (Python `str` index) → UTF-16 offset (CodeMirror position). */
export function utf16Offset(text: string, codePoints: number): number {
	let cp = 0;
	let i = 0;
	while (i < text.length && cp < codePoints) {
		const c = text.codePointAt(i) as number;
		i += c > 0xffff ? 2 : 1;
		cp += 1;
	}
	return i;
}

/** Server diagnostics with positions → CodeMirror diagnostics (never zero-length). */
export function toCmDiagnostics(text: string, diags: readonly ExprDiagnostic[]): Diagnostic[] {
	const len = text.length;
	return diags
		.filter((d) => typeof d.start === 'number')
		.map((d) => {
			let from = Math.min(utf16Offset(text, d.start as number), len);
			let to = Math.min(utf16Offset(text, (d.end ?? d.start) as number), len);
			if (to <= from) {
				if (from < len) to = from + 1;
				else if (len > 0) from = len - 1;
				to = Math.max(to, from);
			}
			return {
				from,
				to,
				severity: d.severity === 'warning' ? 'warning' : d.severity === 'info' ? 'info' : 'error',
				message: d.message
			} satisfies Diagnostic;
		});
}

export interface EditorOptions {
	doc: string;
	label: string;
	describedBy?: string;
	onChange: (text: string) => void;
}

export function editorExtensions(opts: EditorOptions): Extension[] {
	return [
		history(),
		keymap.of([...defaultKeymap, ...historyKeymap]),
		exprLanguage,
		syntaxHighlighting(classHighlighter),
		placeholder('e.g. age >= 18 and answered(q3)'),
		EditorView.lineWrapping,
		EditorView.contentAttributes.of({
			'aria-label': opts.label,
			'aria-multiline': 'true',
			role: 'textbox',
			spellcheck: 'false',
			...(opts.describedBy ? { 'aria-describedby': opts.describedBy } : {})
		}),
		EditorView.updateListener.of((u) => {
			if (u.docChanged) opts.onChange(u.state.doc.toString());
		})
	];
}

export function createEditor(parent: HTMLElement, opts: EditorOptions): EditorView {
	return new EditorView({
		parent,
		state: EditorState.create({ doc: opts.doc, extensions: editorExtensions(opts) })
	});
}

export function showDiagnostics(view: EditorView, diags: readonly ExprDiagnostic[]): void {
	view.dispatch(setDiagnostics(view.state, toCmDiagnostics(view.state.doc.toString(), diags)));
}
