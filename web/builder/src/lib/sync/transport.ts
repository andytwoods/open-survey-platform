/**
 * How the survey store talks to the server. `SurveyTransport` is an interface so unit
 * tests can script the server; `apiTransport` is the real one over the generated client.
 * Every call resolves to a tagged result: HTTP and network failures never throw.
 */
import type { ApiClient, components } from '@osp/api-client';
import type { PatchOperation } from './json-patch';

export type Diagnostic = components['schemas']['Diagnostic'];
export type SurveyDoc = Record<string, unknown>;

export interface Invocation {
	op: string;
	params?: Record<string, unknown>;
}

export interface EditResult {
	revision: number;
	patch: PatchOperation[];
	diagnostics: Diagnostic[];
	transactionId: string | null;
	replayed?: boolean;
}

export interface LoadedSurvey {
	id: string;
	title: string;
	revision: number;
	survey: SurveyDoc;
	/** The validator's diagnostics for the draft as loaded (optional for scripted servers). */
	diagnostics?: Diagnostic[];
	/** How many versions have been published (0 or absent: never). */
	publishedVersions?: number;
}

export type Result<T> =
	| { kind: 'ok'; data: T }
	/** 409: our baseRevision is stale. */
	| { kind: 'conflict'; currentRevision: number | null; message: string }
	/** 422: the edit was rejected; nothing was applied. */
	| { kind: 'rejected'; message: string; diagnostics: Diagnostic[]; failedIndex: number | null }
	/** Network failure or a gateway/unavailable status: worth retrying. */
	| { kind: 'offline'; message: string }
	/** Anything else (401, 403, 404, 500 …): not retried. */
	| { kind: 'error'; status: number; code: string; message: string };

export interface SurveyTransport {
	load(surveyId: string): Promise<Result<LoadedSurvey>>;
	applyOps(
		surveyId: string,
		body: { ops: Invocation[]; baseRevision: number; transactionId: string }
	): Promise<Result<EditResult>>;
	undo(surveyId: string, body: { transactionId: string; baseRevision: number }): Promise<Result<EditResult>>;
	redo(surveyId: string, body: { transactionId: string; baseRevision: number }): Promise<Result<EditResult>>;
}

const RETRYABLE = new Set([502, 503, 504]);

interface ErrorBodyLike {
	code?: unknown;
	message?: unknown;
	currentRevision?: unknown;
	diagnostics?: unknown;
	failedIndex?: unknown;
	detail?: unknown;
}

/** Map an HTTP failure body to a Result. Exported for tests. */
export function failure(status: number, body: unknown): Result<never> {
	const b: ErrorBodyLike = typeof body === 'object' && body !== null ? (body as ErrorBodyLike) : {};
	const message = typeof b.message === 'string' ? b.message : `Request failed (${status}).`;
	if (status === 409) {
		return {
			kind: 'conflict',
			currentRevision: typeof b.currentRevision === 'number' ? b.currentRevision : null,
			message
		};
	}
	if (status === 422) {
		const diagnostics = Array.isArray(b.diagnostics) ? (b.diagnostics as Diagnostic[]) : [];
		// FastAPI's own request validation answers 422 with `detail`, not diagnostics.
		if (!diagnostics.length && Array.isArray(b.detail)) {
			for (const d of b.detail as { msg?: unknown; loc?: unknown }[]) {
				diagnostics.push({
					code: 'request.invalid',
					message: String(d?.msg ?? 'Invalid request'),
					pointer: Array.isArray(d?.loc) ? '/' + d.loc.join('/') : '',
					severity: 'error'
				});
			}
		}
		return {
			kind: 'rejected',
			message,
			diagnostics,
			failedIndex: typeof b.failedIndex === 'number' ? b.failedIndex : null
		};
	}
	if (RETRYABLE.has(status)) return { kind: 'offline', message };
	return { kind: 'error', status, code: typeof b.code === 'string' ? b.code : 'error', message };
}

async function call<T>(fn: () => Promise<{ data?: unknown; error?: unknown; response: Response }>): Promise<Result<T>> {
	try {
		const { data, error, response } = await fn();
		if (response.ok && data !== undefined) return { kind: 'ok', data: data as T };
		return failure(response.status, error);
	} catch (e) {
		return { kind: 'offline', message: (e as Error)?.message || 'Network error' };
	}
}

export function apiTransport(api: ApiClient): SurveyTransport {
	return {
		async load(surveyId) {
			const r = await call<LoadedSurvey>(() =>
				api.GET('/api/surveys/{survey_id}', { params: { path: { survey_id: surveyId } } })
			);
			if (r.kind !== 'ok') return r;
			const { id, title, revision, survey, diagnostics, publishedVersions } = r.data;
			return { kind: 'ok', data: { id, title, revision, survey, diagnostics, publishedVersions } };
		},
		applyOps(surveyId, body) {
			return call<EditResult>(() =>
				api.POST('/api/surveys/{survey_id}/ops', {
					params: { path: { survey_id: surveyId } },
					body: { ...body, ops: body.ops.map((o) => ({ op: o.op, params: o.params ?? {} })) }
				})
			);
		},
		undo(surveyId, body) {
			return call<EditResult>(() =>
				api.POST('/api/surveys/{survey_id}/undo', { params: { path: { survey_id: surveyId } }, body })
			);
		},
		redo(surveyId, body) {
			return call<EditResult>(() =>
				api.POST('/api/surveys/{survey_id}/redo', { params: { path: { survey_id: surveyId } }, body })
			);
		}
	};
}
