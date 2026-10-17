/**
 * The results page's state (task V2): the filters being edited, the filters last applied,
 * the response, and the request in flight. Requests go through a `ResultsSource` (the
 * generated API client in the page, a stub in tests). A newer request supersedes an older
 * one, and the user can cancel a long one: V1 sends no progress events, so the page shows
 * how long it has been waiting instead.
 */
import { api } from '../api';
import { ChartChoices } from './charts.svelte';
import type { MenuChoice } from './charts/types';
import type { ExportPage } from './export/run';
import { ExportSettings } from './export/settings.svelte';
import { ResultsTheme, type ThemeLibraryList } from './results-theme.svelte';
import {
	cardRequests,
	choiceVariables,
	cloneFilters,
	defaultFilters,
	type CardBins,
	describeFilters,
	filterProblems,
	sameFilters,
	toQuery,
	toTextParams,
	type ChoiceVariable,
	type ResultsFilters
} from './model';
import { chartNotices, inOrder, moved, type ChartNotice, type PageState } from './layouts';
import { apiLayouts, type LayoutSource } from './layouts-api';
import { livePolicy } from './live';
import { LivePoller, type Watermark } from './live.svelte';
import { presentation } from './presentation.svelte';
import type {
	Card,
	ResultsExportRecord,
	ResultsExportRequest,
	ResultsQuery,
	ResultsResponse,
	TextPage
} from './types';

export type Fetched<T> = { ok: true; data: T } | { ok: false; status: number; message: string; aborted?: boolean };

export interface ResultsSource {
	query(body: ResultsQuery, signal: AbortSignal): Promise<Fetched<ResultsResponse>>;
	/** The cheap "did the responses change?" poll (task LV3); without it the page has no Live toggle. */
	watermark?(versions: number[] | undefined, signal: AbortSignal): Promise<Fetched<Watermark>>;
	text(
		question: string,
		params: ReturnType<typeof toTextParams> & { cursor?: string; limit?: number },
		signal: AbortSignal
	): Promise<Fetched<TextPage>>;
	/** Writes the `results.export` audit row a figure export needs (task V4). */
	recordExport(body: ResultsExportRequest): Promise<Fetched<ResultsExportRecord>>;
	/** The platform's name and version, for export manifests. */
	platform?(): Promise<{ name: string; version: string }>;
	/** Saved layouts (task V5b); without it the page has no layout bar. */
	layouts?: LayoutSource;
	/** The lab's theme library (task V6); without it the theme picker offers no lab themes. */
	themes?(): Promise<Fetched<ThemeLibraryList>>;
}

function failed(status: number, error: unknown, fallback: string): Fetched<never> {
	const m = (error as { message?: unknown } | undefined)?.message;
	return { ok: false, status, message: typeof m === 'string' && m ? m : fallback };
}

function thrown(e: unknown, signal: AbortSignal): Fetched<never> {
	if (signal.aborted) return { ok: false, status: 0, message: 'Cancelled.', aborted: true };
	return { ok: false, status: 0, message: (e as Error)?.message || 'Network error.' };
}

