import { describe, expect, it } from 'vitest';
import {
	blocks,
	descendantCount,
	diagnosticsByNode,
	dropTarget,
	emptyForm,
	flagFor,
	formError,
	freshId,
	insertOps,
	keyMoveTarget,
	nodeLabel,
	parseGap,
	slots,
	unavailable,
	walk
} from './model';

const survey = {
	metadata: { languages: ['en'] },
	blocks: [
		{ id: 'consent', pages: [{ id: 'p1', items: [{ id: 'q1' }] }] },
		{ id: 'demo', title: 'Demographics', pages: [{ id: 'p2', items: [{ id: 'q2' }, { id: 'q3' }] }] },
		{ id: 'spare', pages: [] }
	],
	variables: [{ kind: 'assigned', id: 'framing', levels: ['gain', 'loss'] }],
	quotas: [{ id: 'q_old', when: { kind: 'bool', value: true }, limit: 5, onFull: { outcome: 'full' } }],
	flow: [
		{ type: 'block', id: 'n1', block: 'consent' },
		{
			type: 'branch',
			id: 'b1',
			if: { kind: 'compare', op: '==', left: { kind: 'ref', id: 'q1' }, right: { kind: 'int', value: 0 } },
			then: [{ type: 'end', id: 'e1', outcome: 'declined' }],
			else: []
		},
		{ type: 'block', id: 'n2', block: 'demo' }
	]
};

describe('walk', () => {
	it('lists nodes in document order with pointers and depth', () => {
		expect(walk(survey).map((r) => [r.id, r.pointer, r.depth, r.parent, r.arm])).toEqual([
			['n1', '/flow/0', 0, null, null],
			['b1', '/flow/1', 0, null, null],
			['e1', '/flow/1/then/0', 1, 'b1', 'then'],
			['n2', '/flow/2', 0, null, null]
		]);
	});
	it('never throws on hostile input', () => {
		for (const bad of [null, 3, 'x', { flow: 'no' }, { flow: [null, { type: 'nope' }, { type: 'block' }] }]) {
			expect(walk(bad)).toEqual([]);
			expect(slots(bad).length).toBeGreaterThan(0);
			expect(blocks(bad)).toEqual([]);
		}
	});
});

describe('keyboard moves cross levels', () => {
	it('moves down into the next branch, through its arms, and out', () => {
		expect(keyMoveTarget(survey, 'n1', 1)).toMatchObject({ parent: 'b1', arm: 'then', index: 0 });
		expect(keyMoveTarget(survey, 'n2', -1)).toMatchObject({ parent: 'b1', arm: 'else', index: 0 });
		expect(keyMoveTarget(survey, 'e1', 1)).toMatchObject({ parent: 'b1', arm: 'else', index: 0 });
		expect(keyMoveTarget(survey, 'e1', -1)).toMatchObject({ parent: null, index: 1 });
	});
	it('stops at the ends', () => {
		expect(keyMoveTarget(survey, 'n1', -1)).toBeNull();
		expect(keyMoveTarget(survey, 'n2', 1)).toBeNull();
		expect(keyMoveTarget(survey, 'missing', 1)).toBeNull();
	});
	it('skips the moved node’s own subtree', () => {
		const s = slots(survey, 'b1');
		expect(s.some((x) => x.parent === 'b1')).toBe(false);
		expect(keyMoveTarget(survey, 'b1', -1)).toMatchObject({ parent: null, index: 0 });
	});
});

describe('dropTarget', () => {
	it('adjusts the index for removal and ignores no-op drops', () => {
		expect(dropTarget(survey, 'n1', { parent: null, arm: null, index: 0 })).toBeNull();
		expect(dropTarget(survey, 'n1', { parent: null, arm: null, index: 1 })).toBeNull();
		expect(dropTarget(survey, 'n1', { parent: null, arm: null, index: 3 })).toEqual({ parent: null, arm: null, index: 2 });
		expect(dropTarget(survey, 'n2', { parent: 'b1', arm: 'else', index: 0 })).toEqual({ parent: 'b1', arm: 'else', index: 0 });
	});
	it('refuses a drop inside itself', () => {
		expect(dropTarget(survey, 'b1', { parent: 'b1', arm: 'then', index: 0 })).toBeNull();
	});
});

