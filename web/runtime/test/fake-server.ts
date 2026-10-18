/**
 * An in-memory stand-in for the participant API with the same rules as osp-runtime +
 * osp-store: conditional snapshot writes (identical retry = replay, a late older prefix =
 * superseded, a save that extends the server copy = fast-forward whatever its base (R9-1),
 * other stale write = 409 + conflict row), idempotent quota and submit. Can drop requests
 * or replies, or hold saves to deliver them in a chosen order.
 */
import { canonicalJson, type Plan, type ResponseRecord, type Snapshot } from '@osp/engine';
import { HttpError, NetworkError, type Api } from '../src/lib/api';

interface Sess {
	id: string;
	token: string;
	seed: number;
	assigned: Record<string, string>;
	revision: number;
	snapshot: Snapshot | null;
	submitted: ResponseRecord | null;
	quotas: Record<string, 'open' | 'full'>;
}

export class FakeServer {
	sessions = new Map<string, Sess>();
	conflicts: Array<{ session: string; base: number; snapshot: Snapshot }> = [];
	calls: string[] = [];
	/** Every request the server refused, as `call:code` (e.g. `save:session.submitted`). */
	refused: string[] = [];
	/** No request reaches the server. */
	offline = false;
	/** The next N requests are applied but their replies are lost. */
	dropReplies = 0;
	/** Per call name: the next N such requests are applied but their replies are lost. */
	dropOn: Record<string, number> = {};
	quotaResult: 'open' | 'full' = 'open';
	/** Saves wait here (in arrival order at the network) until released, in any order. */
	holdSaves = false;
	held: Array<() => void> = [];
	private n = 0;

	constructor(
		readonly plan: Plan,
		readonly saveMode: 'every-page' | 'end-only' = 'every-page',
		readonly assigned: Record<string, string> = {}
	) {}

	private async io<T>(name: string, fn: () => T): Promise<T> {
		this.calls.push(name);
		await Promise.resolve();
		if (name === 'save' && this.holdSaves) await new Promise<void>((go) => this.held.push(go));
		if (this.offline) throw new NetworkError('offline');
		let out: T;
		try {
			out = fn();
		} catch (e) {
			if (e instanceof HttpError) this.refused.push(`${name}:${e.code}`);
			throw e;
		}
		if (this.dropReplies > 0 || (this.dropOn[name] ?? 0) > 0) {
			if ((this.dropOn[name] ?? 0) > 0) this.dropOn[name]!--;
			else this.dropReplies--;
			throw new NetworkError('reply lost');
		}
		return out;
	}

	private auth(token: string, sid?: string): Sess {
		for (const s of this.sessions.values()) if (s.token === token && (!sid || s.id === sid)) return s;
		throw new HttpError(401, 'token.invalid', {});
	}

	get only(): Sess {
		return [...this.sessions.values()][0]!;
	}

	api: Api = {
		start: () =>
			this.io('start', () => {
				const id = `s${++this.n}`;
				const s: Sess = {
					id,
					token: `tok-${id}`,
					seed: 1000 + this.n,
					assigned: this.assigned,
					revision: 0,
					snapshot: null,
					submitted: null,
					quotas: {}
				};
				this.sessions.set(id, s);
				return {
					sessionId: id,
					resumeToken: s.token,
					sessionSeed: s.seed,
					assigned: s.assigned,
					planUrl: `/plan/${this.plan.checksum}`,
					planChecksum: this.plan.checksum,
					saveMode: this.saveMode,
					revision: 0
				};
			}),
		resume: (token) =>
			this.io('resume', () => {
				const s = this.auth(token);
				return {
					sessionId: s.id,
					revision: s.revision,
					snapshot: s.snapshot ? (JSON.parse(canonicalJson(s.snapshot)) as Record<string, unknown>) : null,
					sessionSeed: s.seed,
					assigned: s.assigned,
					planUrl: `/plan/${this.plan.checksum}`,
					planChecksum: this.plan.checksum,
					saveMode: this.saveMode,
					submitted: !!s.submitted
				};
			}),
		plan: () => this.io('plan', () => JSON.parse(JSON.stringify(this.plan))),
		save: (sid, token, base, snapshot) =>
			this.io('save', () => {
				const s = this.auth(token, sid);
				if (s.submitted) throw new HttpError(409, 'session.submitted', {});
				if (this.saveMode !== 'every-page') throw new HttpError(403, 'save_mode.end_only', {});
				const body = JSON.parse(canonicalJson(snapshot)) as Snapshot;
				const write = () => {
					s.revision++;
					s.snapshot = body;
					return { revision: s.revision, replay: false };
				};
				if (base === s.revision) return write();
				if (base === s.revision - 1 && canonicalJson(body) === canonicalJson(s.snapshot)) {
					return { revision: s.revision, replay: true };
				}
				// The store's judge (osp-runtime save_snapshot), in the same order.
				const log = (x: Snapshot | null) => x?.data?.events ?? [];
				const prefix = (a: Snapshot | null, b: Snapshot | null) =>
					canonicalJson(log(a)) === canonicalJson(log(b).slice(0, log(a).length));
				if (base < s.revision && log(body).length <= log(s.snapshot).length && prefix(body, s.snapshot)) {
					return { revision: s.revision, replay: false, superseded: true };
				}
				if (log(body).length > log(s.snapshot).length && prefix(s.snapshot, body)) return write(); // fast-forward
				this.conflicts.push({ session: s.id, base, snapshot: body });
				throw new HttpError(409, 'snapshot.stale', { revision: s.revision, snapshot: s.snapshot });
			}),
		quota: (sid, token, nodeId) =>
			this.io('quota', () => {
				const s = this.auth(token, sid);
				const replay = nodeId in s.quotas;
				s.quotas[nodeId] ??= this.quotaResult;
				return { nodeId, result: s.quotas[nodeId]!, replay };
			}),
		submit: (sid, token, record) =>
			this.io('submit', () => {
				const s = this.auth(token, sid);
				const body = JSON.parse(canonicalJson(record)) as ResponseRecord;
				if (s.submitted) {
					if (canonicalJson(s.submitted) !== canonicalJson(body)) throw new HttpError(409, 'submit.mismatch', {});
					return { responseId: `r-${s.id}`, submittedAt: '2026-01-01T00:00:00Z', replay: true, late: false };
				}
				s.submitted = body;
				return { responseId: `r-${s.id}`, submittedAt: '2026-01-01T00:00:00Z', replay: false, late: false };
			}),
		externalHandoff: (sid, token, nodeId) =>
			this.io('externalHandoff', () => {
				const s = this.auth(token, sid);
				return { returnToken: `rt:${s.id}:${nodeId}`, expiresAt: '2026-01-01T06:00:00Z' };
			}),
		externalReturn: (sid, token, nodeId, returnToken) =>
			this.io('externalReturn', () => {
				const s = this.auth(token, sid);
				// Minted and bound to this session and node (task EX2): anything else is rejected.
				if (returnToken !== `rt:${s.id}:${nodeId}`) throw new HttpError(403, 'external.token_invalid', {});
				return { ok: true, nodeId };
			})
	};
}
