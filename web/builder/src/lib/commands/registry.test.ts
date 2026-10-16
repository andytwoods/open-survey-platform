import { describe, expect, it, vi } from 'vitest';
import { CommandRegistry, type KeyEventLike } from './registry';
import { ariaShortcut, formatShortcut, matchesShortcut, parseShortcut } from './shortcut';

function key(k: string, mods: Partial<KeyEventLike> = {}): KeyEventLike {
	return { key: k, ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, ...mods };
}

describe('shortcut', () => {
	it('parses modifiers and key', () => {
		expect(parseShortcut('Mod+Shift+Z')).toMatchObject({ mod: true, shift: true, key: 'z' });
		expect(parseShortcut('F6')).toMatchObject({ mod: false, key: 'f6' });
	});

	it('rejects unknown modifiers and empty shortcuts', () => {
		expect(() => parseShortcut('Hyper+K')).toThrow(/Unknown modifier/);
		expect(() => parseShortcut('')).toThrow(/Empty/);
	});

	it('maps Mod to Ctrl off Mac and Cmd on Mac', () => {
		expect(matchesShortcut('Mod+K', key('k', { ctrlKey: true }), false)).toBe(true);
		expect(matchesShortcut('Mod+K', key('k', { metaKey: true }), false)).toBe(false);
		expect(matchesShortcut('Mod+K', key('k', { metaKey: true }), true)).toBe(true);
		expect(matchesShortcut('Mod+K', key('k', { ctrlKey: true }), true)).toBe(false);
	});

	it('requires exact modifiers and ignores letter case', () => {
		expect(matchesShortcut('Mod+Z', key('z', { ctrlKey: true, shiftKey: true }), false)).toBe(false);
		expect(matchesShortcut('Mod+Shift+Z', key('Z', { ctrlKey: true, shiftKey: true }), false)).toBe(
			true
		);
		expect(matchesShortcut('Shift+F6', key('F6', { shiftKey: true }), false)).toBe(true);
	});

	it('formats for display and aria-keyshortcuts', () => {
		expect(formatShortcut('Mod+Shift+Z', false)).toBe('Ctrl+Shift+Z');
		expect(formatShortcut('Mod+Shift+Z', true)).toBe('⇧⌘Z');
		expect(formatShortcut('F6', false)).toBe('F6');
		expect(ariaShortcut('Mod+K', false)).toBe('Control+K');
		expect(ariaShortcut('Mod+K', true)).toBe('Meta+K');
	});
});

