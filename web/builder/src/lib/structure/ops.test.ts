import { describe, expect, it } from 'vitest';
import { outlineFromSurvey } from '../model/outline';
import { addBlockPlan, addPagePlan, deletePlan, duplicatePlan, freeId, neighbourOf, placeOf, usedIds } from './ops';

const q = (id: string, extra: Record<string, unknown> = {}) => ({ id, type: 'text', label: id, ...extra });
const SURVEY = {
	id: 's',
	blocks: [
		{ id: 'b1', pages: [{ id: 'p1', items: [q('qa'), q('qb')] }, { id: 'p2', items: [q('qc')] }] },
		{
			id: 'b2',
			pages: [
				{
					id: 'p3',
					items: [{ id: 'grid', type: 'matrix', label: 'G', rows: [{ id: 'r1', label: 'R' }], choices: [] }]
				}
			]
		},
		{ id: 'loose', pages: [{ id: 'p4', items: [q('qd')] }] }
	],
	flow: [
		{ type: 'block', id: 'n1', block: 'b1' },
		{ type: 'randomiser', id: 'rnd', children: [{ type: 'block', id: 'n2', block: 'b2' }] }
	]
};
const roots = outlineFromSurvey(SURVEY);

describe('ids', () => {
	it('collects ids, names and grid row variables', () => {
		const ids = usedIds(SURVEY);
		for (const id of ['b1', 'p1', 'qa', 'n1', 'rnd', 'grid_r1']) expect(ids.has(id)).toBe(true);
	});

	it('picks the exact id first, then numbers, ignoring case', () => {
		expect(freeId(new Set(['a']), 'b', true)).toBe('b');
		expect(freeId(new Set(['B']), 'b', true)).toBe('b1');
		expect(freeId(new Set(['page1', 'PAGE2']), 'page')).toBe('page3');
	});
});

describe('placeOf / neighbourOf', () => {
	it('locates blocks, pages and questions', () => {
		expect(placeOf(roots, 'p2')).toMatchObject({ type: 'page', blockIndex: 0, pageIndex: 1 });
		expect(placeOf(roots, 'qb')).toMatchObject({ type: 'question', pageIndex: 0, questionIndex: 1 });
		expect(placeOf(roots, 'nope')).toBeUndefined();
	});

	it('selects the next sibling, else the previous, else the parent', () => {
		expect(neighbourOf(roots, 'p1')).toBe('p2');
		expect(neighbourOf(roots, 'p2')).toBe('p1');
		expect(neighbourOf(roots, 'p3')).toBe('b2');
		expect(neighbourOf(roots, 'loose')).toBe('b2');
	});
});

describe('addPagePlan', () => {
	it('goes after the selected page or question’s page', () => {
		expect(addPagePlan(SURVEY, roots, 'p1')?.ops).toEqual([
			{ op: 'add_page', params: { block: 'b1', index: 1, id: 'page1' } }
		]);
		expect(addPagePlan(SURVEY, roots, 'qc')?.ops[0].params).toMatchObject({ block: 'b1', index: 2 });
	});

	it('goes at the end of a selected block, else of the last block', () => {
		expect(addPagePlan(SURVEY, roots, 'b2')?.ops[0].params).toMatchObject({ block: 'b2', index: 1 });
		expect(addPagePlan(SURVEY, roots, null)?.ops[0].params).toMatchObject({ block: 'loose', index: 1 });
		expect(addPagePlan({ blocks: [] }, [], null)).toBeUndefined();
	});
});

describe('addBlockPlan', () => {
	it('adds a block after the selected one and shows it after its flow node', () => {
		const plan = addBlockPlan(SURVEY, roots, 'p3');
		expect(plan.id).toBe('block1');
		expect(plan.ops).toEqual([
			{ op: 'add_block', params: { id: 'block1', index: 2 } },
			{
				op: 'insert_flow_node',
				params: { node: { type: 'block', id: 'n_block1', block: 'block1' }, parent: 'rnd', arm: 'children', index: 1 }
			}
		]);
	});

	it('without a selection (or an unplaced block) goes at the end of both', () => {
		expect(addBlockPlan(SURVEY, roots).ops).toEqual([
			{ op: 'add_block', params: { id: 'block1' } },
			{ op: 'insert_flow_node', params: { node: { type: 'block', id: 'n_block1', block: 'block1' } } }
		]);
		expect(addBlockPlan(SURVEY, roots, 'loose').ops[1].params).not.toHaveProperty('index');
	});
});

describe('duplicatePlan', () => {
	it('names the copy <id>_copy and places a block copy next to its flow node', () => {
		expect(duplicatePlan(SURVEY, roots, 'p1')?.ops).toEqual([
			{ op: 'duplicate_page', params: { id: 'p1', new_id: 'p1_copy' } }
		]);
		expect(duplicatePlan(SURVEY, roots, 'qa')?.ops[0]).toEqual({
			op: 'duplicate_question',
			params: { id: 'qa', new_id: 'qa_copy' }
		});
		expect(duplicatePlan(SURVEY, roots, 'b1')?.ops).toEqual([
			{ op: 'duplicate_block', params: { id: 'b1', new_id: 'b1_copy' } },
			{ op: 'insert_flow_node', params: { node: { type: 'block', id: 'n_b1_copy', block: 'b1_copy' }, index: 1 } }
		]);
	});

	it('does not place the copy of a block that is not in the flow', () => {
		expect(duplicatePlan(SURVEY, roots, 'loose')?.ops).toHaveLength(1);
	});
});

describe('deletePlan', () => {
	it('deletes a block with its flow nodes, in one transaction', () => {
		expect(deletePlan(SURVEY, roots, 'b2')).toEqual({
			ops: [
				{ op: 'delete_flow_node', params: { id: 'n2' } },
				{ op: 'delete_block', params: { id: 'b2' } }
			]
		});
		expect(deletePlan(SURVEY, roots, 'p1', true)).toEqual({ ops: [{ op: 'delete_page', params: { id: 'p1', force: true } }] });
	});

	it('refuses to empty a block or a page', () => {
		expect(deletePlan(SURVEY, roots, 'p3')).toHaveProperty('refused');
		expect(deletePlan(SURVEY, roots, 'qc')).toHaveProperty('refused');
		expect(deletePlan(SURVEY, roots, 'qa')).toEqual({ ops: [{ op: 'delete_question', params: { id: 'qa' } }] });
	});
});
