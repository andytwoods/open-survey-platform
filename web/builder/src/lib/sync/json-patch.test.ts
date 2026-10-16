import { describe, expect, it } from 'vitest';
import { applyPatch, getAt, parsePointer, PatchError } from './json-patch';

describe('parsePointer', () => {
	it('splits and unescapes', () => {
		expect(parsePointer('')).toEqual([]);
		expect(parsePointer('/a/b~1c/d~0e')).toEqual(['a', 'b/c', 'd~e']);
		expect(() => parsePointer('a')).toThrow();
	});
});

describe('applyPatch', () => {
	const doc = { a: 1, list: [1, 2, 3], nested: { x: { y: 'z' } } };

	it('add / remove / replace on objects and arrays', () => {
		const out = applyPatch(doc, [
			{ op: 'add', path: '/b', value: { c: true } },
			{ op: 'add', path: '/list/1', value: 9 },
			{ op: 'add', path: '/list/-', value: 4 },
			{ op: 'remove', path: '/list/0' },
			{ op: 'replace', path: '/a', value: 2 },
			{ op: 'replace', path: '/nested/x/y', value: 'w' }
		]);
		expect(out).toEqual({ a: 2, b: { c: true }, list: [9, 2, 3, 4], nested: { x: { y: 'w' } } });
	});

	it('move and copy', () => {
		const out = applyPatch(doc, [
			{ op: 'move', from: '/list/0', path: '/list/2' },
			{ op: 'copy', from: '/nested/x', path: '/copied' }
		]);
		expect(out.list).toEqual([2, 3, 1]);
		expect(getAt(out, '/copied/y')).toBe('z');
	});

	it('does not mutate the input, and copies values it inserts', () => {
		const value = { deep: [1] };
		const out = applyPatch(doc, [{ op: 'add', path: '/v', value }]) as typeof doc & { v: typeof value };
		value.deep.push(2);
		expect(out.v.deep).toEqual([1]);
		expect(doc).toEqual({ a: 1, list: [1, 2, 3], nested: { x: { y: 'z' } } });
	});

	it('replaces the root with an empty path', () => {
		expect(applyPatch(doc, [{ op: 'replace', path: '', value: { r: 1 } }])).toEqual({ r: 1 });
	});

	it('test op passes on equal values and fails otherwise', () => {
		expect(() => applyPatch(doc, [{ op: 'test', path: '/nested', value: { x: { y: 'z' } } }])).not.toThrow();
		expect(() => applyPatch(doc, [{ op: 'test', path: '/a', value: 2 }])).toThrow(PatchError);
	});

	it('is all or nothing: a bad op throws PatchError with its index', () => {
		let err: unknown;
		try {
			applyPatch(doc, [
				{ op: 'replace', path: '/a', value: 5 },
				{ op: 'remove', path: '/missing' }
			]);
		} catch (e) {
			err = e;
		}
		expect(err).toBeInstanceOf(PatchError);
		expect((err as PatchError).index).toBe(1);
		expect(doc.a).toBe(1);
	});

	it.each([
		[{ op: 'bogus', path: '/a' }],
		[{ op: 'add', path: '/list/7', value: 1 }],
		[{ op: 'add', path: '/list/01', value: 1 }],
		[{ op: 'replace', path: '/nope', value: 1 }],
		[{ op: 'add', path: '/a/b', value: 1 }],
		[{ op: 'move', from: '/nested', path: '/nested/x/z' }],
		[{ op: 'remove', path: '' }],
		[{ op: 'add', path: '/x' }]
	])('rejects hostile op %j', (op) => {
		expect(() => applyPatch(doc, [op])).toThrow(PatchError);
	});

	it('rejects a non-array patch', () => {
		expect(() => applyPatch(doc, 'nope' as never)).toThrow(PatchError);
	});
});
