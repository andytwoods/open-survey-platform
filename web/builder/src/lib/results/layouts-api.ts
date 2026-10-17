/**
 * Where saved results layouts come from (task V5b): V5a's API through the generated client,
 * or a stub in tests. Kept apart from the page state so `results.svelte.ts` can offer it.
 */
import { api } from '../api';
import type { LayoutSettings, ResultsLayout, ResultsLayoutList } from './types';

export type ErrorBody = { message?: unknown; diagnostics?: unknown; detail?: unknown };
export type LayoutFetched<T> = { ok: true; data: T } | { ok: false; status: number; body?: ErrorBody };

export interface LayoutSource {
	list(): Promise<LayoutFetched<ResultsLayoutList>>;
	create(body: { name: string; settings: LayoutSettings; isDefault: boolean }): Promise<LayoutFetched<ResultsLayout>>;
	update(id: string, body: { name?: string; settings?: LayoutSettings }): Promise<LayoutFetched<ResultsLayout>>;
	remove(id: string): Promise<LayoutFetched<null>>;
	setDefault(id: string | null): Promise<LayoutFetched<ResultsLayoutList>>;
}

async function call<T>(
	run: () => Promise<{ data?: T; error?: unknown; response: Response }>,
	empty?: T
): Promise<LayoutFetched<T>> {
	try {
		const { data, error, response } = await run();
		if (response.ok) return { ok: true, data: (data ?? empty) as T };
		return { ok: false, status: response.status, body: (error ?? undefined) as ErrorBody | undefined };
	} catch (e) {
		return { ok: false, status: 0, body: { message: (e as Error)?.message || 'Network error.' } };
	}
}

/** The real API (`/api/surveys/{id}/results/layouts`, V5a; survey.export). */
export function apiLayouts(surveyId: string): LayoutSource {
	const path = { survey_id: surveyId };
	return {
		list: () => call(() => api.GET('/api/surveys/{survey_id}/results/layouts', { params: { path } })),
		create: (body) => call(() => api.POST('/api/surveys/{survey_id}/results/layouts', { params: { path }, body })),
		update: (id, body) =>
			call(() =>
				api.PATCH('/api/surveys/{survey_id}/results/layouts/{layout_id}', {
					params: { path: { ...path, layout_id: id } },
					body
				})
			),
		remove: (id) =>
			call(
				() =>
					api.DELETE('/api/surveys/{survey_id}/results/layouts/{layout_id}', {
						params: { path: { ...path, layout_id: id } }
					}),
				null
			),
		setDefault: (id) =>
			call(() => api.PUT('/api/surveys/{survey_id}/results/layouts/default', { params: { path }, body: { layoutId: id } }))
	};
}