/** The real API (survey.export: owner and editor). */
export function apiSource(surveyId: string): ResultsSource {
	return {
		async query(body, signal) {
			try {
				const { data, error, response } = await api.POST('/api/surveys/{survey_id}/results/query', {
					params: { path: { survey_id: surveyId } },
					body,
					signal
				});
				return data ? { ok: true, data } : failed(response.status, error, 'The results could not be loaded.');
			} catch (e) {
				return thrown(e, signal);
			}
		},
		async watermark(versions, signal) {
			try {
				const { data, error, response } = await api.GET('/api/surveys/{survey_id}/results/watermark', {
					params: { path: { survey_id: surveyId }, query: versions?.length ? { versions } : {} },
					signal
				});
				return data ? { ok: true, data } : failed(response.status, error, 'The responses could not be checked.');
			} catch (e) {
				return thrown(e, signal);
			}
		},
		async text(question, params, signal) {
			try {
				const { data, error, response } = await api.GET('/api/surveys/{survey_id}/results/text/{question}', {
					params: { path: { survey_id: surveyId, question }, query: params },
					signal
				});
				return data ? { ok: true, data } : failed(response.status, error, 'The answers could not be loaded.');
			} catch (e) {
				return thrown(e, signal);
			}
		},
		async recordExport(body) {
			const signal = new AbortController().signal;
			try {
				const { data, error, response } = await api.POST('/api/surveys/{survey_id}/results/export', {
					params: { path: { survey_id: surveyId } },
					body
				});
				return data ? { ok: true, data } : failed(response.status, error, 'The export could not be recorded.');
			} catch (e) {
				return thrown(e, signal);
			}
		},
		async platform() {
			try {
				const { data } = await api.GET('/api/version');
				if (data) return { name: data.name, version: data.version };
			} catch {
				/* fall through */
			}
			return { name: 'Open Survey Platform', version: 'unknown' };
		},
		layouts: apiLayouts(surveyId),
		async themes() {
			const signal = new AbortController().signal;
			try {
				const { data, error, response } = await api.GET('/api/themes');
				if (data) {
					return {
						ok: true,
						data: { themes: data.themes as unknown as ThemeLibraryList['themes'], defaultThemeId: data.defaultThemeId ?? null }
					};
				}
				return failed(response.status, error, 'The lab theme library could not be listed.');
			} catch (e) {
				return thrown(e, signal);
			}
		}
	};
}

/** After this long the waiting state also says how long it has been and offers Cancel. */
export const SLOW_AFTER_MS = 1000;
/** How long a card that changed in a live refresh keeps its outline pulse. */
export const PULSE_MS = 1500;

export class ResultsController {
	readonly source: ResultsSource;
	readonly charts = new ChartChoices();
	readonly exports = new ExportSettings();
	/** The page's own theme (task V6): the choice, the survey's theme and the lab library. */
	readonly theme = new ResultsTheme();
	draft = $state<ResultsFilters>(defaultFilters(0));
	applied = $state<ResultsFilters>(defaultFilters(0));
	response = $state<ResultsResponse | null>(null);
	loading = $state(false);
	/** Seconds since the request in flight started (ticks while loading). */
	elapsed = $state(0);
	error = $state<{ status: number; message: string } | null>(null);
	/** The choice variables of the latest response (the filter and split options). */
	choices = $state<ChoiceVariable[]>([]);
	/** Display order (V5b): questions listed here first, the rest in survey order. */
	order = $state<string[]>([]);
	/** Show note items (a saved layout's "showNotes"). */
	showNotes = $state(false);
	/** Live results (task LV3), when the source can poll the watermark. */
	readonly live: LivePoller | null;
	/** The page's view of "busy" (recent input, an open menu or dialog): badge instead of a refresh. */
	busyCheck: () => boolean = () => false;
	/** The request in flight is an automatic refresh: no "Computing results…" unless it is slow. */
	quiet = $state(false);
	/** The last refresh the poller made: when, the count, which cards' numbers changed. */
	liveUpdate = $state<{ seq: number; at: number; responses: number; changed: string[] } | null>(null);
	/** Cards whose numbers just changed in a live refresh (a short outline pulse). */
	pulsing = $state<string[]>([]);
	/** When the results on screen were received (the presentation footer's "updated hh:mm", LV4). */
	receivedAt = $state<number | null>(null);
	readonly latest: number;
	#abort: AbortController | null = null;
	#seq = 0;
	#timer: ReturnType<typeof setInterval> | null = null;
	#pulseTimer: ReturnType<typeof setTimeout> | null = null;

