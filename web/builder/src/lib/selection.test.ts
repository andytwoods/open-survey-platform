import { describe, expect, it, vi } from 'vitest';
import { SelectionStore, selection } from './selection.svelte';

describe('SelectionStore', () => {
	it('starts empty, selects and clears', () => {
		const s = new SelectionStore();
		expect(s.id).toBeNull();
		s.select('q_hours');
		expect(s.id).toBe('q_hours');
		expect(s.isSelected('q_hours')).toBe(true);
		expect(s.isSelected('q_info')).toBe(false);
		s.clear();
		expect(s.id).toBeNull();
	});

	it('notifies only on real changes', () => {
		const s = new SelectionStore();
		const fn = vi.fn();
		const off = s.onChange(fn);
		s.select('a');
		s.select('a');
		s.select('b');
		s.clear();
		expect(fn.mock.calls).toEqual([['a'], ['b'], [null]]);
		off();
		s.select('c');
		expect(fn).toHaveBeenCalledTimes(3);
	});

	it('exports one shared instance for all panes', () => {
		expect(selection).toBeInstanceOf(SelectionStore);
	});
});
