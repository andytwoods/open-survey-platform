/**
 * The participant session: engine state + local copy + network saves (runtime-design §5).
 * No survey logic: every decision is the engine's. This class only moves snapshots between
 * the engine, IndexedDB and the server, and runs the engine's effects (quota, end).
 *
 * Data-safety rules, step by step:
 * 1. Start: seed, assignment and plan checksum go to the local store *before* the first
 *    page renders (`boot`).
 * 2. Every engine change writes the local snapshot immediately (`commit`).
 * 3. `every-page`: the snapshot is PUT with `baseRevision` on page change, input blur, a
 *    ~3 s debounce while typing, and on `visibilitychange`/`pagehide` (keepalive). A sent
 *    save is resent *unchanged* until it is acknowledged (the server answers an identical
 *    retry with `replay`), so a lost reply never looks like a conflict. Retries back off
 *    exponentially with jitter. With storage blocked it saves on every answer (R-1).
 * 4. Resume and 409: the server copy and the local copy are compared by event log. If one
 *    log is a prefix of the other, the longer one is newer and nothing is lost. Otherwise it
 *    is a true conflict: the server copy wins and the local copy is kept (locally, and sent
 *    once with its stale base so the server stores it in its conflict log, R-2).
 * 5. Quota: idempotent per node on the server; retried until it answers, then `resolve`.
 * 6. End: the ResponseRecord is stored locally, then submitted (idempotent) until the server
 *    acknowledges. Only then does "thank you" show and the local copy go.
 * 7. `end-only`: nothing but quota checks and the final submit reaches the server.
 * 8. Consent (semantics.md §11, M5): while the consent page is shown nothing is saved to
 *    the server in either mode; agree/decline/withdraw are at the end of this class.
 */
import * as E from '@osp/engine';
import type { Effect, PageView, Plan, Snapshot, State } from '@osp/engine';
import { HttpError, retryable, type Api, type ResumeResponse, type SaveMode } from './api';
import type { LocalRecord, LocalStore, SyncBackup } from './storage';

export type Phase = 'page' | 'pending' | 'submitting' | 'done' | 'fatal';
/** Quiet save indicator. `local`: end-only (kept on this device until submit). */
export type NetStatus = 'saved' | 'saving' | 'offline' | 'local';

export interface Env {
	api: Api;
	store: LocalStore;
	now: () => number;
	random: () => number;
	setTimer: (fn: () => void, ms: number) => unknown;
	clearTimer: (handle: unknown) => void;
	debounceMs?: number;
	/** Synchronous copy written on pagehide (see storage.ts SyncBackup). */
	backup?: SyncBackup;
	log?: (msg: string, detail?: unknown) => void;
}

export interface BootOptions {
	slug: string;
	/** From a resume link (`#resume=…`): continue that session, possibly on a new device. */
	resumeToken?: string | null;
	urlParams?: Record<string, string>;
	language?: string;
	device?: E.Device | null;
}

export class BootError extends Error {
	constructor(
		readonly kind: 'not-found' | 'closed' | 'expired' | 'plan' | 'network' | 'invalid',
		message: string
	) {
		super(message);
	}
}

const DAY = 24 * 60 * 60 * 1000;
/** Local copies untouched for this long are deleted on the next load (§5.0). */
export const LOCAL_TTL = 7 * DAY;

/** True when `a` (events) is a prefix of `b`, compared as canonical JSON. */
export function isPrefix(a: Snapshot | null, b: Snapshot | null): boolean {
	if (!a || !b) return false;
	const ea = a.data?.events ?? [];
	const eb = b.data?.events ?? [];
	if (ea.length > eb.length) return false;
	return E.canonicalJson(ea) === E.canonicalJson(eb.slice(0, ea.length));
}

function asSnapshot(x: unknown): Snapshot | null {
	if (!x || typeof x !== 'object') return null;
	const s = x as Snapshot;
	return s.format === 'osp-engine-snapshot/1' && s.data && Array.isArray(s.data.events) ? s : null;
}