describe('diagnostics', () => {
	it('pins each /flow diagnostic to the deepest node and explains it', () => {
		const d = [
			{ code: 'flow.unreachable', message: 'x', pointer: '/flow/1/then/0', severity: 'warning' },
			{ code: 'flow.empty_branch', message: 'y', pointer: '/flow/1/then', severity: 'warning' },
			{ code: 'block.unused', message: 'z', pointer: '/blocks/2', severity: 'warning' },
			{ code: 'flow.pick_too_large', message: 'pick 3', pointer: '/flow/9', severity: 'error' }
		];
		const m = diagnosticsByNode(walk(survey), d);
		expect(m.get('e1')?.map((x) => x.code)).toEqual(['flow.unreachable']);
		expect(m.get('b1')?.map((x) => x.code)).toEqual(['flow.empty_branch']);
		expect(m.size).toBe(2);
		expect(flagFor(d[0])).toMatchObject({ kind: 'unreachable', label: 'Unreachable' });
		expect(flagFor(d[0]).explanation).toMatch(/never reach/);
		expect(flagFor(d[3])).toMatchObject({ kind: 'error', explanation: 'Error: pick 3' });
	});
});

describe('new nodes', () => {
	it('defaults to the first block not yet in the flow', () => {
		expect(emptyForm(survey).block).toBe('spare');
		expect(emptyForm(survey).variables).toEqual(['framing']);
	});
	it('builds insert ops; a branch sets its condition in the same transaction', () => {
		const f = { ...emptyForm(survey, 'branch'), condition: 'q1 == 1' };
		const { id, ops } = insertOps(survey, f, { parent: 'b1', arm: 'else', index: 0 });
		expect(id).toBe('branch_1');
		expect(ops).toEqual([
			{
				op: 'insert_flow_node',
				params: { node: { type: 'branch', id, if: { kind: 'bool', value: true }, then: [] }, parent: 'b1', arm: 'else', index: 0 }
			},
			{ op: 'set_condition', params: { target: id, condition: 'q1 == 1' } }
		]);
		const r = insertOps(survey, emptyForm(survey, 'randomiser'), { parent: null, arm: null });
		expect(r.ops[0].params.node).toMatchObject({ type: 'randomiser', children: [{ type: 'block', block: 'spare' }] });
		const e = insertOps(survey, { ...emptyForm(survey, 'end'), outcome: 'screened', message: 'Bye' }, { parent: null, arm: null, index: 3 });
		expect(e.ops[0].params).toMatchObject({ node: { type: 'end', outcome: 'screened', message: { en: 'Bye' } }, index: 3 });
	});
	it('validates the form and says why a type is unavailable', () => {
		expect(formError({ ...emptyForm(survey, 'branch') })).toMatch(/condition/);
		expect(formError({ ...emptyForm(survey, 'end'), outcome: '9x' })).toMatch(/Outcome/);
		expect(formError(emptyForm(survey, 'block'))).toBeNull();
		expect(unavailable({}, 'assign')).toMatch(/assigned variable/);
		expect(unavailable(survey, 'quotaCheck')).toBeNull();
	});
	it('makes fresh ids that do not clash', () => {
		expect(freshId({ flow: [{ id: 'end_1' }], variables: [{ name: 'end_2' }] }, 'end')).toBe('end_3');
	});
});

it('parses gap keys', () => {
	expect(parseGap('flow::2')).toEqual({ parent: null, arm: null, index: 2 });
	expect(parseGap('branch_1:else:0')).toEqual({ parent: 'branch_1', arm: 'else', index: 0 });
	for (const bad of [null, '', 'x::', 'b:nope:1', 'b::1', '1x:then:0']) expect(parseGap(bad)).toBeNull();
});

it('labels nodes', () => {
	const [n1, b1, e1, n2] = walk(survey);
	expect(nodeLabel(n1.node, survey)).toBe('Block: consent');
	expect(nodeLabel(n2.node, survey)).toBe('Block: Demographics');
	expect(nodeLabel(b1.node)).toBe('Branch: if q1 == 0');
	expect(nodeLabel(e1.node)).toBe('End: declined');
	expect(nodeLabel({ type: 'randomiser', children: [1, 2], pick: 1 })).toBe('Randomiser: 1 of 2');
	expect(descendantCount(b1.node)).toBe(1);
});
