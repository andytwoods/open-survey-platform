import { describe, expect, it } from 'vitest';
import { toCmDiagnostics, utf16Offset } from './codemirror';
import { operatorsForRow, operatorsForType } from './operators';
import { questionsFromSurvey } from './questions';
import { astToTree, choiceLiteral, newGroup, newRow, numberLiteral, rowProblem, treeToAst } from './tree';
import type { CondNode, ExprNode, GroupNode, QuestionInfo } from './types';
import { requireAnswered, treeWarnings } from './warnings';

const ref = (id: string) => ({ kind: 'ref', id });
const int = (value: number) => ({ kind: 'int', value });
const text = (value: string) => ({ kind: 'text', value });
const cmp = (op: string, id: string, right: ExprNode) => ({ kind: 'compare', op, left: ref(id), right });
const contains = (id: string, value: ExprNode) => ({ kind: 'contains', ref: ref(id), value });
const answered = (id: string) => ({ kind: 'answered', ref: ref(id) });
const not = (arg: ExprNode) => ({ kind: 'not', arg });
const and = (...args: ExprNode[]) => ({ kind: 'and', args });
const or = (...args: ExprNode[]) => ({ kind: 'or', args });

const Q = (id: string, type: string, extra: Partial<QuestionInfo> = {}): QuestionInfo => ({
	id,
	type,
	label: id,
	choices: [],
	required: false,
	conditional: false,
	...extra
});
const QUESTIONS = [
	Q('age', 'integer', { required: true }),
	Q('colours', 'multi', { choices: [{ value: 'red', label: 'Red' }] }),
	Q('q3', 'text'),
	Q('pet', 'single', { choices: [{ value: 1, label: 'Yes' }] }),
	Q('start', 'date'),
	Q('stop', 'date')
];
const QMAP = new Map(QUESTIONS.map((q) => [q.id, q]));

/** The example from the task: `(age >= 18 and contains(colours, "red")) or not answered(q3)`. */
const EXAMPLE = or(and(cmp('>=', 'age', int(18)), contains('colours', text('red'))), not(answered('q3')));

const REPRESENTABLE: [string, ExprNode][] = [
	['example', EXAMPLE],
	['single row', cmp('==', 'pet', int(1))],
	['every compare op', and(...['==', '!=', '<', '<=', '>', '>='].map((op) => cmp(op, 'age', int(3))))],
	['decimal and negative literals', or(cmp('<', 'age', { kind: 'decimal', value: '2.50' }), cmp('>', 'age', int(-4)))],
	['text literal', cmp('==', 'q3', text('yes "quoted"'))],
	['question on the right (dates)', cmp('<', 'start', ref('stop'))],
	['includes / excludes', and(contains('colours', text('red')), not(contains('colours', int(2))))],
	['answered / not answered', or(answered('q3'), not(answered('age')))],
	['none of (not or)', not(or(cmp('==', 'pet', int(1)), answered('q3')))],
	['none of one row (not compare)', not(cmp('>', 'age', int(5)))],
	['not and', not(and(answered('age'), answered('q3')))],
	['double negation', not(not(answered('q3')))],
	['nested same-kind groups', and(and(answered('age'), answered('q3')), answered('pet'))],
	['deep nesting', or(and(or(answered('age'), and(answered('q3'), not(or(answered('pet'), answered('start'))))), answered('stop')), answered('colours'))],
	['deleted question', and(cmp('>=', 'age', int(18)), cmp('==', 'gone', int(1)))]
];

const NOT_REPRESENTABLE: [string, ExprNode][] = [
	['arithmetic', cmp('>', 'age', { kind: 'arith', op: '+', left: ref('age'), right: int(1) })],
	['literal on the left', { kind: 'compare', op: '<', left: int(18), right: ref('age') }],
	['bool literal', { kind: 'bool', value: true }],
	['if()', { kind: 'if', cond: answered('q3'), then: int(1), else: int(2) }],
	['null comparison', cmp('==', 'age', { kind: 'null' })],
	['bare reference', ref('age')],
	['unknown kind inside a group', and(answered('age'), { kind: 'mystery' })],
	['malformed and', { kind: 'and', args: [answered('age')] }]
];