function bootError(e: unknown): BootError {
	if (e instanceof BootError) return e;
	if (e instanceof HttpError) {
		if (e.status === 404) return new BootError('not-found', 'This survey link is not valid.');
		if (e.status === 410 && e.code === 'survey.closed') return new BootError('closed', 'This survey is closed.');
		if (e.status === 410 || e.status === 401) return new BootError('expired', 'This session has expired.');
		if (e.status === 429) return new BootError('network', 'Too many attempts. Please try again in a minute.');
		return new BootError('invalid', `The server refused the request (${e.code}).`);
	}
	return new BootError('network', 'Could not reach the survey server. Check your connection and try again.');
}

export class Session {
	plan: Plan;
	state: State;
	rec: LocalRecord;
	phase: Phase = 'page';
	net: NetStatus;
	fatal: string | null = null;
	/** The engine state changed underneath the page (server copy adopted): refocus. */
	replaced = 0;

	private env: Env;
	private listeners = new Set<() => void>();
	private pumping = false;
	private again = false;
	private debounce: unknown = null;
	private sleeper: { handle: unknown; wake: () => void } | null = null;
	private attempt = 0;
	/** Saves wait until the local copy has been reconciled with the server (resume). */
	private reconciled: boolean;
	private writes: Promise<void> = Promise.resolve();
	private writeQueued = false;
	private sending = false;
	private gone = false;
	private closed = false;
	private effectRunning = false;

	constructor(env: Env, rec: LocalRecord, plan: Plan, state: State, reconciled: boolean) {
		this.env = env;
		this.rec = rec;
		this.plan = plan;
		this.state = state;
		this.reconciled = reconciled;
		this.net = rec.saveMode === 'end-only' ? 'local' : 'saved';
	}

	get saveMode(): SaveMode {
		return this.rec.saveMode;
	}
	get storageBlocked(): boolean {
		return this.env.store.kind === 'memory';
	}
	/** After boot: reconcile with the server (every-page resume), then run pending effects. */
	async run(): Promise<void> {
		if (this.phase === 'done') return;
		if (!this.reconciled) await this.resumeSync();
		else {
			await this.runEffects();
			void this.pump();
		}
	}

	view(): PageView {
		return E.view(this.state);
	}
	subscribe(fn: () => void): () => void {
		this.listeners.add(fn);
		return () => this.listeners.delete(fn);
	}
	private emit() {
		for (const fn of this.listeners) fn();
	}
	private log(msg: string, detail?: unknown) {
		this.env.log?.(msg, detail);
	}

	// -- local copy -----------------------------------------------------------------

	/**
	 * Write the record (ordered after earlier writes). Writes that queue up behind a running
	 * one coalesce: the store copies the record when the write starts, so it is the newest.
	 */
	private persist(): Promise<void> {
		// After submit the local copy is deleted; a late save ack must not write it back.
		if (this.gone) return this.writes;
		this.rec.updatedAt = this.env.now();
		if (!this.writeQueued) {
			this.writeQueued = true;
			this.writes = this.writes
				.then(() => {
					this.writeQueued = false;
					return this.env.store.put(this.rec);
				})
				.catch((e) => this.log('local write failed', e));
		}
		return this.writes;
	}

	/** A new engine state: snapshot it locally first, then schedule the network save. */
	private commit(next: State, save: 'debounce' | 'now' | 'none'): Promise<void> {
		this.state = next;
		this.rec.snapshot = E.snapshot(next);
		const written = this.persist();
		if (save === 'now') this.saveNow();
		else if (save === 'debounce') this.scheduleSave();
		this.emit();
		return written;
	}

	// -- participant actions ---------------------------------------------------------

	answer(itemId: string, value: unknown) {
		if (this.phase !== 'page') return;
		const next = E.answer(this.state, itemId, value);
		if (next === this.state) return;
		// R-1: with no local storage, every answer goes to the server straight away.
		this.commit(next, this.storageBlocked ? 'now' : 'debounce');
	}

	/** An input lost focus: save what was typed. */
	blur() {
		if (this.rec.snapshot && this.rec.snapshot.revision !== this.rec.syncedEngineRev) this.saveNow();
	}

