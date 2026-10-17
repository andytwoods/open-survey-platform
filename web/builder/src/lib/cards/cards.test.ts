import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import ChoiceCard from './ChoiceCard.svelte';
import { CARDS, cardFor } from './dispatch';
import MatrixCard from './MatrixCard.svelte';
import NoteCard from './NoteCard.svelte';
import NumberCard from './NumberCard.svelte';
import ScaleCard from './ScaleCard.svelte';
import TextCard from './TextCard.svelte';
import {
	badgesFor,
	choicesFor,
	exprToText,
	pipeSegments,
	resolveFamily,
	rowsFor,
	scaleRange,
	textFor,
	withoutCardData
} from './logic';
import { FAMILIES, type CardQuestion, type ExprNode } from './types';

const ref = (id: string): ExprNode => ({ kind: 'ref', id });
const int = (value: number): ExprNode => ({ kind: 'int', value });
const cmp = (op: string, left: ExprNode, right: ExprNode): ExprNode => ({ kind: 'compare', op, left, right });

describe('dispatcher', () => {
	it('has one card per family', () => {
		expect(Object.keys(CARDS).sort()).toEqual([...FAMILIES].sort());
		expect(cardFor('choice')).toBe(ChoiceCard);
		expect(cardFor('text')).toBe(TextCard);
		expect(cardFor('number')).toBe(NumberCard);
		expect(cardFor('matrix')).toBe(MatrixCard);
		expect(cardFor('scale')).toBe(ScaleCard);
		expect(cardFor('note')).toBe(NoteCard);
		expect(cardFor(null)).toBeNull();
	});

	it('prefers the family prop, then the schema, then the question type', () => {
		const q = { id: 'q1', type: 'single' };
		expect(resolveFamily('scale', { type: 'single', family: 'choice' }, q)).toBe('scale');
		expect(resolveFamily(undefined, { type: 'x', family: 'number' }, q)).toBe('number');
		expect(resolveFamily(undefined, null, q)).toBe('choice');
		expect(resolveFamily(undefined, null, { id: 'd', type: 'date' })).toBe('text');
		expect(resolveFamily(undefined, null, { id: 'd', type: 'decimal' })).toBe('number');
	});

	it('returns null for unknown or hostile input instead of throwing', () => {
		expect(resolveFamily('bogus', { type: 'x', family: 'nope' }, { id: 'q', type: 'ranking' })).toBeNull();
		expect(resolveFamily(undefined, undefined, undefined)).toBeNull();
		expect(resolveFamily(42, null, { id: 'q', type: 'constructor' })).toBeNull();
		expect(resolveFamily(undefined, null, { id: 'q', type: 'toString' })).toBeNull();
	});

	it('covers every question family in the osp-spec property schemas', () => {
		const dir = fileURLToPath(
			new URL('../../../../../python/osp-spec/src/osp_spec/properties/', import.meta.url)
		);
		const families = readdirSync(dir)
			.filter((f) => f.endsWith('.yaml'))
			.map((f) => readFileSync(dir + f, 'utf8'))
			.filter((y) => /^entity: question$/m.test(y))
			.map((y) => /^family: (\S+)$/m.exec(y)?.[1]);
		expect(families.length).toBeGreaterThan(0);
		for (const f of families) expect(cardFor(resolveFamily(f, null, null))).not.toBeNull();
	});
});

describe('badges', () => {
	it('shows nothing for a plain question', () => {
		expect(badgesFor({ id: 'q', type: 'text', label: 'Hi' })).toEqual([]);
	});

	it('shows show-if with its text form, shuffle and validation', () => {
		const q: CardQuestion = {
			id: 'q',
			type: 'single',
			showIf: { kind: 'and', args: [cmp('>=', ref('age'), int(18)), { kind: 'answered', ref: ref('consent') }] },
			choiceOrder: 'shuffle',
			constraint: cmp('!=', ref('q'), { kind: 'text', value: 'x' })
		};
		const badges = badgesFor(q);
		expect(badges.map((b) => b.kind)).toEqual(['showIf', 'shuffle', 'validation']);
		expect(badges[0].detail).toBe('age >= 18 and answered(consent)');
		expect(badges[2].detail).toBe('q != "x"');
	});

	it('counts errors and warnings first, ignoring info', () => {
		const d = (severity: 'error' | 'warning' | 'info') => ({ severity, code: 'c', message: 'm' });
		const badges = badgesFor({ id: 'q', type: 'text' }, null, [d('error'), d('error'), d('warning'), d('info')]);
		expect(badges.map((b) => [b.kind, b.label, b.tone])).toEqual([
			['errors', '2 errors', 'danger'],
			['warnings', '1 warning', 'warning']
		]);
	});

	it('only shows a badge the schema has a property for', () => {
		const q: CardQuestion = { id: 'n', type: 'note', choiceOrder: 'shuffle', showIf: ref('x') };
		const kinds = badgesFor(q, { type: 'note', properties: { label: {}, showIf: {} } }).map((b) => b.kind);
		expect(kinds).toEqual(['showIf']);
	});

	it('survives hostile input', () => {
		expect(badgesFor(null)).toEqual([]);
		expect(badgesFor({ id: 'q', type: 't', showIf: 'nope' as never }, null, 'x' as never)).toEqual([]);
		expect(badgesFor({ id: 'q', type: 't' }, null, [null as never])).toEqual([]);
	});
});

