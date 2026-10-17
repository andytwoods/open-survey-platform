/**
 * Saved layouts on the Results page (task V5b): the survey's layouts, which one is open,
 * and what it looked like when opened or saved (for the unsaved-changes indicator). Calls
 * go through a `LayoutSource` (the generated API client in the page, a stub in tests).
 * Owners and editors only (survey.export); viewers cannot reach the page.
 */
import { emptyState, fromSettings, layoutError, sameLayout, toSettings, type PageState } from './layouts';
import type { ErrorBody, LayoutSource } from './layouts-api';
import type { ResultsController } from './results.svelte';
import type { LayoutSettings, ResultsLayout, ResultsLayoutList } from './types';

export type { LayoutSource } from './layouts-api';

export const MAX_NAME = 200;

/** A layout name's problem, or null. */
export function nameProblem(name: string): string | null {
	const n = name.trim();
	if (!n) return 'Enter a name for the layout.';
	if (n.length > MAX_NAME) return `Use at most ${MAX_NAME} characters.`;
	return null;
}

export class LayoutsController {
	readonly source: LayoutSource;
	readonly results: ResultsController;
	layouts = $state<ResultsLayout[]>([]);
	defaultId = $state<string | null>(null);
	/** The open layout (null: the page's defaults). */
	currentId = $state<string | null>(null);
	busy = $state(false);
	/** The last failure, in words (role="alert"). */
	error = $state<string | null>(null);
	/** The last success, in words (role="status"). */
	status = $state('');
	/** The state the open layout (or the defaults) gave, for the unsaved-changes indicator. */
	#baseline = $state<PageState>(emptyState(0));

	constructor(source: LayoutSource, results: ResultsController) {
		this.source = source;
		this.results = results;
		this.#baseline = emptyState(results.latest);
	}

	get current(): ResultsLayout | null {
		return this.layouts.find((l) => l.id === this.currentId) ?? null;
	}

	/** The page differs from the open layout (or, with none open, from the defaults). */
	get dirty(): boolean {
		return !sameLayout(this.results.pageState(), this.#baseline, this.results.latest, this.results.questions);
	}

	#setList(list: ResultsLayoutList) {
		this.layouts = list.layouts;
		this.defaultId = list.defaultLayoutId;
		if (this.currentId && !list.layouts.some((l) => l.id === this.currentId)) this.currentId = null;
	}

	async #refresh() {
		const r = await this.source.list();
		if (r.ok) this.#setList(r.data);
	}

	#fail(status: number, body: ErrorBody | undefined, ctx: { name?: string; action: string }) {
		this.error = layoutError(status, body, ctx);
		this.status = '';
		if (status === 404) void this.#refresh();
	}

	#ok(message: string) {
		this.error = null;
		this.status = message;
	}

	/**
	 * List the layouts and open `preferred` (a `?layout=` id from a shared link, task V6) or
	 * the default. False when no layout was opened (load defaults).
	 */
	async init(preferred: string | null = null): Promise<boolean> {
		const r = await this.source.list();
		if (!r.ok) {
			this.#fail(r.status, r.body, { action: 'loaded' });
			return false;
		}
		this.#setList(r.data);
		const def = r.data.layouts.find((l) => l.id === preferred) ?? r.data.layouts.find((l) => l.id === r.data.defaultLayoutId);
		if (!def) return false;
		await this.open(def.id);
		return true;
	}

	/** Open a layout (null: the page's defaults) and fetch its results. */
	async open(id: string | null): Promise<void> {
		const layout = id ? this.layouts.find((l) => l.id === id) : null;
		if (id && !layout) return;
		const state = layout ? fromSettings(layout.settings, this.results.latest) : emptyState(this.results.latest);
		this.currentId = layout?.id ?? null;
		this.#baseline = structuredClone(state);
		this.error = null;
		this.status = layout ? `Opened “${layout.name}”.` : 'Showing the default view.';
		await this.results.restore(state);
	}

	#settings(): LayoutSettings {
		return toSettings(this.results.pageState(), this.results.latest, this.results.questions);
	}

	/** Save the page into the open layout. */
	async save(): Promise<boolean> {
		const cur = this.current;
		if (!cur || this.busy) return false;
		this.busy = true;
		try {
			const r = await this.source.update(cur.id, { settings: this.#settings() });
			if (!r.ok) {
				this.#fail(r.status, r.body, { action: 'saved' });
				return false;
			}
			this.layouts = this.layouts.map((l) => (l.id === r.data.id ? r.data : l));
			this.#baseline = fromSettings(r.data.settings, this.results.latest);
			this.#ok(`Saved “${r.data.name}”.`);
			return true;
		} finally {
			this.busy = false;
		}
	}

	/** Save the page as a new layout (and open it). */
	async saveAs(name: string, makeDefault: boolean): Promise<boolean> {
		const n = name.trim();
		if (this.busy || nameProblem(n)) return false;
		this.busy = true;
		try {
			const r = await this.source.create({ name: n, settings: this.#settings(), isDefault: makeDefault });
			if (!r.ok) {
				this.#fail(r.status, r.body, { name: n, action: 'saved' });
				return false;
			}
			await this.#refresh();
			if (!this.layouts.some((l) => l.id === r.data.id)) this.layouts = [...this.layouts, r.data];
			this.currentId = r.data.id;
			this.#baseline = fromSettings(r.data.settings, this.results.latest);
			this.#ok(`Saved as “${r.data.name}”${makeDefault ? ', the default layout' : ''}.`);
			return true;
		} finally {
			this.busy = false;
		}
	}

	/** Rename the open layout. */
	async rename(name: string): Promise<boolean> {
		const cur = this.current;
		const n = name.trim();
		if (!cur || this.busy || nameProblem(n)) return false;
		this.busy = true;
		try {
			const r = await this.source.update(cur.id, { name: n });
			if (!r.ok) {
				this.#fail(r.status, r.body, { name: n, action: 'renamed' });
				return false;
			}
			await this.#refresh();
			this.#ok(`Renamed to “${r.data.name}”.`);
			return true;
		} finally {
			this.busy = false;
		}
	}

	/** Delete the open layout. The page keeps showing its settings, now unsaved. */
	async remove(): Promise<boolean> {
		const cur = this.current;
		if (!cur || this.busy) return false;
		this.busy = true;
		try {
			const r = await this.source.remove(cur.id);
			if (!r.ok) {
				this.#fail(r.status, r.body, { action: 'deleted' });
				return false;
			}
			this.layouts = this.layouts.filter((l) => l.id !== cur.id);
			if (this.defaultId === cur.id) this.defaultId = null;
			this.currentId = null;
			this.#baseline = emptyState(this.results.latest);
			await this.#refresh();
			this.#ok(`Deleted “${cur.name}”.`);
			return true;
		} finally {
			this.busy = false;
		}
	}

	/** Make the open layout the survey's default (or, with `clear`, have no default). */
	async setDefault(clear = false): Promise<boolean> {
		const cur = this.current;
		if (this.busy || (!cur && !clear)) return false;
		this.busy = true;
		try {
			const r = await this.source.setDefault(clear ? null : cur!.id);
			if (!r.ok) {
				this.#fail(r.status, r.body, { action: 'made the default' });
				return false;
			}
			this.#setList(r.data);
			this.#ok(clear ? 'No layout opens by default now.' : `“${cur!.name}” now opens by default.`);
			return true;
		} finally {
			this.busy = false;
		}
	}
}
