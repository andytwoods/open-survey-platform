import { describe, expect, it } from 'vitest';
import survey from '../../dev/conditions/sample-survey.json';
import { localExpressionService } from './service';
import type { ExprNode } from './types';

// The in-browser answers of /api/meta/expressions/{parse,print} (osp_api/routes/expressions.py),
// on the /dev/conditions sample survey (q_target comes after age, colours, q3; `later` after it).
const service = localExpressionService(() => survey);

describe('localExpressionService', () => {
	it('parses text to the AST and its canonical text', async () => {
		const r = await service.parse({ text: '(age >= 18)  and contains(colours, "red")', target: 'q_target' });
		expect(r.ok).toBe(true);
		expect(r.text).toBe('age >= 18 and contains(colours, "red")');
		expect(r.ast).toEqual({
			kind: 'and',
			args: [
				{ kind: 'compare', op: '>=', left: { kind: 'ref', id: 'age' }, right: { kind: 'int', value: 18 } },
				{ kind: 'contains', ref: { kind: 'ref', id: 'colours' }, value: { kind: 'text', value: 'red' } }
			]
		});
		expect(r.diagnostics).toEqual([]);
	});

	it('a syntax error has code-point offsets and no AST', async () => {
		const r = await service.parse({ text: 'age >=', target: 'q_target' });
		expect(r).toMatchObject({ ok: false, ast: null, text: null });
		expect(r.diagnostics[0]).toMatchObject({ severity: 'error', start: expect.any(Number) });
	});

	it('checks in place: unknown and later questions come back with their ids and paths', async () => {
		const unknown = await service.parse({ text: 'nope == 1', target: 'q_target' });
		expect(unknown.ok).toBe(true);
		expect(unknown.diagnostics).toContainEqual(expect.objectContaining({ code: 'ref.unknown', questionId: 'nope', path: expect.any(String) }));
		const later = await service.parse({ text: 'later > 1', target: 'q_target' });
		expect(later.diagnostics.map((d) => d.code)).toContain('ref.forward');
		expect(later.diagnostics.find((d) => d.code === 'ref.forward')?.questionId).toBe('later');
	});

	it('a target the op refuses gives its diagnostics; no survey, no check', async () => {
		const r = await service.parse({ text: 'age > 1', target: 'no_such' });
		expect(r.diagnostics[0]).toMatchObject({ code: 'op.not_found' });
		const plain = await localExpressionService(() => null).parse({ text: 'nope > 1', target: 'q_target' });
		expect(plain).toMatchObject({ ok: true, diagnostics: [] });
	});

	it('the check sees the draft as it is now', async () => {
		let doc: unknown = survey;
		const live = localExpressionService(() => doc);
		expect((await live.parse({ text: 'age > 1', target: 'q_target' })).diagnostics).toEqual([]);
		doc = { ...survey, blocks: [] };
		expect((await live.parse({ text: 'age > 1', target: 'q_target' })).diagnostics.length).toBeGreaterThan(0);
	});

	it('prints an AST, and refuses what is not one', async () => {
		const ast = { kind: 'not', arg: { kind: 'answered', ref: { kind: 'ref', id: 'q3' } } } as unknown as ExprNode;
		expect(await service.print(ast)).toEqual({ text: 'not answered(q3)', diagnostics: [] });
		const bad = await service.print({ kind: 'nope' } as unknown as ExprNode);
		expect(bad.text).toBeNull();
		expect(bad.diagnostics[0]).toMatchObject({ code: 'invalid-ast' });
		expect((await service.print({ kind: 'compare', op: '>' } as unknown as ExprNode)).diagnostics[0]?.code).toBe('invalid-ast');
	});
});
