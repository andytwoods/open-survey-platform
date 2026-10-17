/**
 * The participant endpoints (runtime-design §5), typed by the generated client
 * (`@osp/api-client`, types only: a hand-rolled fetch keeps `keepalive`, timeouts and the
 * bundle small). The resume token always travels as `Authorization: Bearer`, never in a URL.
 */
import type { components } from '@osp/api-client';
import type { ResponseRecord, Snapshot } from '@osp/engine';

type S = components['schemas'];
export type StartResponse = S['StartResponse'];
export type ResumeResponse = S['ResumeResponse'];
export type SnapshotResponse = S['SnapshotResponse'];
export type QuotaResponse = S['QuotaResponse'];
export type SubmitResponse = S['SubmitResponse'];
export type SaveMode = StartResponse['saveMode'];

/** The server answered with an error status. `status` 0 never happens here (see NetworkError). */
export class HttpError extends Error {
	constructor(
		readonly status: number,
		readonly code: string,
		readonly body: Record<string, unknown>
	) {
		super(`${status} ${code}`);
	}
}

/** No answer at all: offline, DNS, timeout, aborted. Always worth retrying. */
export class NetworkError extends Error {}

/** Worth trying again later: no answer, a server error, or rate limiting. */
export function retryable(e: unknown): boolean {
	if (e instanceof HttpError) return e.status >= 500 || e.status === 429 || e.status === 408;
	return true;
}

export interface Api {
	start(slug: string): Promise<StartResponse>;
	resume(token: string): Promise<ResumeResponse>;
	plan(url: string): Promise<unknown>;
	save(
		sessionId: string,
		token: string,
		baseRevision: number,
		snapshot: Snapshot,
		opts?: { keepalive?: boolean }
	): Promise<SnapshotResponse>;
	quota(sessionId: string, token: string, nodeId: string): Promise<QuotaResponse>;
	submit(sessionId: string, token: string, record: ResponseRecord): Promise<SubmitResponse>;
	/** Consent (semantics.md §11, M5). Optional so older test doubles still type-check. */
	consent?(sessionId: string, token: string, version: string): Promise<unknown>;
	decline?(sessionId: string, token: string): Promise<unknown>;
	withdraw?(sessionId: string, token: string): Promise<unknown>;
}

/** Browsers cap the total body of in-flight keepalive requests at 64 KiB. */
const KEEPALIVE_LIMIT = 60_000;
const TIMEOUT_MS = 20_000;

export function httpApi(base = '', fetchImpl: typeof fetch = (...a) => fetch(...a)): Api {
	async function call<T>(
		method: string,
		path: string,
		opts: { token?: string; body?: unknown; keepalive?: boolean } = {}
	): Promise<T> {
		const headers: Record<string, string> = { Accept: 'application/json' };
		if (opts.token) headers.Authorization = `Bearer ${opts.token}`;
		let body: string | undefined;
		if (opts.body !== undefined) {
			body = JSON.stringify(opts.body);
			headers['Content-Type'] = 'application/json';
		}
		const keepalive = !!opts.keepalive && (body?.length ?? 0) < KEEPALIVE_LIMIT;
		let res: Response;
		try {
			res = await fetchImpl(base + path, {
				method,
				headers,
				body,
				keepalive,
				credentials: 'omit',
				cache: 'no-store',
				signal: AbortSignal.timeout(TIMEOUT_MS)
			});
		} catch (e) {
			throw new NetworkError(e instanceof Error ? e.message : String(e));
		}
		let json: unknown = null;
		try {
			json = res.status === 204 ? {} : await res.json();
		} catch {
			if (res.ok) throw new NetworkError('unreadable response');
		}
		if (!res.ok) {
			const b = (json && typeof json === 'object' ? json : {}) as Record<string, unknown>;
			throw new HttpError(res.status, typeof b.code === 'string' ? b.code : 'http.error', b);
		}
		return json as T;
	}
	const enc = encodeURIComponent;
	return {
		start: (slug) => call('POST', `/api/s/${enc(slug)}/sessions`, { body: { urlParams: {} } }),
		resume: (token) => call('GET', '/api/sessions/resume', { token }),
		plan: (url) => call('GET', url),
		save: (sid, token, baseRevision, snapshot, o) =>
			call('PUT', `/api/sessions/${enc(sid)}/snapshot`, {
				token,
				body: { baseRevision, snapshot },
				keepalive: o?.keepalive
			}),
		quota: (sid, token, nodeId) => call('POST', `/api/sessions/${enc(sid)}/quota/${enc(nodeId)}`, { token }),
		submit: (sid, token, record) => call('POST', `/api/sessions/${enc(sid)}/submit`, { token, body: record }),
		consent: (sid, token, version) =>
			call('POST', `/api/sessions/${enc(sid)}/consent`, { token, body: { consentVersion: version } }),
		decline: (sid, token) => call('POST', `/api/sessions/${enc(sid)}/decline`, { token }),
		withdraw: (sid, token) => call('POST', `/api/sessions/${enc(sid)}/withdraw`, { token })
	};
}