	next(): E.StepResult['outcome'] | null {
		if (this.phase !== 'page') return null;
		const r = E.next(this.state);
		this.commit(r.state, 'now');
		if (r.effect) void this.runEffects();
		return r.result.outcome;
	}

	back(): boolean {
		if (this.phase !== 'page') return false;
		const next = E.back(this.state);
		if (next === this.state) return false;
		this.commit(next, 'now');
		return true;
	}

	/**
	 * The page is being hidden or unloaded: copy the newest snapshot synchronously, in case
	 * the asynchronous IndexedDB write has not landed. Never in memory-only mode (§5.0).
	 */
	flushLocalSync() {
		if (this.closed || this.storageBlocked || !this.rec.snapshot) return;
		this.env.backup?.write(this.rec.slug, this.rec.sessionId, this.rec.snapshot);
	}

	/** The page is being hidden or unloaded: last-chance save with `keepalive`. */
	flushKeepalive() {
		if (this.saveMode !== 'every-page' || this.closed || !this.reconciled) return;
		if (E.awaitingConsent(this.state)) return; // §11: nothing before agreement
		const snap = this.rec.snapshot;
		if (!snap) return;
		if (!this.rec.inflight && snap.revision === this.rec.syncedEngineRev) return;
		// A save is on the wire (sent with keepalive): a duplicate would only arrive late as a
		// stale write and clutter the server's conflict log.
		if (this.sending) return;
		if (!this.rec.inflight) {
			this.rec.inflight = { base: this.rec.serverRevision, snapshot: snap };
			void this.persist();
		}
		const body = this.rec.inflight;
		// Fire and forget. If it lands, the next normal save of the same body is a replay.
		this.env.api
			.save(this.rec.sessionId, this.rec.resumeToken, body.base, body.snapshot, { keepalive: true })
			.catch(() => undefined);
	}

	/** Connectivity came back, or the page became visible again: retry now. */
	wake() {
		if (this.sleeper) {
			this.env.clearTimer(this.sleeper.handle);
			const w = this.sleeper.wake;
			this.sleeper = null;
			w();
		}
	}

	// -- network save (every-page) ----------------------------------------------------

	private scheduleSave() {
		if (this.saveMode !== 'every-page') return;
		if (this.debounce !== null) this.env.clearTimer(this.debounce);
		this.debounce = this.env.setTimer(() => {
			this.debounce = null;
			void this.pump();
		}, this.env.debounceMs ?? 3000);
	}

	saveNow() {
		if (this.saveMode !== 'every-page') return;
		if (this.debounce !== null) {
			this.env.clearTimer(this.debounce);
			this.debounce = null;
		}
		if (this.pumping) this.wake();
		void this.pump();
	}

	private backoff(): number {
		const base = Math.min(30_000, 1000 * 2 ** Math.min(this.attempt, 5));
		this.attempt++;
		return Math.round(base / 2 + (this.env.random() * base) / 2);
	}

	private sleep(ms: number): Promise<void> {
		return new Promise((resolve) => {
			const handle = this.env.setTimer(() => {
				this.sleeper = null;
				resolve();
			}, ms);
			this.sleeper = { handle, wake: resolve };
		});
	}

	private setNet(n: NetStatus) {
		if (this.net !== n) {
			this.net = n;
			this.emit();
		}
	}

	private dirty(): boolean {
		const s = this.rec.snapshot;
		return !!this.rec.inflight || (!!s && s.revision !== this.rec.syncedEngineRev);
	}

