/**
 * How the survey store talks to the server (task CE5, planning/client-edits.md §3). The
 * builder applies its ops in the browser (@osp/ops), so the server is asked for two things
 * only: the draft (`load`) and to store a new one (`saveDraft`: a JSON Patch against the
 * revision it was made from, plus the op names for the audit log). `SurveyTransport` is an
 * interface so unit tests, the dev pages and the serverless demo can stand in for the
 * server (`memoryTransport` in memory-transport.ts); `apiTransport` is the real one over
 * the generated client. Every call resolves to a tagged result: HTTP and network failures
 * never throw.
 */
import type { ApiClient, components } from '@osp/api-client';
import type { PatchOperation } from './json-patch';

export type Diagnostic = components['schemas']['Diagnostic'];
export type SurveyDoc = Record<string, unknown>;

export interface Invocation {
	op: string;
	params?: Record<string, unknown>;
}

/** What a local edit (or undo/redo) gives its caller: the store's view right after it. */
export interface EditResult {
	/** The store's revision after the edit (the server's, plus edits not yet saved). */
	revision: number;
	/** RFC 6902, from the survey before the edit to after it. */
	patch: PatchOperation[];
	diagnostics: Diagnostic[];
	/** The transaction the edit is saved as; null when it changed nothing. */
	transactionId: string | null;
}

export interface SaveRequest {
	/** The server revision `patch` was made against. */
	baseRevision: number;
	/** RFC 6902, from that revision's document to the new one. */
	patch: PatchOperation[];
	/** The ops that made the patch (for the audit log; the server doesn't re-run them). */
	ops: Invocation[];
	/** Client-chosen, `[A-Za-z0-9_-]{1,36}`: a retry with the same id is not applied twice. */
	transactionId: string;
}

export interface SaveResult {
	revision: number;
	/** The server validator's diagnostics for the saved document (authoritative). */
	diagnostics: Diagnostic[];
	transactionId: string | null;
	/** A retry of a save that had landed: nothing was applied again. */
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
	/** The lab the survey belongs to (for lab-level reads such as the theme library). */
	tenantId?: string;
}

export type Result<T> =
	| { kind: 'ok'; data: T }
	/** 409: our baseRevision is stale. */
	| { kind: 'conflict'; currentRevision: number | null; message: string }
	/** 422: the save was refused; nothing was stored. */
	| { kind: 'rejected'; message: string; diagnostics: Diagnostic[]; failedIndex: number | null }
	/** Network failure or a gateway/unavailable status: worth retrying. */
	| { kind: 'offline'; message: string }
	/** Anything else (401, 403, 404, 500 …): not retried. */
	| { kind: 'error'; status: number; code: string; message: string };

/**
 * The server, as the survey store sees it. An implementation keeps `{survey, revision}`:
 * `load` returns it; `saveDraft` answers `conflict` unless `baseRevision` is the current
 * revision, `rejected` if the patch doesn't apply or the result is refused (nothing kept),
 * else stores the result, bumps the revision when the document changed, and answers
 * `replayed` for a transaction id it already stored after `baseRevision`.
 */
export interface SurveyTransport {
	load(surveyId: string): Promise<Result<LoadedSurvey>>;
	saveDraft(surveyId: string, body: SaveRequest): Promise<Result<SaveResult>>;
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
			const { id, title, revision, survey, diagnostics, publishedVersions, tenantId } = r.data;
			return { kind: 'ok', data: { id, title, revision, survey, diagnostics, publishedVersions, tenantId } };
		},
		saveDraft(surveyId, body) {
			return call<SaveResult>(() =>
				api.PUT('/api/surveys/{survey_id}/draft', {
					params: { path: { survey_id: surveyId } },
					body: {
						baseRevision: body.baseRevision,
						patch: body.patch as unknown as Record<string, unknown>[],
						ops: body.ops.map((o) => ({ op: o.op, params: o.params ?? {} })),
						transactionId: body.transactionId
					}
				})
			);
		}
	};
}