	constructor(source: ResultsSource, publishedVersions: number, opts: { minRefreshMs?: number } = {}) {
		this.source = source;
		this.latest = publishedVersions;
		this.draft = defaultFilters(publishedVersions);
		this.applied = cloneFilters(this.draft);
		const poll = source.watermark?.bind(source);
		this.live = poll
			? new LivePoller(
					{
						poll: (signal) => poll(this.applied.versions.length ? [...this.applied.versions].sort((a, b) => a - b) : undefined, signal),
						refresh: (live) => this.load({ live }),
						watermark: () => this.response?.watermark ?? null,
						busy: () => this.loading || this.dirty || this.busyCheck(),
						policy: () => livePolicy({ presenting: presentation.active, refresh: presentation.refresh })
					},
					opts
				)
			: null;
	}

	/** The response's cards in display order (notes only when "show notes" is on). */
	get cards(): Card[] {
		const cards = (this.response?.cards ?? []).filter((c) => c.type !== 'note' || this.showNotes);
		return inOrder(cards, this.order);
	}

	/** The response's questions in survey order (what a saved layout lists). */
	get questions(): string[] {
		return (this.response?.cards ?? []).map((c) => c.question);
	}

	/** Cards whose chosen chart (from a layout) does not suit them, and what they show instead. */
	get chartNotices(): ChartNotice[] {
		return chartNotices(this.response?.cards ?? [], this.charts.all);
	}

	/** Move a card to position `to` of the display order (drag or keyboard). */
	move(question: string, to: number) {
		this.order = moved(
			this.cards.map((c) => c.question),
			question,
			to
		);
	}

	/** What a saved layout would hold now (the applied filters, not the draft). */
	pageState(): PageState {
		return {
			filters: cloneFilters(this.applied),
			cards: this.charts.snapshot(),
			captions: { ...this.exports.captions },
			order: [...this.order],
			showNotes: this.showNotes,
			theme: { ...this.theme.choice },
			exports: this.exports.snapshot(),
			live: this.live?.on ?? false
		};
	}

	/** Open a layout's state and fetch. Bins need the card list, so they may re-ask once. */
	async restore(state: PageState): Promise<boolean> {
		this.draft = cloneFilters(state.filters);
		this.applied = cloneFilters(state.filters);
		this.charts.restore(state.cards);
		this.exports.restoreCaptions(state.captions);
		this.exports.restore(state.exports);
		this.theme.choose({ ...state.theme });
		this.order = [...state.order];
		this.showNotes = state.showNotes;
		this.live?.set(state.live);
		const ok = await this.load({ allCards: true });
		if (ok && this.query().cards) return this.load();
		return ok;
	}

	get problems() {
		return filterProblems(this.draft);
	}

	/** The applied filters in words (the line above the cards and every export caption). */
	get activeFilters(): string[] {
		return describeFilters(this.applied, {
			choices: this.choices,
			versionsUsed: this.response?.versionsUsed,
			splitLabel: this.response?.split?.label
		});
	}

	/** What an export needs: the response, its query, the filters in words (V4), the theme (V6). */
	exportPage(): ExportPage | null {
		if (!this.response) return null;
		// A plain copy: figures are built from it and Vega clones specs (proxies cannot be cloned).
		const response = $state.snapshot(this.response) as ResultsResponse;
		const source = this.source;
		const query = this.query();
		const shown = this.cards.filter((c) => c.type !== 'note' && !this.charts.hidden(c.question)).map((c) => c.question);
		return {
			response,
			query,
			filters: this.activeFilters,
			charts: this.charts,
			// Display order (V5b), hidden cards and notes left out; plain copies from the snapshot.
			cards: shown.map((q) => response.cards.find((c) => c.question === q)!),
			theme: { tokens: this.theme.exportTokens, description: this.theme.exportDescription },
			async record(body) {
				const r = await source.recordExport({ query, ...body } as ResultsExportRequest);
				if (r.ok) return null;
				return r.status === 403 ? 'You need owner or editor access to this survey to export its results.' : r.message;
			},
			platform: () => source.platform?.() ?? Promise.resolve({ name: 'Open Survey Platform', version: 'unknown' })
		};
	}

	/** The draft differs from what the cards show. */
	get dirty(): boolean {
		return !sameFilters(this.draft, this.applied);
	}