	/** Send saves until the server holds the newest snapshot. One loop at a time. */
	async pump(): Promise<void> {
		if (this.saveMode !== 'every-page' || this.closed || !this.reconciled) return;
		if (E.awaitingConsent(this.state)) return; // §11: nothing before agreement
		if (this.pumping) {
			this.again = true;
			return;
		}
		this.pumping = true;
		try {
			do {
				this.again = false;
				while (this.dirty() && !this.closed) {
					if (!this.rec.inflight) {
						this.rec.inflight = { base: this.rec.serverRevision, snapshot: this.rec.snapshot! };
						await this.persist();
					}
					const body = this.rec.inflight;
					this.setNet('saving');
					try {
						// keepalive: an unload does not cancel it, so flushKeepalive needn't resend it.
						this.sending = true;
						const ack = await this.env.api
							.save(this.rec.sessionId, this.rec.resumeToken, body.base, body.snapshot, { keepalive: true })
							.finally(() => (this.sending = false));
						this.rec.serverRevision = ack.revision;
						this.rec.syncedEngineRev = body.snapshot.revision;
						this.rec.inflight = null;
						this.attempt = 0;
						await this.persist();
					} catch (e) {
						if (!(await this.saveFailed(e, body))) return;
					}
				}
			} while (this.again && !this.closed);
			if (!this.closed) this.setNet('saved');
		} finally {
			this.pumping = false;
		}
	}

	/** Handle a failed save. Returns false when saving must stop. */
	private async saveFailed(e: unknown, body: { base: number; snapshot: Snapshot }): Promise<boolean> {
		if (e instanceof HttpError && e.status === 409 && e.code === 'snapshot.stale') {
			this.rec.inflight = null;
			const rev = typeof e.body.revision === 'number' ? e.body.revision : this.rec.serverRevision;
			this.reconcile(rev, asSnapshot(e.body.snapshot), body.snapshot);
			await this.persist();
			return true;
		}
		if (e instanceof HttpError && e.code === 'session.submitted') {
			// Submitted (perhaps from another tab): nothing more to save.
			this.rec.inflight = null;
			return false;
		}
		if (e instanceof HttpError && (e.status === 401 || e.status === 410)) {
			this.fail('This session has expired, so your answers can no longer be saved.');
			return false;
		}
		if (!retryable(e)) {
			// 413/422: the server will never take this snapshot. Keep it locally and stop.
			this.log('save refused', e);
			this.rec.inflight = null;
			this.setNet('offline');
			return false;
		}
		this.setNet('offline');
		await this.sleep(this.backoff());
		return true;
	}

	/**
	 * The server holds `server` at `rev`; ours is `this.rec.snapshot`. `sent` is the local
	 * copy that lost (for the conflict record). Updates the record; never loses a newer log.
	 */
	private reconcile(rev: number, server: Snapshot | null, sent?: Snapshot) {
		const local = this.rec.snapshot;
		if (!server || isPrefix(server, local)) {
			// Ours is the same or newer: rebase onto the server revision and push.
			this.rec.serverRevision = rev;
			this.rec.syncedEngineRev = server ? server.revision : -1;
			return;
		}
		const restored = E.restore(this.plan, server, { clock: this.env.now });
		if (!E.isState(restored)) {
			// The server copy is unreadable: keep ours and overwrite it.
			this.log('server snapshot did not restore', restored.error);
			this.rec.serverRevision = rev;
			this.rec.syncedEngineRev = -1;
			return;
		}
		if (local && !isPrefix(local, server)) {
			this.rec.conflicts.push({ at: this.env.now(), serverRevision: rev, snapshot: sent ?? local });
			this.log('conflict: kept the server copy, local copy kept for the record');
		}
		this.state = restored;
		this.rec.snapshot = server;
		this.rec.serverRevision = rev;
		this.rec.syncedEngineRev = server.revision;
		this.replaced++;
		this.emit();
	}

	/** Boot-time reconciliation with the server's copy (every-page). Retries until it answers. */
	async resumeSync(given?: ResumeResponse): Promise<void> {
		if (this.saveMode !== 'every-page' || this.reconciled) return;
		let r = given;
		while (!r && !this.closed) {
			try {
				r = await this.env.api.resume(this.rec.resumeToken);
			} catch (e) {
				if (e instanceof HttpError && (e.status === 401 || e.status === 410)) {
					this.fail('This session has expired, so your answers can no longer be saved.');
					return;
				}
				this.setNet('offline');
				await this.sleep(this.backoff());
			}
		}
		if (!r) return;
		this.attempt = 0;
		if (r.submitted) {
			await this.finish();
			return;
		}
		const server = asSnapshot(r.snapshot);
		const local = this.rec.snapshot;
		const trueConflict = !!server && !!local && !isPrefix(server, local) && !isPrefix(local, server);
		if (trueConflict) {
			// Let the server log the losing copy: a stale base always gets 409 + conflict row.
			this.env.api
				.save(this.rec.sessionId, this.rec.resumeToken, Math.min(this.rec.serverRevision, r.revision - 1), local!)
				.catch(() => undefined);
		}
		this.rec.inflight = null;
		this.reconcile(r.revision, server);
		this.reconciled = true;
		await this.persist();
		this.emit();
		await this.runEffects();
		void this.pump();
	}

