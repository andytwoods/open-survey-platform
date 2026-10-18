import '@testing-library/svelte/vitest';
import { EditorView } from '@codemirror/view';
import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import ConditionBuilder from './ConditionBuilder.svelte';
import type { ExpressionService } from './service';
import type { ExprNode, QuestionInfo } from './types';

const QUESTIONS: QuestionInfo[] = [{ id: 'age', type: 'integer', label: 'Age', choices: [], required: true, conditional: false }];
const AGE_18: ExprNode = { kind: 'compare', op: '>=', left: { kind: 'ref', id: 'age' }, right: { kind: 'int', value: 18 } };

/** A server that prints every tree as "age >= 18" and accepts any text. */
function service(): ExpressionService & { prints: number } {
	const s = {
		prints: 0,
		print: vi.fn(async () => {
			s.prints += 1;
			return { text: 'age >= 18', diagnostics: [] };
		}),
		parse: vi.fn(async ({ text }: { text: string }) => ({ ok: true, ast: AGE_18, text, diagnostics: [] }))
	};
	return s;
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

describe('ConditionBuilder', () => {
	it('the text view opens on the tree’s text, and a late tree print never replaces what was typed', async () => {
		const svc = service();
		render(ConditionBuilder, { props: { questions: QUESTIONS, value: AGE_18, target: 'q2', service: svc, onOps: vi.fn() } });
		// Straight to Text, before the tree's own (debounced) print has run.
		await fireEvent.click(screen.getByTestId('view-text'));
		const host = await screen.findByTestId('condition-text');
		const view = EditorView.findFromDOM(host.querySelector<HTMLElement>('.cm-editor')!)!;
		expect(view.state.doc.toString()).toBe('age >= 18');
		view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: 'age >= 21' }, userEvent: 'input.type' });
		await wait(400); // past the tree's debounce (200 ms)
		expect(view.state.doc.toString()).toBe('age >= 21');
		expect(svc.parse).toHaveBeenLastCalledWith(expect.objectContaining({ text: 'age >= 21' }));
	});
});
