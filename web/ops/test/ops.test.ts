/**
 * The basics with the default env (the ported validator) and with NO_VALIDATOR. Parity with
 * Python is parity.test.ts.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { NO_VALIDATOR, applyPatch, applyTransaction, enabled, opIds, run, same, type Json, type JsonObject } from '../src/index.ts';

const BASE = JSON.parse(
	readFileSync(join(import.meta.dirname, '..', '..', '..', 'python', 'osp-ops', 'tests', 'base_survey.json'), 'utf8')
) as JsonObject;

describe('ops', () => {
	it('registers every op of osp-ops', () => {
		expect(opIds()).toHaveLength(46);
		expect(opIds()).toContain('insert_bank_item');
	});

	it('runs an op, never mutates its input, and the inverse restores it', () => {
		const before = structuredClone(BASE);
		const res = run('add_question', BASE, { page: 'p_demo', type: 'single', label: 'Hi' });
		expect(res.ok).toBe(true);
		expect(same(BASE, before)).toBe(true);
		expect(same(applyPatch(BASE, res.patch), res.survey)).toBe(true);
		const undo = run(res.inverse!.op, res.survey, res.inverse!.params);
		expect(undo.ok && same(undo.survey, BASE)).toBe(true);
	});

	it('reports params errors as pydantic does', () => {
		const res = run('add_question', BASE, { page: 3, zz: 1 });
		expect(res.diagnostics.map((d) => [d.code, d.message, d.pointer])).toEqual([
			['op.params', 'Input should be a valid string', '/page'],
			['op.params', 'Extra inputs are not permitted', '/zz']
		]);
		expect(enabled('nope', BASE)).toBe("no op with id 'nope'");
	});

	it('applies transactions all or nothing, with one inverse for undo and redo', () => {
		const draft = { survey: BASE as Json, revision: 4 };
		const ops = [
			{ op: 'add_block', params: { id: 'b_new' } },
			{ op: 'insert_flow_node', params: { node: { type: 'block', block: 'b_new' } } }
		];
		const done = applyTransaction(draft, ops, 4);
		expect(done.status).toBe('ok');
		expect(done.draft.revision).toBe(5);
		const undo = applyTransaction(done.draft, done.inverse, 5);
		expect(undo.status === 'ok' && same(undo.draft.survey, BASE)).toBe(true);
		const redo = applyTransaction(undo.draft, undo.inverse, 6);
		expect(same(redo.draft.survey, done.draft.survey)).toBe(true);

		const bad = applyTransaction(draft, [...ops, { op: 'delete_question', params: { id: 'nope' } }], 4);
		expect([bad.status, bad.failedIndex, bad.draft]).toEqual(['rejected', 2, draft]);
		expect(applyTransaction(draft, ops, 3).status).toBe('conflict');
	});

	it('parses condition text by default; without a parser it takes only the AST', () => {
		const text = run('set_condition', BASE, { target: 'rating', condition: 'age > 3' });
		expect(text.ok).toBe(true);
		expect(run('set_condition', BASE, { target: 'rating', condition: 'age >' }).diagnostics[0]!.code).toBe('op.expr_syntax');
		const bare = { validator: NO_VALIDATOR };
		expect(run('set_condition', BASE, { target: 'rating', condition: 'age > 3' }, bare).diagnostics[0]!.code).toBe('op.expr_syntax');
		const ast = { kind: 'compare', op: '>', left: { kind: 'ref', id: 'age' }, right: { kind: 'int', value: 3 } };
		const viaAst = run('set_condition', BASE, { target: 'rating', condition: ast }, bare);
		expect(viaAst.ok && same(viaAst.survey, text.survey)).toBe(true);
	});
});