	// -- effects -----------------------------------------------------------------------

	/** Run whatever the engine is waiting for: a quota check, or the final submit. */
	async runEffects(): Promise<void> {
		if (this.effectRunning || this.closed) return;
		this.effectRunning = true;
		try {
			for (;;) {
				const v = E.view(this.state);
				if (v.status === 'pending' && v.effect?.kind === 'quota') {
					this.phase = 'pending';
					this.emit();
					const ok = await this.runQuota(v.effect);
					if (!ok) return;
					continue;
				}
				if (v.status === 'ended') {
					// §11: a declined session records no response; never submit it.
					if (E.declinedConsent(this.state)) await this.finish();
					else await this.submit();
					return;
				}
				this.phase = 'page';
				this.emit();
				return;
			}
		} finally {
			this.effectRunning = false;
		}
	}

	private async runQuota(effect: Effect & { kind: 'quota' }): Promise<boolean> {
		for (;;) {
			try {
				const r = await this.env.api.quota(this.rec.sessionId, this.rec.resumeToken, effect.nodeId);
				this.attempt = 0;
				if (this.saveMode === 'every-page') this.setNet(this.dirty() ? 'saving' : 'saved');
				const value = r.result === 'full' ? 'full' : 'open';
				const next = E.resolve(this.state, effect, value);
				await this.commit(next, 'now');
				return true;
			} catch (e) {
				if (!retryable(e)) {
					if (e instanceof HttpError && e.code === 'session.submitted') await this.finish();
					else this.fail('Something went wrong checking your place in this survey. Please contact the research team.');
					return false;
				}
				this.setNet('offline');
				await this.sleep(this.backoff());
			}
		}
	}

	private async submit(): Promise<void> {
		this.phase = 'submitting';
		if (!this.rec.submitting) {
			this.rec.submitting = E.result(this.state);
			await this.persist();
		}
		this.emit();
		for (;;) {
			try {
				await this.env.api.submit(this.rec.sessionId, this.rec.resumeToken, this.rec.submitting);
				break;
			} catch (e) {
				if (e instanceof HttpError && e.code === 'submit.mismatch') {
					// Already submitted with other data (another device finished first).
					this.log('submit mismatch: the session was already submitted', e.body);
					break;
				}
				if (!retryable(e)) {
					if (e instanceof HttpError && (e.status === 401 || e.status === 410))
						this.fail('This session has expired, so your answers could not be submitted.');
					else this.fail('Your answers could not be submitted. Please keep this page open and contact the research team.');
					return;
				}
				this.setNet('offline');
				await this.sleep(this.backoff());
			}
		}
		await this.finish();
	}

	/** The server has the response: say thank you, delete the local copy, stop saving. */
	async finish() {
		this.closed = true;
		if (this.debounce !== null) this.env.clearTimer(this.debounce);
		this.wake();
		this.phase = 'done';
		this.env.backup?.take(this.rec.slug, this.rec.sessionId);
		this.net = 'saved';
		this.gone = true;
		await this.writes;
		try {
			await this.env.store.delete(this.rec.slug);
		} catch (e) {
			this.log('could not delete the local copy', e);
		}
		this.emit();
	}

	private fail(message: string) {
		this.closed = true;
		this.phase = 'fatal';
		this.fatal = message;
		this.emit();
	}

	// -- consent and withdrawal (semantics.md §11, M5; UI in ConsentPage / Withdraw) ------

	/** The consent call or the withdrawal is on the wire. */
	consentBusy = false;
	/** The participant withdrew: the server deleted their response and session. */
	withdrawn = false;

