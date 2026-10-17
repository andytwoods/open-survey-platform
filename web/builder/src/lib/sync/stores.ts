/**
 * One SurveyStore per page: each page is its own load (planning/pages-split.md D8), so the
 * undo history is per page. The store registers itself as the page's save guard, so
 * leaving the page waits for its queue (host/links.ts).
 */
import { api } from '../api';
import { registerSaveGuard } from '../host/links';
import { session } from '../host/session.svelte';
import { SurveyStore } from './survey-store.svelte';
import { apiTransport } from './transport';

let current: SurveyStore | null = null;
let offGuard: (() => void) | null = null;

export function storeFor(surveyId: string): SurveyStore {
	// Reuse only a store that loaded: a failed load is retried on the next visit.
	if (current && current.surveyId === surveyId && current.survey) return current;
	offGuard?.();
	const store = new SurveyStore({
		transport: apiTransport(api),
		onUnauthenticated: () => session.unauthenticated()
	});
	store.surveyId = surveyId;
	offGuard = registerSaveGuard({
		unsaved: () => store.unsaved,
		flush: () => store.flushBuffers(),
		settled: () => store.settledOrPaused()
	});
	current = store;
	return store;
}
