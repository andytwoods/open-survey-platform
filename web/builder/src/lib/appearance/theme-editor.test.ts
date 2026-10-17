import { describe, expect, it } from 'vitest';
import { DRAFT_KEY, ThemeEditor, presetTheme, type Storage } from './theme-editor.svelte';

function memoryStorage(): Storage & { data: Map<string, string> } {
	const data = new Map<string, string>();
	return {
		data,
		getItem: (k) => data.get(k) ?? null,
		setItem: (k, v) => void data.set(k, v),
		removeItem: (k) => void data.delete(k)
	};
}

function editor() {
	let t = 0;
	const storage = memoryStorage();
	const clock = { advance: (ms: number) => (t += ms) };
	const ed = new ThemeEditor({ now: () => t, storage: () => storage });
	return { ed, storage, clock };
}

describe('ThemeEditor', () => {
	it('starts from the Clean preset, publishable', () => {
		const { ed } = editor();
		expect(ed.theme).toEqual(presetTheme('clean'));
		expect(ed.canPublish).toBe(true);
		expect(ed.canUndo).toBe(false);
	});

	it('undoes and redoes field changes', () => {
		const { ed, clock } = editor();
		ed.set('radius', 12);
		clock.advance(5000);
		ed.set('density', 'compact');
		expect(ed.canUndo).toBe(true);
		ed.undo();
		expect(ed.theme.density).toBe('comfortable');
		expect(ed.theme.radius).toBe(12);
		ed.undo();
		expect(ed.theme.radius).toBe(6);
		expect(ed.canUndo).toBe(false);
		ed.redo();
		ed.redo();
		expect(ed.theme.density).toBe('compact');
		expect(ed.canRedo).toBe(false);
	});

	it('coalesces rapid changes to one control into one undo step', () => {
		const { ed, clock } = editor();
		for (const hex of ['#111111', '#222222', '#333333']) {
			ed.setColour('light', 'accent', hex);
			clock.advance(100);
		}
		clock.advance(2000);
		ed.setColour('light', 'accent', '#444444');
		ed.undo();
		expect(ed.theme.colours.light.accent).toBe('#333333');
		ed.undo();
		expect(ed.theme.colours.light.accent).toBe('#2456c7');
	});

	it('a new change clears redo; a no-op change records nothing', () => {
		const { ed } = editor();
		ed.set('radius', 6);
		expect(ed.canUndo).toBe(false);
		ed.set('radius', 10);
		ed.undo();
		ed.set('mode', 'dark');
		expect(ed.canRedo).toBe(false);
	});

	it('ignores colours that are not #rrggbb', () => {
		const { ed } = editor();
		ed.setColour('light', 'accent', '#fff');
		ed.setColour('light', 'accent', 'red');
		expect(ed.canUndo).toBe(false);
	});

	it('flags contrast problems and fixes them with the suggestion', () => {
		const { ed } = editor();
		ed.setColour('light', 'accent', '#66aaff');
		expect(ed.canPublish).toBe(false);
		expect(ed.contrastProblems.length).toBeGreaterThan(0);
		ed.applySuggestion(ed.contrastProblems[0]);
		expect(ed.contrastProblems).toEqual([]);
		expect(ed.canPublish).toBe(true);
		ed.undo();
		expect(ed.theme.colours.light.accent).toBe('#66aaff');
	});

	it('only checks the modes the theme shows', () => {
		const { ed } = editor();
		ed.setColour('dark', 'accent', '#101010');
		expect(ed.canPublish).toBe(false);
		ed.set('mode', 'light');
		expect(ed.canPublish).toBe(true);
	});

	it('applies a preset but keeps brand text and logo', () => {
		const { ed } = editor();
		ed.set('headerText', 'Sleep lab');
		ed.applyPreset('warm');
		expect(ed.theme.preset).toBe('warm');
		expect(ed.theme.font).toBe('system-serif');
		expect(ed.theme.headerText).toBe('Sleep lab');
		ed.undo();
		expect(ed.theme.preset).toBe('clean');
	});

	it('round-trips through JSON export/import', () => {
		const { ed } = editor();
		ed.applyPreset('high-contrast');
		const json = ed.toJson();
		const other = editor().ed;
		expect(other.importJson(json)).toEqual({ ok: true, problems: [] });
		expect(other.theme).toEqual(ed.theme);
		other.undo();
		expect(other.theme.preset).toBe('clean');
	});

	it('rejects invalid JSON without changing the theme', () => {
		const { ed } = editor();
		const res = ed.importJson('{"colours": {"light": {}}}');
		expect(res.ok).toBe(false);
		expect(res.problems.length).toBeGreaterThan(0);
		expect(ed.canUndo).toBe(false);
		expect(ed.importJson('nope').ok).toBe(false);
	});

	it('keeps a local draft and loads it back', () => {
		const { ed, storage } = editor();
		ed.set('radius', 20);
		expect(JSON.parse(storage.data.get(DRAFT_KEY)!).radius).toBe(20);
		const again = new ThemeEditor({ storage: () => storage });
		expect(again.loadDraft()).toBe(true);
		expect(again.theme.radius).toBe(20);
		expect(again.canUndo).toBe(false);
	});

	it('ignores a corrupt draft and survives blocked storage', () => {
		const storage = memoryStorage();
		storage.data.set(DRAFT_KEY, '{"colours": 1}');
		expect(new ThemeEditor({ storage: () => storage }).loadDraft()).toBe(false);
		const blocked: Storage = {
			getItem: () => {
				throw new Error('blocked');
			},
			setItem: () => {
				throw new Error('blocked');
			},
			removeItem: () => {
				throw new Error('blocked');
			}
		};
		const ed = new ThemeEditor({ storage: () => blocked });
		expect(ed.loadDraft()).toBe(false);
		ed.set('radius', 3);
		ed.reset();
		expect(ed.theme.radius).toBe(6);
	});

	it('suggests 16 px when an imported theme has a smaller base size', () => {
		const { ed } = editor();
		const t = { ...presetTheme('clean'), baseSize: 14 };
		expect(ed.importJson(JSON.stringify(t)).ok).toBe(true);
		const d = ed.diagnostics.find((x) => x.code === 'theme.input_font_size')!;
		expect(d.suggestion).toBe(16);
		ed.applySuggestion(d);
		expect(ed.theme.baseSize).toBe(16);
	});
});

describe('ThemeEditor.loadTheme (survey and library themes, B12)', () => {
	it('starts from a source once, keeping edits when the same source opens again', () => {
		const { ed } = editor();
		expect(ed.loadTheme(presetTheme('warm'), 'survey:s1')).toBe(true);
		expect(ed.theme.preset).toBe('warm');
		expect(ed.canUndo).toBe(false);
		ed.set('radius', 0);
		expect(ed.loadTheme(presetTheme('warm'), 'survey:s1')).toBe(false);
		expect(ed.theme.radius).toBe(0);
	});

	it('loads a library theme as an undoable step', () => {
		const { ed } = editor();
		ed.loadTheme(presetTheme('dark'), 'library:t1', { undoable: true });
		expect(ed.theme.preset).toBe('dark');
		expect(ed.undo()).toBe(true);
		expect(ed.theme.preset).toBe('clean');
	});
});
