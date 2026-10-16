import { describe, expect, it } from 'vitest';
import { ancestorsOf, findNode, navigate, visibleRows, type TreeNode } from './tree-nav';

const tree: TreeNode[] = [
	{ id: 'p1', children: [{ id: 'b1', children: [{ id: 'q1' }, { id: 'q2' }] }] },
	{ id: 'p2', children: [{ id: 'b2', children: [{ id: 'q3' }] }] }
];
const all = new Set(['p1', 'b1', 'p2', 'b2']);

describe('tree navigation', () => {
	it('lists visible rows with levels, hiding collapsed children', () => {
		expect(visibleRows(tree, all).map((r) => `${r.node.id}:${r.level}`)).toEqual([
			'p1:1',
			'b1:2',
			'q1:3',
			'q2:3',
			'p2:1',
			'b2:2',
			'q3:3'
		]);
		const q2 = visibleRows(tree, all).find((r) => r.node.id === 'q2');
		expect(q2).toMatchObject({ parentId: 'b1', setsize: 2, posinset: 2 });
		expect(visibleRows(tree, new Set(['p2'])).map((r) => r.node.id)).toEqual(['p1', 'p2', 'b2']);
	});

	it('moves up/down through visible rows and stops at the ends', () => {
		expect(navigate('ArrowDown', 'q2', tree, all)).toEqual({ kind: 'focus', id: 'p2' });
		expect(navigate('ArrowUp', 'p2', tree, all)).toEqual({ kind: 'focus', id: 'q2' });
		expect(navigate('ArrowUp', 'p1', tree, all)).toEqual({ kind: 'none' });
		expect(navigate('ArrowDown', 'q3', tree, all)).toEqual({ kind: 'none' });
		expect(navigate('Home', 'q3', tree, all)).toEqual({ kind: 'focus', id: 'p1' });
		expect(navigate('End', 'p1', tree, all)).toEqual({ kind: 'focus', id: 'q3' });
	});

	it('right expands, then enters; left collapses, then goes to the parent', () => {
		const closed = new Set<string>();
		expect(navigate('ArrowRight', 'p1', tree, closed)).toEqual({ kind: 'expand', id: 'p1' });
		expect(navigate('ArrowRight', 'p1', tree, all)).toEqual({ kind: 'focus', id: 'b1' });
		expect(navigate('ArrowRight', 'q1', tree, all)).toEqual({ kind: 'none' });
		expect(navigate('ArrowLeft', 'b1', tree, all)).toEqual({ kind: 'collapse', id: 'b1' });
		expect(navigate('ArrowLeft', 'q1', tree, all)).toEqual({ kind: 'focus', id: 'b1' });
		expect(navigate('ArrowLeft', 'p1', tree, closed)).toEqual({ kind: 'none' });
	});

	it('recovers from an unknown current id by focusing the first row', () => {
		expect(navigate('ArrowDown', 'gone', tree, all)).toEqual({ kind: 'focus', id: 'p1' });
		expect(navigate('ArrowDown', 'gone', [], all)).toEqual({ kind: 'none' });
	});

	it('finds nodes and ancestors', () => {
		expect(ancestorsOf(tree, 'q3')).toEqual(['p2', 'b2']);
		expect(ancestorsOf(tree, 'p1')).toEqual([]);
		expect(ancestorsOf(tree, 'missing')).toEqual([]);
		expect(findNode(tree, 'b2')?.id).toBe('b2');
		expect(findNode(tree, 'missing')).toBeUndefined();
	});
});