	/** Retry a consent-related call until the server answers; false if it refused. */
	private async consentCall(fn: () => Promise<unknown> | undefined, gone: (e: HttpError) => boolean): Promise<boolean> {
		this.consentBusy = true;
		this.emit();
		try {
			for (;;) {
				try {
					await fn();
					this.attempt = 0;
					return true;
				} catch (e) {
					if (e instanceof HttpError && gone(e)) return true;
					if (!retryable(e)) {
						this.log('consent call refused', e);
						return false;
					}
					this.setNet('offline');
					await this.sleep(this.backoff());
				}
			}
		} finally {
			this.consentBusy = false;
			this.emit();
		}
	}

	/** Agree: the server records it first, then the flow starts and saving begins. */
	async agree(): Promise<boolean> {
		const c = this.plan.consent;
		if (!c || !E.awaitingConsent(this.state) || this.consentBusy) return false;
		const ok = await this.consentCall(
			() => this.env.api.consent?.(this.rec.sessionId, this.rec.resumeToken, c.version),
			() => false
		);
		if (!ok) {
			this.fail('Your answer could not be recorded. Please reload the page and try again.');
			return false;
		}
		if (this.saveMode === 'every-page') this.setNet('saved');
		await this.commit(E.agree(this.state), 'now');
		return true;
	}

	/** Decline: the server deletes the session; nothing is kept here either. */
	async decline(): Promise<void> {
		if (!E.awaitingConsent(this.state) || this.consentBusy) return;
		await this.consentCall(
			() => this.env.api.decline?.(this.rec.sessionId, this.rec.resumeToken),
			(e) => e.status === 401 || e.status === 404 // already gone
		);
		this.state = E.decline(this.state);
		await this.finish();
	}

	/** Withdraw (after agreeing): the server deletes the response and session. */
	async withdraw(): Promise<boolean> {
		if (this.withdrawn || this.consentBusy || E.awaitingConsent(this.state)) return false;
		const ok = await this.consentCall(
			() => this.env.api.withdraw?.(this.rec.sessionId, this.rec.resumeToken),
			(e) => e.status === 401 // the token no longer exists: already withdrawn
		);
		if (!ok) return false;
		this.withdrawn = true;
		await this.finish();
		return true;
	}

	/** Stop timers (tests, teardown). */
	dispose() {
		this.closed = true;
		if (this.debounce !== null) this.env.clearTimer(this.debounce);
		this.wake();
	}
}

// -- boot --------------------------------------------------------------------------------

/** Boot-time calls: a few quick retries on a dropped connection or a server hiccup. */
async function withRetry<T>(env: Env, fn: () => Promise<T>, tries = 5): Promise<T> {
	for (let i = 0; ; i++) {
		try {
			return await fn();
		} catch (e) {
			if (i + 1 >= tries || !retryable(e)) throw e;
			const base = 500 * 2 ** i;
			await new Promise((r) => env.setTimer(() => r(undefined), base / 2 + (env.random() * base) / 2));
		}
	}
}

async function loadPlan(env: Env, url: string, checksum: string, cached: Plan | null): Promise<Plan> {
	let plan: unknown = cached;
	if (!cached || cached.checksum !== checksum) plan = await withRetry(env, () => env.api.plan(url));
	// The checksum is recomputed here, not trusted from the file (§5.1).
	const p = plan as Plan;
	if (!p || typeof p !== 'object' || p.checksum !== checksum || E.planChecksum(p) !== checksum) {
		throw new BootError('plan', 'The survey could not be loaded (its checksum does not match).');
	}
	try {
		E.checkPlan(p);
	} catch {
		throw new BootError('plan', 'This survey needs a newer version of the survey app.');
	}
	return p;
}

