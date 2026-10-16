/**
 * One SurveyStore per open survey, kept across the editor ↔ appearance routes so the
 * undo history and pending edits survive switching views. Opening another survey
 * replaces it.
 */
import { api } from '../api';
import { auth } from '../auth.svelte';
import { SurveyStore } from './survey-store.svelte';
import { apiTransport } from './transport';

let current: SurveyStore | null = null;

export function storeFor(surveyId: string): SurveyStore {
	// Reuse only a store that loaded: a failed load is retried on the next visit.
	if (current && current.surveyId === surveyId && current.survey) return current;
	current = new SurveyStore({ transport: apiTransport(api), onUnauthenticated: () => auth.expired() });
	current.surveyId = surveyId;
	return current;
}
