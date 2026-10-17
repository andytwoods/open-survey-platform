/**
 * The theme being edited in the Appearance view, with undo/redo and a local draft.
 *
 * Every change goes through `update()` (or a helper built on it), which records the
 * previous theme for undo. Rapid edits to the same control (dragging a slider or a colour
 * picker) coalesce into one undo step. The shell's Undo/Redo commands call `undo()` /
 * `redo()` while the Appearance view is open.
 *
 * Persistence to the store/API comes later; for now the draft lives in localStorage
 * (best effort) and themes move in and out as JSON.
 */
import {
	THEME_DEFAULTS,
	THEME_PRESETS,
	THEME_VERSION,
	type Mode,
	type PaletteField,
	type PresetId,
	type Theme
} from '@osp/ui-components';
import { checkTheme, type ThemeDiagnostic } from './guard';
import { parseThemeJson, type ImportProblem } from './validate';

export const DRAFT_KEY = 'osp-appearance-draft';
const HISTORY_LIMIT = 200;
const COALESCE_MS = 1000;

const clone = (t: Theme): Theme => JSON.parse(JSON.stringify(t));

/** A complete theme: every optional field filled with its default, so controls are bound. */
export function normalise(t: Theme): Required<Theme> {
	return {
		themeVersion: THEME_VERSION,
		preset: null,
		logoAssetId: null,
		headerText: null,
		...THEME_DEFAULTS,
		...clone(t)
	} as Required<Theme>;
}

export function presetTheme(id: PresetId): Required<Theme> {
	const p = THEME_PRESETS.find((x) => x.id === id) ?? THEME_PRESETS[0];
	return normalise(p.theme);
}

export interface Storage {
	getItem(key: string): string | null;
	setItem(key: string, value: string): void;
	removeItem(key: string): void;
}

function defaultStorage(): Storage | null {
	try {
		return globalThis.localStorage ?? null;
	} catch {
		return null;
	}
}

export class ThemeEditor {
	theme = $state<Required<Theme>>(presetTheme('clean'));
	#past = $state<Theme[]>([]);
	#future = $state<Theme[]>([]);
	#lastKey: string | null = null;
	#lastAt = 0;
	readonly #now: () => number;
	readonly #storage: () => Storage | null;

	/** Every guard diagnostic for the current theme (contrast in each shown mode, font size). */
	readonly diagnostics: ThemeDiagnostic[] = $derived(checkTheme(this.theme));
	readonly contrastProblems = $derived(this.diagnostics.filter((d) => d.code === 'theme.contrast'));
	readonly canPublish = $derived(this.diagnostics.length === 0);

	constructor({ now = () => Date.now(), storage = defaultStorage } = {}) {
		this.#now = now;
		this.#storage = storage;
	}

	get canUndo() {
		return this.#past.length > 0;
	}
	get canRedo() {
		return this.#future.length > 0;
	}

	/**
	 * Change the theme. `key` names the control: consecutive changes with the same key
	 * within a second are one undo step.
	 */
	update(fn: (draft: Required<Theme>) => void, key: string | null = null): void {
		const before = clone(this.theme);
		const next = normalise(before);
		fn(next);
		if (JSON.stringify(next) === JSON.stringify(before)) return;
		const now = this.#now();
		const coalesce = key !== null && key === this.#lastKey && now - this.#lastAt < COALESCE_MS;
		if (!coalesce) this.#past = [...this.#past, before].slice(-HISTORY_LIMIT);
		this.#future = [];
		this.#lastKey = key;
		this.#lastAt = now;
		this.theme = next;
		this.#saveDraft();
	}

	/** Set a top-level field. */
	set<K extends keyof Theme>(field: K, value: Required<Theme>[K]): void {
		this.update((t) => {
			t[field] = value;
		}, field);
	}