function newRecord(slug: string, r: { sessionId: string; resumeToken: string; sessionSeed: number; assigned: Record<string, unknown>; planUrl: string; planChecksum: string; saveMode: SaveMode }, now: number): LocalRecord {
	return {
		slug,
		sessionId: r.sessionId,
		resumeToken: r.resumeToken,
		sessionSeed: r.sessionSeed,
		assigned: r.assigned as Record<string, string | number>,
		planUrl: r.planUrl,
		planChecksum: r.planChecksum,
		saveMode: r.saveMode,
		plan: null,
		snapshot: null,
		serverRevision: 0,
		syncedEngineRev: -1,
		inflight: null,
		conflicts: [],
		submitting: null,
		createdAt: now,
		updatedAt: now
	};
}

function startEngine(env: Env, plan: Plan, rec: LocalRecord, o: BootOptions): State {
	return E.start(plan, {
		sessionSeed: rec.sessionSeed,
		assigned: rec.assigned,
		clock: env.now,
		language: o.language,
		device: o.device ?? null,
		urlParams: o.urlParams ?? {},
		sessionId: rec.sessionId
	});
}

/**
 * Start or resume a session. Order matters: the record (seed, assignment, plan checksum)
 * is written locally before the engine starts and before anything renders.
 */
export async function boot(env: Env, o: BootOptions): Promise<Session> {
	try {
		await env.store.purge(env.now() - LOCAL_TTL);
	} catch {
		/* best effort */
	}
	let rec = (await env.store.get(o.slug)) ?? null;
	if (rec && o.resumeToken && rec.resumeToken !== o.resumeToken) rec = null; // the link wins

	// A resume link on a device without a local copy: the server copy is the truth.
	if (!rec && o.resumeToken) {
		let r: ResumeResponse;
		try {
			r = await withRetry(env, () => env.api.resume(o.resumeToken!));
		} catch (e) {
			throw bootError(e);
		}
		rec = newRecord(o.slug, { ...r, resumeToken: o.resumeToken }, env.now());
		await env.store.put(rec);
		const plan = await loadPlan(env, r.planUrl, r.planChecksum, null).catch((e) => Promise.reject(bootError(e)));
		rec.plan = plan;
		const server = asSnapshot(r.snapshot);
		let state: State;
		if (server) {
			const restored = E.restore(plan, server, { clock: env.now });
			if (!E.isState(restored)) throw new BootError('invalid', 'The saved answers could not be restored.');
			state = restored;
			rec.snapshot = server;
			rec.syncedEngineRev = server.revision;
		} else {
			state = startEngine(env, plan, rec, o);
			rec.snapshot = E.snapshot(state);
		}
		rec.serverRevision = r.revision;
		await env.store.put(rec);
		const s = new Session(env, rec, plan, state, true);
		if (r.submitted) await s.finish();
		return s;
	}

	if (!rec) {
		let st;
		try {
			st = await withRetry(env, () => env.api.start(o.slug));
		} catch (e) {
			throw bootError(e);
		}
		rec = newRecord(o.slug, st, env.now());
		rec.serverRevision = st.revision;
		await env.store.put(rec); // seed + assignment + checksum, before anything renders
		const plan = await loadPlan(env, st.planUrl, st.planChecksum, null).catch((e) => Promise.reject(bootError(e)));
		rec.plan = plan;
		const state = startEngine(env, plan, rec, o);
		rec.snapshot = E.snapshot(state);
		await env.store.put(rec);
		const s = new Session(env, rec, plan, state, true);
		return s;
	}

	// A local copy exists (refresh, tab killed, came back later).
	const plan = await loadPlan(env, rec.planUrl, rec.planChecksum, rec.plan).catch((e) => Promise.reject(bootError(e)));
	rec.plan = plan;
	const last = env.backup?.take(rec.slug, rec.sessionId) ?? null;
	if (last && (!rec.snapshot || (isPrefix(rec.snapshot, last) && last.data.events.length > rec.snapshot.data.events.length))) {
		rec.snapshot = last; // the pagehide copy is newer than the last IndexedDB write
	}
	let state: State;
	const local = rec.snapshot ? E.restore(plan, rec.snapshot, { clock: env.now }) : null;
	if (local && E.isState(local)) state = local;
	else {
		state = startEngine(env, plan, rec, o);
		rec.snapshot = E.snapshot(state);
	}
	await env.store.put(rec);
	return new Session(env, rec, plan, state, rec.saveMode !== 'every-page');
}