describe('condition text form (matches osp_expr.syntax.to_text)', () => {
	it.each([
		[cmp('==', ref('a'), int(1)), 'a == 1'],
		[{ kind: 'or', args: [{ kind: 'and', args: [ref('a'), ref('b')] }, ref('c')] }, 'a and b or c'],
		[{ kind: 'and', args: [{ kind: 'or', args: [ref('a'), ref('b')] }, ref('c')] }, '(a or b) and c'],
		[{ kind: 'not', arg: { kind: 'or', args: [ref('a'), ref('b')] } }, 'not (a or b)'],
		[
			cmp('>', { kind: 'arith', op: '*', left: { kind: 'arith', op: '+', left: ref('a'), right: int(1) }, right: int(2) }, int(3)),
			'(a + 1) * 2 > 3'
		],
		[{ kind: 'arith', op: '-', left: ref('a'), right: { kind: 'arith', op: '-', left: ref('b'), right: ref('c') } }, 'a - (b - c)'],
		[{ kind: 'contains', ref: ref('fruit'), value: { kind: 'text', value: 'a"b\n' } }, 'contains(fruit, "a\\"b\\n")'],
		[{ kind: 'decimal', value: '3' }, '3.0'],
		[{ kind: 'decimal', value: '2.50' }, '2.50'],
		[{ kind: 'bool', value: false }, 'false'],
		[{ kind: 'null' }, 'null']
	] as [ExprNode, string][])('%#: %s', (expr, text) => {
		expect(exprToText(expr)).toBe(text);
	});

	it('prints ? for nodes it does not know, and stops on runaway depth', () => {
		expect(exprToText({ kind: 'mystery' })).toBe('?');
		expect(exprToText(null)).toBe('?');
		let deep: ExprNode = ref('x');
		for (let i = 0; i < 500; i++) deep = { kind: 'not', arg: deep };
		expect(exprToText(deep)).toContain('?');
	});
});

describe('pipes and text', () => {
	it('splits ${id} pipes into tokens and leaves malformed ones as text', () => {
		expect(pipeSegments('Hi ${name}, age ${age}?')).toEqual([
			{ kind: 'text', text: 'Hi ' },
			{ kind: 'pipe', id: 'name' },
			{ kind: 'text', text: ', age ' },
			{ kind: 'pipe', id: 'age' },
			{ kind: 'text', text: '?' }
		]);
		expect(pipeSegments('${1bad} ${ok')).toEqual([{ kind: 'text', text: '${1bad} ${ok' }]);
		expect(pipeSegments('')).toEqual([]);
	});

	it('picks a language from translatable text', () => {
		expect(textFor('plain')).toBe('plain');
		expect(textFor({ de: 'Hallo', en: 'Hello' }, 'de')).toBe('Hallo');
		expect(textFor({ de: 'Hallo', en: 'Hello' }, 'fr')).toBe('Hello');
		expect(textFor({ nl: 'Hoi' }, 'fr')).toBe('Hoi');
		expect(textFor(null)).toBe('');
		expect(textFor(['x'])).toBe('');
	});

	it('resolves inline or shared choices, string-valued and de-duplicated', () => {
		const lists = [{ id: 'agree5', choices: [{ value: 1, label: { en: 'Disagree' } }, { value: 1, label: 'dup' }] }];
		expect(choicesFor({ id: 'q', type: 'single', choiceList: 'agree5' }, lists)).toEqual({
			choices: [{ value: '1', label: 'Disagree' }],
			sharedList: 'agree5'
		});
		expect(choicesFor({ id: 'q', type: 'single', choiceList: 'missing' }, lists).choices).toEqual([]);
	});

	it('keeps card data off the select button', () => {
		expect(withoutCardData({ choiceLists: [], id: 'card-q1', 'data-pane-focus': '' })).toEqual({
			id: 'card-q1',
			'data-pane-focus': ''
		});
	});

	it('previews matrix rows by row id, dropping rows without an id or repeated', () => {
		const q = {
			id: 'm',
			type: 'matrix',
			rows: [{ id: 'tea', label: { en: 'Tea' } }, { id: 'tea', label: 'dup' }, { label: 'no id' }, null, { id: 'cocoa', label: 'Cocoa', required: false }]
		} as unknown as CardQuestion;
		expect(rowsFor(q)).toEqual([
			{ value: 'tea', label: 'Tea' },
			{ value: 'cocoa', label: 'Cocoa' }
		]);
		expect(rowsFor({ id: 'm', type: 'matrix', rows: null })).toEqual([]);
	});

	it('makes any scale range safe for the slider', () => {
		expect(scaleRange({ id: 's', type: 'slider' })).toEqual({ min: 0, max: 100, step: 1 });
		expect(scaleRange({ id: 's', type: 'slider', min: '0.5', max: '2.5', step: '0.5' })).toEqual({
			min: 0.5,
			max: 2.5,
			step: 0.5
		});
		expect(scaleRange({ id: 's', type: 'slider', min: 'x', max: '', step: '0' })).toEqual({ min: 0, max: 100, step: 1 });
		expect(scaleRange({ id: 's', type: 'slider', min: 5, max: 5, step: -1 })).toEqual({ min: 5, max: 6, step: 1 });
		expect(scaleRange({ id: 's', type: 'slider', min: 1, max: 7, step: 0.5 })).toEqual({ min: 1, max: 7, step: 0.5 });
	});
});