	/** Set one colour of one mode. Ignores anything that isn't `#rrggbb`. */
	setColour(mode: Mode, field: PaletteField, hex: string): void {
		if (!/^#[0-9a-fA-F]{6}$/.test(hex)) return;
		this.update((t) => {
			t.colours[mode][field] = hex.toLowerCase();
		}, `colour:${mode}:${field}`);
	}

	/** Apply a preset. Brand text and logo are kept; everything else comes from the preset. */
	applyPreset(id: PresetId): void {
		this.update((t) => {
			const p = presetTheme(id);
			Object.assign(t, { ...p, headerText: t.headerText, logoAssetId: t.logoAssetId });
		});
	}

	/** Apply a guard suggestion (a diagnostic's pointer and suggested value). */
	applySuggestion(d: ThemeDiagnostic): void {
		if (d.suggestion === null) return;
		const m = /^\/colours\/(light|dark)\/(\w+)$/.exec(d.pointer);
		if (m && typeof d.suggestion === 'string') {
			const hex = d.suggestion.toLowerCase();
			// No coalescing key: a fix is always its own undo step.
			this.update((t) => {
				t.colours[m[1] as Mode][m[2] as PaletteField] = hex;
			});
		} else if (d.pointer === '/baseSize' && typeof d.suggestion === 'number') {
			this.update((t) => {
				t.baseSize = d.suggestion as number;
			});
		}
	}

	undo(): boolean {
		const prev = this.#past.at(-1);
		if (!prev) return false;
		this.#past = this.#past.slice(0, -1);
		this.#future = [...this.#future, clone(this.theme)];
		this.theme = normalise(prev);
		this.#lastKey = null;
		this.#saveDraft();
		return true;
	}

	redo(): boolean {
		const next = this.#future.at(-1);
		if (!next) return false;
		this.#future = this.#future.slice(0, -1);
		this.#past = [...this.#past, clone(this.theme)];
		this.theme = normalise(next);
		this.#lastKey = null;
		this.#saveDraft();
		return true;
	}

	/** The theme as a JSON document, every field explicit. */
	toJson(): string {
		return JSON.stringify(this.theme, null, 2) + '\n';
	}

	/** Replace the theme with imported JSON, if it is valid. Undoable. */
	importJson(text: string): { ok: boolean; problems: ImportProblem[] } {
		const { theme, problems } = parseThemeJson(text);
		if (!theme) return { ok: false, problems };
		this.update((t) => Object.assign(t, normalise(theme)));
		return { ok: true, problems: [] };
	}

	#draftChecked = false;

	/** Load the draft the first time the editor is opened in this page; later calls do nothing. */
	openOnce(): void {
		if (this.#draftChecked) return;
		this.#draftChecked = true;
		this.loadDraft();
	}

	/** Load the local draft, if there is a valid one. Not undoable (it is the starting point). */
	loadDraft(): boolean {
		let text: string | null;
		try {
			text = this.#storage()?.getItem(DRAFT_KEY) ?? null;
		} catch {
			return false;
		}
		if (!text) return false;
		const { theme } = parseThemeJson(text);
		if (!theme) return false;
		this.theme = normalise(theme);
		this.#past = [];
		this.#future = [];
		return true;
	}

	#source: string | null = null;

	/**
	 * Start editing a theme that came from somewhere (a survey's own theme, a library theme).
	 * `source` names where it came from: opening the same source again keeps the edits in
	 * progress. Not undoable (it is the starting point); undoable when `undoable` is set.
	 */
	loadTheme(theme: Theme, source: string, { undoable = false } = {}): boolean {
		if (!undoable && source === this.#source) return false;
		this.#source = source;
		this.#draftChecked = true;
		const { theme: parsed } = parseThemeJson(JSON.stringify(theme));
		if (!parsed) return false;
		if (undoable) {
			this.update((t) => Object.assign(t, normalise(parsed)));
			return true;
		}
		this.theme = normalise(parsed);
		this.#past = [];
		this.#future = [];
		return true;
	}

	/** Start over from the Clean preset and forget the draft. Undoable. */
	reset(): void {
		this.update((t) => Object.assign(t, presetTheme('clean')));
		try {
			this.#storage()?.removeItem(DRAFT_KEY);
		} catch {
			/* storage blocked */
		}
	}

	#saveDraft() {
		try {
			this.#storage()?.setItem(DRAFT_KEY, JSON.stringify(this.theme));
		} catch {
			/* storage blocked or full: the draft lasts for this page only */
		}
	}
}

/** The editor the Appearance view and the shell's undo/redo share. */
export const themeEditor = new ThemeEditor();