describe('AST ⇄ tree', () => {
	it.each(REPRESENTABLE)('%s: AST → tree → AST is exact', (_name, ast) => {
		const tree = astToTree(ast);
		expect(tree.ok).toBe(true);
		if (!tree.ok) return;
		const back = treeToAst(tree.root, QMAP);
		expect(back.incomplete).toEqual([]);
		expect(back.ast).toEqual(ast);
	});

	it.each(REPRESENTABLE)('%s: tree → AST → tree is stable', (_name, ast) => {
		const first = astToTree(ast);
		if (!first.ok) throw new Error('not representable');
		const again = astToTree(treeToAst(first.root, QMAP).ast);
		if (!again.ok) throw new Error('not representable');
		expect(shape(again.root)).toEqual(shape(first.root));
	});

	it.each(NOT_REPRESENTABLE)('%s falls back to text', (_name, ast) => {
		const tree = astToTree(ast);
		expect(tree.ok).toBe(false);
	});

	it('maps the example to Any of [All of [age ≥ 18, colours includes red], q3 not answered]', () => {
		const tree = astToTree(EXAMPLE);
		if (!tree.ok) throw new Error('not representable');
		expect(shape(tree.root)).toEqual({
			any: [{ all: ['age ge 18', 'colours contains red'] }, 'q3 not_answered']
		});
	});

	it('no condition is an empty All of group, and an empty tree compiles to null', () => {
		const tree = astToTree(null);
		expect(tree.ok && tree.root.children).toEqual([]);
		expect(treeToAst(newGroup('all')).ast).toBeNull();
		expect(treeToAst(newGroup('any', [newGroup('all')])).ast).toBeNull();
	});

	it('leaves out and reports incomplete rows; collapses one-child groups', () => {
		const done = newRow('age', 'ge', int(18));
		const blank = newRow();
		const noValue = newRow('age', 'gt');
		const out = treeToAst(newGroup('any', [newGroup('all', [done, blank]), noValue]), QMAP);
		expect(out.ast).toEqual(cmp('>=', 'age', int(18)));
		expect(out.incomplete).toEqual([blank.key, noValue.key]);
		expect(rowProblem(blank, undefined)).toBe('Choose a question');
		expect(rowProblem(noValue, QMAP.get('age'))).toBe('Enter a value');
		expect(rowProblem(newRow('q3', 'answered'), QMAP.get('q3'))).toBeNull();
	});

	it('None of compiles to not / not-or', () => {
		expect(treeToAst(newGroup('none', [newRow('q3', 'answered')])).ast).toEqual(not(answered('q3')));
		expect(treeToAst(newGroup('none', [newRow('q3', 'answered'), newRow('age', 'answered')])).ast).toEqual(
			not(or(answered('q3'), answered('age')))
		);
	});
});

describe('operators by question type', () => {
	const ids = (type: string) => operatorsForType(type).map((o) => o.id);
	const labels = (type: string) => operatorsForType(type).map((o) => o.label);

	it('number: = ≠ < ≤ > ≥ and answered', () => {
		for (const t of ['integer', 'decimal']) {
			expect(ids(t)).toEqual(['eq', 'ne', 'lt', 'le', 'gt', 'ge', 'answered', 'not_answered']);
			expect(labels(t).slice(0, 6).map((l) => l.slice(-2, -1))).toEqual(['=', '≠', '<', '≤', '>', '≥']);
			expect(operatorsForType(t).filter((o) => o.value !== 'none').every((o) => o.value === 'number')).toBe(true);
		}
	});

	it('single choice: is / is not with a choice picker', () => {
		expect(labels('single')).toEqual(['is', 'is not', 'is answered', 'is not answered']);
		expect(operatorsForType('single')[0].value).toBe('choice');
	});

	it('multi choice: includes / excludes with a choice picker', () => {
		expect(ids('multi')).toEqual(['contains', 'not_contains', 'answered', 'not_answered']);
		expect(labels('multi').slice(0, 2)).toEqual(['includes', 'excludes']);
		expect(operatorsForType('multi')[1].value).toBe('choice');
	});

	it('text: is / is empty / is answered', () => {
		expect(labels('text')).toEqual(['is', 'is empty', 'is answered']);
		expect(ids('text')).toEqual(['eq', 'not_answered', 'answered']);
	});

	it('date: ordering against another date question', () => {
		expect(ids('date')).toEqual(['eq', 'ne', 'lt', 'le', 'gt', 'ge', 'answered', 'not_answered']);
		expect(operatorsForType('date')[2]).toMatchObject({ label: 'is before', value: 'question' });
	});

	it('every type offers "is answered"; unknown types only that pair', () => {
		for (const t of ['integer', 'decimal', 'single', 'multi', 'text', 'date', 'ranking']) {
			expect(ids(t)).toContain('answered');
		}
		expect(ids('ranking')).toEqual(['answered', 'not_answered']);
	});

	it('keeps a loaded operator the type does not offer, and offers it on a deleted question', () => {
		expect(operatorsForRow(QMAP.get('q3'), 'gt').map((o) => o.id)).toEqual(['eq', 'not_answered', 'answered', 'gt']);
		expect(operatorsForRow(undefined, 'contains').map((o) => o.label)).toEqual(['includes']);
		expect(operatorsForRow(QMAP.get('q3'), 'eq').map((o) => o.id)).toEqual(['eq', 'not_answered', 'answered']);
	});
});

describe('values', () => {
	it('parses numbers into int or decimal literals', () => {
		expect(numberLiteral('18')).toEqual(int(18));
		expect(numberLiteral(' -3 ')).toEqual(int(-3));
		expect(numberLiteral('2.50')).toEqual({ kind: 'decimal', value: '2.50' });
		expect(numberLiteral('99999999999999999999')).toEqual({ kind: 'decimal', value: '99999999999999999999' });
		for (const bad of ['', 'x', '1.', '.5', '1e3', '1,5']) expect(numberLiteral(bad)).toBeNull();
	});

	it('keeps choice codes as numbers or text', () => {
		expect(choiceLiteral(1)).toEqual(int(1));
		expect(choiceLiteral('red')).toEqual(text('red'));
	});
});

