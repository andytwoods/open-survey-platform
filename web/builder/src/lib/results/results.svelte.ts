/**
 * The results page's state (task V2): the filters being edited, the filters last applied,
 * the response, and the request in flight. Requests go through a `ResultsSource` (the
 * generated API client in the page, a stub in tests). A newer request supersedes an older
 * one, and the user can cancel a long one: V1 sends no progress events, so the page shows
 * how long it has been waiting instead.
 */
import { api } from '../api';
import { ChartChoices } from './charts.svelte';
import {
	cardRequests,
	choiceVariables,
	cloneFilters,
	defaultFilters,
	filterProblems,
	sameFilters,
	toQuery,
	toTextParams,
	type ChoiceVariable,
	type ResultsFilters
} from './model';
import type { ResultsQuery, ResultsResponse, TextPage } from './types';

export type Fetched<T> = { ok: true; data: T } | { ok: false; status: number; message: string; aborted?: boolean };

export interface ResultsSource {
	query(body: ResultsQuery, signal: AbortSignal): Promise<Fetched<ResultsResponse>>;
	text(
		question: string,
		params: ReturnType<typeof toTextParams> & { cursor?: string; limit?: number },
		signal: AbortSignal
	): Promise<Fetched<TextPage>>;
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
		}
	};
}

/** After this long the waiting state also says how long it has been and offers Cancel. */
export const SLOW_AFTER_MS = 1000;

export class ResultsController {
	readonly source: ResultsSource;
	readonly charts = new ChartChoices();
	draft = $state<ResultsFilters>(defaultFilters(0));
	applied = $state<ResultsFilters>(defaultFilters(0));
	response = $state<ResultsResponse | null>(null);
	loading = $state(false);
	/** Seconds since the request in flight started (ticks while loading). */
	elapsed = $state(0);
	error = $state<{ status: number; message: string } | null>(null);
	/** The choice variables of the latest response (the filter and split options). */
	choices = $state<ChoiceVariable[]>([]);
	#abort: AbortController | null = null;
	#seq = 0;
	#timer: ReturnType<typeof setInterval> | null = null;

	constructor(source: ResultsSource, publishedVersions: number) {
		this.source = source;
		this.draft = defaultFilters(publishedVersions);
		this.applied = cloneFilters(this.draft);
	}

	get problems() {
		return filterProblems(this.draft);
	}

	/** The draft differs from what the cards show. */
	get dirty(): boolean {
		return !sameFilters(this.draft, this.applied);
	}

	/** The query the applied filters and chart choices make. */
	query(): ResultsQuery {
		return toQuery(this.applied, this.response ? cardRequests(this.response.cards, this.charts.all) : undefined);
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

	/** Choose a chart; a date card's period changes what the server computes. */
	chooseChart(question: string, chart: string) {
		const before = this.query();
		this.charts.choose(question, chart);
		if (JSON.stringify(this.query()) !== JSON.stringify(before)) void this.load();
	}

	async load(): Promise<boolean> {
		this.#abort?.abort();
		const abort = new AbortController();
		this.#abort = abort;
		const seq = ++this.#seq;
		this.loading = true;
		this.error = null;
		this.#startClock();
		const r = await this.source.query(this.query(), abort.signal);
		if (seq !== this.#seq) return false;
		this.loading = false;
		this.#stopClock();
		this.#abort = null;
		if (!r.ok) {
			if (!r.aborted) this.error = { status: r.status, message: r.message };
			return false;
		}
		this.response = r.data;
		const choices = choiceVariables(r.data.cards);
		if (choices.length || !this.choices.length) this.choices = choices;
		return true;
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
