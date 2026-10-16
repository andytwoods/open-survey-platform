import { describe, expect, it } from 'vitest';
import { SelectionStore } from '../selection.svelte';
import { MultiSelection } from './multi-select.svelte';

const TYPES: Record<string, string> = { p1: 'page', a: 'question', b: 'question', c: 'question', d: 'question' };
const typeOf = (id: string) => TYPES[id];
const ORDER = ['p1', 'a', 'b', 'c', 'd'];

describe('MultiSelection', () => {
	it('ctrl-toggles items of one type; another type starts over', () => {
		const sel = new SelectionStore();
		const m = new MultiSelection(sel);
		m.single('a');
		m.toggle('c', typeOf);
		expect(m.ids.sort()).toEqual(['a', 'c']);
		expect(sel.id).toBe('c');
		m.toggle('a', typeOf);
		expect(m.ids).toEqual(['c']);
		m.toggle('p1', typeOf);
		expect(m.ids).toEqual(['p1']);
	});

	it('shift extends a range of the anchor type', () => {
		const sel = new SelectionStore();
		const m = new MultiSelection(sel);
		m.single('b');
		m.range('d', ORDER, typeOf);
		expect(m.ids.sort()).toEqual(['b', 'c', 'd']);
		m.range('a', ORDER, typeOf);
		expect(m.ids.sort()).toEqual(['a', 'b']);
	});

	it('a selection made elsewhere resets to just that item', () => {
		const sel = new SelectionStore();
		const m = new MultiSelection(sel);
		m.single('a');
		m.toggle('b', typeOf);
		sel.select('d');
		expect(m.ids).toEqual(['d']);
		expect(m.has('a')).toBe(false);
	});
});