describe('warnings', () => {
	it('flags a deleted question and pins server diagnostics to rows', () => {
		const gone = newRow('gone', 'eq', int(1));
		const later = newRow('age', 'gt', int(1));
		const ws = treeWarnings(newGroup('all', [gone, later]), QMAP, [
			{ code: 'ref.unknown', message: "'gone' is not a question", questionId: 'gone' },
			{ code: 'ref.forward', message: "'age' comes later in the flow", questionId: 'age' }
		]);
		expect(ws.map((w) => [w.kind, w.rowKey, w.code])).toEqual([
			['unknown-question', gone.key, undefined],
			['server', later.key, 'ref.forward']
		]);
	});

	it('warns on excludes and negated rows of optional questions, not on required ones', () => {
		const excl = newRow('colours', 'not_contains', text('red'));
		const inNone = newRow('pet', 'eq', int(1));
		const requiredInNone = newRow('age', 'gt', int(3));
		const notAnswered = newRow('q3', 'not_answered');
		const isNot = newRow('pet', 'ne', int(1));
		const root = newGroup('any', [excl, newGroup('none', [inNone, requiredInNone]), notAnswered, isNot]);
		const ws = treeWarnings(root, QMAP).filter((w) => w.kind === 'may-be-unanswered');
		expect(ws.map((w) => w.rowKey)).toEqual([excl.key, inNone.key]);
		expect(ws[1].fixKey).toBe((root.children[1] as GroupNode).key);
	});

	it('"also require answered" adds answered(q) and clears the warning', () => {
		const excl = newRow('colours', 'not_contains', text('red'));
		let root = newGroup('any', [excl, newRow('q3', 'answered')]);
		const [w] = treeWarnings(root, QMAP);
		root = requireAnswered(root, w.fixKey as string, w.question);
		expect(treeToAst(root, QMAP).ast).toEqual(
			or(and(answered('colours'), not(contains('colours', text('red')))), answered('q3'))
		);
		expect(treeWarnings(root, QMAP)).toEqual([]);

		// Inside an All of group the guard goes next to the row.
		const row = newRow('colours', 'not_contains', text('red'));
		const all = newGroup('all', [row]);
		const [w2] = treeWarnings(all, QMAP);
		requireAnswered(all, w2.fixKey as string, w2.question);
		expect(treeToAst(all, QMAP).ast).toEqual(and(answered('colours'), not(contains('colours', text('red')))));

		// A negated root is wrapped.
		const none = newGroup('none', [newRow('pet', 'eq', int(1))]);
		const [w3] = treeWarnings(none, QMAP);
		const wrapped = requireAnswered(none, w3.fixKey as string, w3.question);
		expect(treeToAst(wrapped, QMAP).ast).toEqual(and(answered('pet'), not(cmp('==', 'pet', int(1)))));
		expect(treeWarnings(wrapped, QMAP)).toEqual([]);
	});
});

describe('questions from survey JSON', () => {
	it('reads ids, types, labels and choices (inline or from a list); skips notes', () => {
		const qs = questionsFromSurvey({
			choiceLists: [{ id: 'c', choices: [{ value: 'a', label: { en: 'A', fr: 'Á' } }] }],
			blocks: [
				{
					pages: [
						{
							items: [
								{ type: 'note', id: 'n' },
								{ type: 'multi', id: 'm', label: { en: 'Pick' }, choiceList: 'c', required: true },
								{ type: 'single', id: 's', choices: [{ value: 2, label: 'Two' }], showIf: answered('m') }
							]
						}
					]
				}
			]
		});
		expect(qs).toEqual([
			Q('m', 'multi', { label: 'Pick', choices: [{ value: 'a', label: 'A' }], required: true }),
			Q('s', 'single', { label: '', choices: [{ value: 2, label: 'Two' }], conditional: true })
		]);
	});

	it('never throws on junk', () => {
		for (const junk of [null, 3, 'x', [], { blocks: 'x' }, { blocks: [{ pages: [{ items: [null, 1] }] }] }]) {
			expect(questionsFromSurvey(junk)).toEqual([]);
		}
	});
});

describe('text view positions', () => {
	it('maps code-point offsets to UTF-16 and never makes empty ranges', () => {
		expect(utf16Offset('😀 and', 2)).toBe(3);
		const ds = toCmDiagnostics('age >', [
			{ code: 'expected', message: 'expected a value', start: 5, end: 5 },
			{ code: 'x', message: 'no position' }
		]);
		expect(ds).toEqual([{ from: 4, to: 5, severity: 'error', message: 'expected a value' }]);
	});
});

/** A compact, key-free picture of a tree. */
function shape(node: CondNode): unknown {
	if (node.kind === 'row') {
		const v = node.value ? ` ${String(node.value.kind === 'ref' ? node.value.id : node.value.value)}` : '';
		return `${node.question} ${node.op}${v}`;
	}
	return { [node.mode]: node.children.map(shape) };
}
