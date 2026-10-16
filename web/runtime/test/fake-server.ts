/**
 * An in-memory stand-in for the participant API with the same rules as osp-runtime +
 * osp-store: conditional snapshot writes (identical retry = replay, other stale write =
 * 409 + conflict row), idempotent quota and submit. Can drop requests or replies.
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
	quotas: Record<string, 'admitted' | 'full'>;
}

export class FakeServer {
	sessions = new Map<string, Sess>();
	conflicts: Array<{ session: string; base: number; snapshot: Snapshot }> = [];
	calls: string[] = [];
	/** No request reaches the server. */
	offline = false;
	/** The next N requests are applied but their replies are lost. */
	dropReplies = 0;
	/** Per call name: the next N such requests are applied but their replies are lost. */
	dropOn: Record<string, number> = {};
	quotaResult: 'admitted' | 'full' = 'admitted';
	private n = 0;

	constructor(
		readonly plan: Plan,
		readonly saveMode: 'every-page' | 'end-only' = 'every-page',
		readonly assigned: Record<string, string> = {}
	) {}

	private async io<T>(name: string, fn: () => T): Promise<T> {
		this.calls.push(name);
		await Promise.resolve();
		if (this.offline) throw new NetworkError('offline');
		const out = fn();
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
				if (base === s.revision) {
					s.revision++;
					s.snapshot = body;
					return { revision: s.revision, replay: false };
				}
				if (base === s.revision - 1 && canonicalJson(body) === canonicalJson(s.snapshot)) {
					return { revision: s.revision, replay: true };
				}
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
			})
	};
}