describe('CommandRegistry', () => {
	it('registers, lists in order, and unregisters', () => {
		const r = new CommandRegistry();
		const off = r.register({ id: 'a', label: 'A', run: () => {} });
		r.register({ id: 'b', label: 'B', run: () => {} });
		expect(r.list().map((c) => c.id)).toEqual(['a', 'b']);
		off();
		expect(r.get('a')).toBeUndefined();
		expect(r.list().map((c) => c.id)).toEqual(['b']);
	});

	it('rejects duplicate and empty ids', () => {
		const r = new CommandRegistry();
		r.register({ id: 'a', label: 'A', run: () => {} });
		expect(() => r.register({ id: 'a', label: 'A2', run: () => {} })).toThrow(/already registered/);
		expect(() => r.register({ id: '', label: 'x', run: () => {} })).toThrow(/needs an id/);
	});

	it('runs enabled commands only, and reports unknown ids', () => {
		const r = new CommandRegistry();
		const run = vi.fn();
		let on = false;
		r.register({ id: 'x', label: 'X', enabled: () => on, run });
		expect(r.run('x')).toBe(false);
		on = true;
		expect(r.run('x')).toBe(true);
		expect(run).toHaveBeenCalledTimes(1);
		expect(r.run('nope')).toBe(false);
	});

	it('treats a throwing enabled() as disabled instead of crashing', () => {
		const r = new CommandRegistry();
		r.register({
			id: 'x',
			label: 'X',
			enabled: () => {
				throw new Error('boom');
			},
			run: () => {}
		});
		expect(r.isEnabled('x')).toBe(false);
		expect(r.run('x')).toBe(false);
	});

	it('dispatches shortcuts to the matching command and prevents the default', () => {
		const r = new CommandRegistry({ isMac: false });
		const undo = vi.fn();
		const redo = vi.fn();
		r.register({ id: 'edit.undo', label: 'Undo', shortcut: 'Mod+Z', run: undo });
		r.register({ id: 'edit.redo', label: 'Redo', shortcut: ['Mod+Shift+Z', 'Mod+Y'], run: redo });
		const preventDefault = vi.fn();

		expect(r.handleKeydown({ ...key('z', { ctrlKey: true }), preventDefault })).toBe(true);
		expect(undo).toHaveBeenCalledTimes(1);
		expect(preventDefault).toHaveBeenCalledTimes(1);

		r.handleKeydown(key('Z', { ctrlKey: true, shiftKey: true }));
		r.handleKeydown(key('y', { ctrlKey: true }));
		expect(redo).toHaveBeenCalledTimes(2);

		expect(r.handleKeydown(key('q', { ctrlKey: true }))).toBe(false);
	});

	it('skips shortcuts in text fields unless the command allows it', () => {
		const r = new CommandRegistry();
		const undo = vi.fn();
		const palette = vi.fn();
		r.register({ id: 'edit.undo', label: 'Undo', shortcut: 'Mod+Z', run: undo });
		r.register({ id: 'palette', label: 'Palette', shortcut: 'Mod+K', allowInEditable: true, run: palette });
		const target = { tagName: 'INPUT' } as unknown as EventTarget;

		expect(r.handleKeydown({ ...key('z', { ctrlKey: true }), target })).toBe(false);
		expect(undo).not.toHaveBeenCalled();
		expect(r.handleKeydown({ ...key('k', { ctrlKey: true }), target })).toBe(true);
		expect(palette).toHaveBeenCalledTimes(1);
	});

	it('ignores disabled commands and already-handled events', () => {
		const r = new CommandRegistry();
		const run = vi.fn();
		r.register({ id: 'f6', label: 'Next pane', shortcut: 'F6', enabled: () => false, run });
		expect(r.handleKeydown(key('F6'))).toBe(false);
		expect(r.handleKeydown({ ...key('F6'), defaultPrevented: true })).toBe(false);
		expect(run).not.toHaveBeenCalled();
	});

	it('while a modal is open, only allowInModal shortcuts fire', () => {
		let modal = true;
		const r = new CommandRegistry({ isModalOpen: () => modal });
		const undo = vi.fn();
		const palette = vi.fn();
		r.register({ id: 'edit.undo', label: 'Undo', shortcut: 'Mod+Z', run: undo });
		r.register({ id: 'palette', label: 'Palette', shortcut: 'Mod+K', allowInModal: true, run: palette });
		expect(r.handleKeydown(key('z', { ctrlKey: true }))).toBe(false);
		expect(r.handleKeydown(key('k', { ctrlKey: true }))).toBe(true);
		expect(r.isEnabled('edit.undo')).toBe(true); // still runnable by id, e.g. from the palette
		modal = false;
		expect(r.handleKeydown(key('z', { ctrlKey: true }))).toBe(true);
		expect(undo).toHaveBeenCalledTimes(1);
		expect(palette).toHaveBeenCalledTimes(1);
	});

	it('notifies subscribers on change', () => {
		const r = new CommandRegistry();
		const fn = vi.fn();
		const unsub = r.subscribe(fn);
		const off = r.registerAll([
			{ id: 'a', label: 'A', run: () => {} },
			{ id: 'b', label: 'B', run: () => {} }
		]);
		off();
		expect(fn).toHaveBeenCalledTimes(4);
		unsub();
		r.register({ id: 'c', label: 'C', run: () => {} });
		expect(fn).toHaveBeenCalledTimes(4);
	});
});