	/** The query the applied filters and chart choices make. */
	query(): ResultsQuery {
		return toQuery(this.applied, this.response ? cardRequests(this.response.cards, this.charts.bins as Record<string, CardBins>) : undefined);
	}

	/** Apply the draft filters and fetch. False when the draft has a problem. */
	apply(): Promise<boolean> {
		if (this.problems.length) return Promise.resolve(false);
		this.applied = cloneFilters(this.draft);
		return this.load();
	}

	/** Back to the defaults (latest version, complete responses) and fetch. */
	reset(publishedVersions: number): Promise<boolean> {
		this.draft = defaultFilters(publishedVersions);
		return this.apply();
	}

	/** Choose a chart: drawn from the same numbers, so nothing is re-asked. */
	chooseChart(question: string, chart: MenuChoice) {
		this.charts.choose(question, chart);
	}

	/** Choose a date card's period: the server computes it, so this re-asks. */
	chooseUnit(question: string, unit: string) {
		const before = this.query();
		this.charts.setUnit(question, unit);
		if (JSON.stringify(this.query()) !== JSON.stringify(before)) void this.load();
	}

	/**
	 * Fetch. `allCards`: ask without a card list (every question), e.g. after the versions
	 * change. `live`: an automatic refresh by the poller (LV-D7: the server audits it as
	 * `results.live`; the page notes which cards changed and stays quiet unless it is slow).
	 */
	async load(opts: { allCards?: boolean; live?: boolean } = {}): Promise<boolean> {
		this.#abort?.abort();
		const abort = new AbortController();
		this.#abort = abort;
		const seq = ++this.#seq;
		this.loading = true;
		this.quiet = !!opts.live;
		this.error = null;
		this.#startClock();
		const body = this.query();
		if (opts.allCards) delete body.cards;
		if (opts.live) body.live = true;
		const before = opts.live ? this.response : null;
		const r = await this.source.query(body, abort.signal);
		if (seq !== this.#seq) return false;
		this.loading = false;
		this.quiet = false;
		this.#stopClock();
		this.#abort = null;
		if (!r.ok) {
			if (!r.aborted) this.error = { status: r.status, message: r.message };
			return false;
		}
		this.response = r.data;
		this.receivedAt = Date.now();
		const choices = choiceVariables(r.data.cards);
		if (choices.length || !this.choices.length) this.choices = choices;
		if (opts.live) this.#noteLiveUpdate(before, r.data);
		return true;
	}

	/** Which cards' numbers changed in a live refresh; they pulse briefly (not under reduced motion). */
	#noteLiveUpdate(before: ResultsResponse | null, after: ResultsResponse) {
		const old: Record<string, string> = {};
		for (const c of before?.cards ?? []) old[c.question] = JSON.stringify($state.snapshot(c));
		const changed = after.cards.filter((c) => old[c.question] !== JSON.stringify(c)).map((c) => c.question);
		this.liveUpdate = { seq: (this.liveUpdate?.seq ?? 0) + 1, at: Date.now(), responses: after.responses, changed };
		this.pulsing = changed;
		if (this.#pulseTimer) clearTimeout(this.#pulseTimer);
		this.#pulseTimer = setTimeout(() => {
			this.#pulseTimer = null;
			this.pulsing = [];
		}, PULSE_MS);
	}

	/** Stop waiting for the request in flight (the cards keep the last results). */
	cancel() {
		if (!this.#abort) return;
		this.#abort.abort();
		this.#abort = null;
		this.#seq++;
		this.loading = false;
		this.#stopClock();
	}

	dispose() {
		this.cancel();
		this.live?.dispose();
		if (this.#pulseTimer) clearTimeout(this.#pulseTimer);
		this.#pulseTimer = null;
	}

	#startClock() {
		this.#stopClock();
		const t0 = Date.now();
		this.elapsed = 0;
		this.#timer = setInterval(() => (this.elapsed = Math.floor((Date.now() - t0) / 1000)), 250);
	}

	#stopClock() {
		if (this.#timer) clearInterval(this.#timer);
		this.#timer = null;
	}
}
