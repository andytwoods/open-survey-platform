/**
 * The participant session: engine state + local copy + network saves (runtime-design §5).
 * No survey logic: every decision is the engine's. This class only moves snapshots between
 * the engine, IndexedDB and the server, and runs the engine's effects (quota, end, hooks).
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
 *    is a true conflict: the server copy wins, the page shows it with a notice (R6-6), and
 *    the local copy is kept (locally, and sent once with its stale base so the server stores
 *    it in its conflict log, R-2).
 * 5. Quota: idempotent per (session, node) on the server; retried until it answers, then
 *    `resolve`. A refresh while it is pending re-sends the same call (R6-4).
 * 6. End: the ResponseRecord is stored locally, then submitted (idempotent) until the server
 *    acknowledges. Only then does "thank you" show and the local copy go.
 * 7. `end-only`: nothing but quota checks and the final submit reaches the server.
 * 8. No durable local copy (IndexedDB blocked, or `localCopy: memory`): the session id and
 *    resume token are kept in the tab (`SessionPointer`), so a refresh resumes the server's
 *    copy (every-page, R4-3) or restarts the same session with the same seed and conditions
 *    and says so (end-only, R6-5).
 * 9. Consent (semantics.md §11, M5): while the consent page is shown nothing is saved to
 *    the server in either mode; agree/decline/withdraw are at the end of this class.
 */
import * as E from '@osp/engine';
import type { Effect, PageView, Plan, Snapshot, State } from '@osp/engine';
import type { FireOutcome, HookRunner, NextOutcome } from '@osp/hooks-sandbox';
import { HttpError, retryable, type Api, type ResumeResponse, type SaveMode } from './api';
import { fill, negotiateLanguage, ui } from './messages';
import { MemoryStore, type LocalRecord, type LocalStore, type SessionPointer, type SyncBackup } from './storage';

export type Phase = 'page' | 'pending' | 'hook' | 'submitting' | 'done' | 'fatal';
/** Quiet save indicator. `local`: end-only (kept on this device until submit). */
export type NetStatus = 'saved' | 'saving' | 'offline' | 'local';
/**
 * A one-off message about the session itself (fixtures/FORMAT.md §3 `notice`): the server
 * copy replaced this device's (R6-6), or a memory-only session restarted (R6-5). It stays
 * until the participant moves to another page.
 */
export type Notice = 'conflict' | 'restarted' | null;
/** Why there is no durable local copy: storage is blocked, or the survey chose memory. */
export type MemoryReason = 'blocked' | 'chosen' | null;

/** The part of `HookRunner` (`@osp/hooks-sandbox`) the session drives. */
export type HookDriver = Pick<
	HookRunner,
	| 'begin'
	| 'resume'
	| 'answer'
	| 'next'
	| 'back'
	| 'arrive'
	| 'beforeSubmit'
	| 'submitted'
	| 'retry'
	| 'setState'
	| 'redirectUrl'
	| 'unloading'
	| 'dispose'
	| 'awaitingRetry'
>;
/** Builds the hook runner for a plan that declares hooks (`hooks.ts`); null if it can't. */
export type HookFactory = (plan: Plan, state: State, onState: (s: State) => void) => Promise<HookDriver | null>;

export interface Env {
	api: Api;
	store: LocalStore;
	now: () => number;
	random: () => number;
	setTimer: (fn: () => void, ms: number) => unknown;
	clearTimer: (handle: unknown) => void;
	debounceMs?: number;
	/** Delay of the save after an input loses focus (default 250 ms). */
	blurDelayMs?: number;
	/** Synchronous copy written on pagehide (see storage.ts SyncBackup). */
	backup?: SyncBackup;
	/** Where the session is kept when there is no durable local copy (storage.ts): this tab. */
	pointer?: SessionPointer;
	/** The same, findable from another tab later: every-page sessions only (storage.ts). */
	devicePointer?: SessionPointer | null;
	/** Researcher hooks: only used when the plan declares them. */
	hooks?: HookFactory;
	log?: (msg: string, detail?: unknown) => void;
}

export interface BootOptions {
	slug: string;
	/** From a resume link (`#resume=…`): continue that session, possibly on a new device. */
	resumeToken?: string | null;
	urlParams?: Record<string, string>;
	/** The participant's languages, most preferred first (navigator.languages). */
	languages?: readonly string[];
	/** One preferred language (kept for callers that have only one). */
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
		if (e.status === 404) return new BootError('not-found', ui.notFound);
		if (e.status === 410 && e.code === 'survey.closed') return new BootError('closed', ui.closed);
		if (e.status === 410 || e.status === 401) return new BootError('expired', ui.expired);
		if (e.status === 429) return new BootError('network', ui.tooMany);
		return new BootError('invalid', fill(ui.refused, { code: e.code }));
	}
	return new BootError('network', ui.unreachable);
}

/** The participant's language for this plan (R4-4): `de-DE` → `de`, else the default. */
export function sessionLanguage(plan: Plan, o: Pick<BootOptions, 'languages' | 'language'>): string {
	const prefs = o.languages?.length ? o.languages : o.language ? [o.language] : [];
	return negotiateLanguage(prefs, plan.languages, plan.defaultLanguage);
}

/** No durable local copy for this plan: end-only with `localCopy: memory` (§5.0). */
function memoryChosen(plan: Plan, rec: Pick<LocalRecord, 'saveMode' | 'localCopy'>): boolean {
	// The server's word (start/resume `localCopy`) first, else the plan's setting.
	return rec.saveMode === 'end-only' && (rec.localCopy ?? plan.settings?.localCopy) === 'memory';
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
	notice: Notice = null;
	memory: MemoryReason;
	/**
	 * Errors come only from a `next` on the page shown (fixtures/FORMAT.md §3): a page
	 * restored by refresh, resume or another device's copy shows none until the next `next`
	 * (R4-2), although the restored engine state still holds the last ones.
	 */
	errorsHidden = false;
	/** A flow-critical hook failed: the page shows a retry prompt (runtime-design §7a). */
	hookRetry = false;

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
	private hooks: HookDriver | null = null;
	/** The session started on this load (hooks `begin`), rather than resumed (`resume`). */
	private fresh: boolean;

	constructor(env: Env, rec: LocalRecord, plan: Plan, state: State, reconciled: boolean, fresh = false) {
		this.env = env;
		this.rec = rec;
		this.plan = plan;
		this.state = state;
		this.reconciled = reconciled;
		this.fresh = fresh;
		this.net = rec.saveMode === 'end-only' ? 'local' : 'saved';
		this.memory = env.store.kind === 'memory' ? (memoryChosen(plan, rec) ? 'chosen' : 'blocked') : null;
	}

	get saveMode(): SaveMode {
		return this.rec.saveMode;
	}
	get storageBlocked(): boolean {
		return this.env.store.kind === 'memory';
	}
	/** A save is on its way to the server (not waiting out a backoff while offline). */
	get saving(): boolean {
		return this.net === 'saving' || (this.pumping && this.net !== 'offline');
	}
	/** The end redirect a hook chose (declared template, filled and checked), if any. */
	get redirectUrl(): string | null {
		return this.phase === 'done' ? (this.hooks?.redirectUrl() ?? null) : null;
	}

	/** After boot: reconcile with the server (every-page resume), then run pending effects. */
	async run(): Promise<void> {
		if (this.phase === 'done') return;
		if (!this.reconciled) await this.resumeSync();
		else {
			await this.startHooks();
			await this.runEffects();
			void this.pump();
		}
	}

	view(): PageView {
		const v = E.view(this.state);
		if (!this.errorsHidden) return v;
		return {
			...v,
			errors: {},
			focus: v.focus === 'error-summary' ? 'heading' : v.focus,
			items: v.items.map((i) => (i.error ? { ...i, error: null } : i))
		};
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

	/** The participant moved to another page: one-off notices are done. */
	private moved(before: string) {
		if (`${E.view(this.state).page}#${this.state.data.history.length}` !== before) this.notice = null;
	}
	private where(): string {
		return `${E.view(this.state).page}#${this.state.data.history.length}`;
	}

	// -- participant actions ---------------------------------------------------------

	answer(itemId: string, value: unknown) {
		if (this.phase !== 'page') return;
		if (this.hooks) {
			// The runner applies the answer synchronously (onState commits it), then runs
			// `onAnswer` if the hook reads this question.
			void this.hooks.answer(itemId, value).then((o) => this.afterHook(o));
			return;
		}
		const next = E.answer(this.state, itemId, value);
		if (next === this.state) return;
		// R-1: with no local storage, every answer goes to the server straight away.
		this.commit(next, this.storageBlocked ? 'now' : 'debounce');
	}

	/**
	 * An input lost focus: save what was typed, after a moment. Focus usually leaves the last
	 * field for Next or Back; their save (with the page change) then replaces this one, so the
	 * server sees one write and a stale device learns of the conflict on that write (R6-6).
	 */
	blur() {
		if (!this.rec.snapshot || this.rec.snapshot.revision === this.rec.syncedEngineRev) return;
		if (this.saveMode !== 'every-page' || !this.reconciled || E.awaitingConsent(this.state)) return;
		// Say so at once: whoever waits for "Saved" (leaving for another device) waits for it.
		if (this.net !== 'offline') this.setNet('saving');
		this.scheduleSave(this.env.blurDelayMs ?? 250);
	}

	/** Submit the page. Resolves to the engine's outcome (`invalid`: focus the error summary). */
	async next(): Promise<E.StepResult['outcome'] | null> {
		if (this.phase !== 'page') return null;
		const before = this.where();
		this.errorsHidden = false;
		if (this.hooks) return this.nextWithHooks(before);
		const r = E.next(this.state);
		this.commit(r.state, 'now');
		this.moved(before);
		this.emit();
		if (r.effect) void this.runEffects();
		return r.result.outcome;
	}

	private async nextWithHooks(before: string): Promise<E.StepResult['outcome'] | null> {
		this.phase = 'hook';
		this.emit();
		let r: NextOutcome;
		try {
			r = await this.hooks!.next();
		} finally {
			if (this.phase === 'hook') this.phase = 'page';
		}
		this.moved(before);
		this.saveNow();
		this.emit();
		switch (r.outcome) {
			case 'invalid':
			case 'rejected':
				return 'invalid';
			case 'hook':
				this.afterHook(r.hook);
				return null;
			case 'effect':
			case 'ended':
				await this.runEffects();
				return r.outcome === 'ended' ? 'ended' : 'effect';
			default:
				return 'advanced';
		}
	}

	async back(): Promise<boolean> {
		if (this.phase !== 'page') return false;
		const before = this.where();
		if (this.hooks) {
			this.phase = 'hook';
			this.emit();
			let o: FireOutcome;
			try {
				o = await this.hooks.back();
			} finally {
				if (this.phase === 'hook') this.phase = 'page';
			}
			const moved = o.outcome !== 'refused';
			this.moved(before);
			this.saveNow();
			this.afterHook(o);
			this.emit();
			return moved;
		}
		const next = E.back(this.state);
		if (next === this.state) return false;
		this.errorsHidden = false;
		this.commit(next, 'now');
		this.moved(before);
		this.emit();
		return true;
	}

	/** The participant pressed "Try again" after a flow-critical hook failed. */
	async retryHook(): Promise<void> {
		if (!this.hooks || !this.hookRetry) return;
		this.hookRetry = false;
		this.phase = 'hook';
		this.emit();
		let o: FireOutcome;
		try {
			o = await this.hooks.retry();
		} finally {
			if (this.phase === 'hook') this.phase = 'page';
		}
		this.afterHook(o);
		this.saveNow();
		await this.runEffects();
	}

	/**
	 * The page is being hidden or unloaded: copy the newest snapshot synchronously, in case
	 * the asynchronous IndexedDB write has not landed. Never in memory-only mode (§5.0).
	 */
	flushLocalSync() {
		if (this.closed || this.storageBlocked || !this.rec.snapshot) return;
		this.env.backup?.write(this.rec.slug, this.rec.sessionId, this.rec.snapshot);
	}

	/** A clean unload (refresh, close): a hook in flight runs again on reload (§7a). */
	unloading() {
		this.hooks?.unloading();
	}

	/** The page is being hidden or unloaded: last-chance save with `keepalive`. */
	flushKeepalive() {
		if (this.saveMode !== 'every-page' || this.closed || !this.reconciled) return;
		if (E.awaitingConsent(this.state)) return; // §11: nothing before agreement
		const snap = this.rec.snapshot;
		if (!snap) return;
		if (!this.rec.inflight && snap.revision === this.rec.syncedEngineRev) return;
		// A save is on the wire (sent with keepalive): a duplicate would only arrive late as a
		// stale write and clutter the server's conflict log. But if the page has moved on
		// since (a refresh right after typing), chain the newest copy on the revision that
		// save will create, so the last keystrokes are not lost (R4-3, storage blocked).
		if (this.sending) {
			const wire = this.rec.inflight;
			if (wire && wire.snapshot.revision !== snap.revision && isPrefix(wire.snapshot, snap)) {
				this.env.api
					.save(this.rec.sessionId, this.rec.resumeToken, wire.base + 1, snap, { keepalive: true })
					.catch(() => undefined);
			}
			return;
		}
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

	// -- hooks (runtime-design §7a) ----------------------------------------------------

	/** The runner changed the state (an answer, next, back or a hook result): keep it. */
	private fromHooks(s: State) {
		if (s === this.state) return;
		this.commit(s, this.storageBlocked ? 'now' : 'debounce');
	}

	private async startHooks() {
		if (!this.plan.hooks || !this.env.hooks || this.hooks || this.closed) return;
		// No researcher code runs before the participant agrees (semantics §11).
		if (E.awaitingConsent(this.state)) return;
		try {
			this.hooks = await this.env.hooks(this.plan, this.state, (s) => this.fromHooks(s));
		} catch (e) {
			this.log('hooks unavailable', e);
			this.hooks = null;
			this.fail(ui.hooksFailed);
			return;
		}
		if (!this.hooks) return;
		this.phase = 'hook';
		this.emit();
		let o: FireOutcome;
		try {
			o = this.fresh ? await this.hooks.begin() : await this.hooks.resume();
		} finally {
			if (this.phase === 'hook') this.phase = 'page';
		}
		this.afterHook(o);
		this.saveNow();
		this.emit();
	}

	private afterHook(o: FireOutcome) {
		if (o.outcome === 'retry') {
			this.hookRetry = true;
			this.emit();
		} else if (o.outcome === 'hook-failed') {
			// The engine ended the session `hook-failed`: submit what there is.
			void this.runEffects();
		}
	}

	// -- network save (every-page) ----------------------------------------------------

	private scheduleSave(ms = this.env.debounceMs ?? 3000) {
		if (this.saveMode !== 'every-page') return;
		if (this.debounce !== null) this.env.clearTimer(this.debounce);
		this.debounce = this.env.setTimer(() => {
			this.debounce = null;
			void this.pump();
		}, ms);
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
			// Whatever the engine was waiting for in the adopted copy (a quota check, the end).
			if (!this.effectRunning) void this.runEffects();
			return true;
		}
		if (e instanceof HttpError && e.code === 'session.submitted') {
			// Submitted (perhaps from another tab): nothing more to save.
			this.rec.inflight = null;
			return false;
		}
		if (e instanceof HttpError && (e.status === 401 || e.status === 410)) {
			this.fail(ui.expiredSave);
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
		const conflict = !!local && !isPrefix(local, server);
		if (conflict) {
			this.rec.conflicts.push({ at: this.env.now(), serverRevision: rev, snapshot: sent ?? local! });
			this.log('conflict: kept the server copy, local copy kept for the record');
		}
		this.state = restored;
		this.hooks?.setState(restored);
		this.rec.snapshot = server;
		this.rec.serverRevision = rev;
		this.rec.syncedEngineRev = server.revision;
		this.errorsHidden = true;
		// R6-6: this device lost; it now shows the server's page and values, and says why.
		if (conflict) this.notice = 'conflict';
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
					this.fail(ui.expiredSave);
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
		await this.startHooks();
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
				// Idempotent per (session, node): a resend after a refresh or a lost reply gets
				// the result the server recorded the first time (R6-4).
				const r = await this.env.api.quota(this.rec.sessionId, this.rec.resumeToken, effect.nodeId);
				this.attempt = 0;
				if (this.saveMode === 'every-page') this.setNet(this.dirty() ? 'saving' : 'saved');
				const value = r.result === 'full' ? 'full' : 'open';
				const before = this.where();
				const next = E.resolve(this.state, effect, value);
				await this.commit(next, 'now');
				this.moved(before);
				if (this.hooks) {
					this.hooks.setState(next);
					const o = await this.hooks.arrive();
					this.afterHook(o);
				}
				return true;
			} catch (e) {
				if (!retryable(e)) {
					if (e instanceof HttpError && e.code === 'session.submitted') await this.finish();
					else this.fail(ui.quotaFailed);
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
			// `onBeforeSubmit` first: what it records (paradata, variables) is in the record.
			if (this.hooks) this.afterHook(await this.hooks.beforeSubmit());
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
					if (e instanceof HttpError && (e.status === 401 || e.status === 410)) this.fail(ui.expiredSubmit);
					else this.fail(ui.submitFailed);
					return;
				}
				this.setNet('offline');
				await this.sleep(this.backoff());
			}
		}
		await this.finish();
		// Side effects to external systems belong after the acknowledgement (§7a).
		if (this.hooks) void this.hooks.submitted().catch(() => undefined);
	}

	/** The server has the response: say thank you, delete the local copy, stop saving. */
	async finish() {
		this.closed = true;
		if (this.debounce !== null) this.env.clearTimer(this.debounce);
		this.wake();
		this.phase = 'done';
		this.notice = null;
		this.env.backup?.take(this.rec.slug, this.rec.sessionId);
		this.env.pointer?.clear(this.rec.slug);
		this.env.devicePointer?.clear(this.rec.slug);
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
		await this.startHooks(); // hooks start with the flow, after agreement (§11)
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
		this.rec.snapshot = E.snapshot(this.state); // in memory only: finish() deletes the copy
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
		this.hooks?.dispose();
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
		throw new BootError('plan', ui.planChecksum);
	}
	try {
		E.checkPlan(p);
	} catch {
		throw new BootError('plan', ui.planNewer);
	}
	return p;
}

function newRecord(slug: string, r: { sessionId: string; resumeToken: string; sessionSeed: number; assigned: Record<string, unknown>; planUrl: string; planChecksum: string; saveMode: SaveMode; localCopy?: 'browser' | 'memory' }, now: number): LocalRecord {
	return {
		slug,
		sessionId: r.sessionId,
		resumeToken: r.resumeToken,
		sessionSeed: r.sessionSeed,
		assigned: r.assigned as Record<string, string | number>,
		planUrl: r.planUrl,
		planChecksum: r.planChecksum,
		saveMode: r.saveMode,
		...(r.localCopy ? { localCopy: r.localCopy } : {}),
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
		language: sessionLanguage(plan, o),
		device: o.device ?? null,
		urlParams: o.urlParams ?? {},
		sessionId: rec.sessionId
	});
}

/**
 * R6-5: an end-only session whose only copy was in memory, after a refresh: the engine's
 * `restart()` of the original start (same seed, conditions, language, device, URL
 * parameters). Without the start event (sessionStorage blocked) the same is rebuilt from
 * the server's seed and conditions.
 */
function restartEngine(env: Env, plan: Plan, rec: LocalRecord, o: BootOptions, start: unknown): State {
	const ev = start as E.EngineEvent | undefined;
	if (ev && ev.type === 'start' && ev.sessionSeed === rec.sessionSeed && ev.sessionId === rec.sessionId) {
		const lost = E.replay(plan, [ev], { clock: env.now });
		if (E.isState(lost)) return E.restart(lost, { clock: env.now });
	}
	return E.restart(startEngine(env, plan, rec, o), { clock: env.now });
}

/**
 * The store this session keeps its copy in: the durable one, unless the survey chose
 * `localCopy: memory` (then nothing is kept beyond this window, §5.0).
 */
async function storeFor(env: Env, plan: Plan, rec: LocalRecord): Promise<Env> {
	if (env.store.kind === 'memory' || !memoryChosen(plan, rec)) return env;
	try {
		await env.store.delete(rec.slug);
	} catch {
		/* best effort */
	}
	return { ...env, store: new MemoryStore() };
}

/** No durable copy: remember where the session is, so a refresh can find it (R4-3). */
function remember(env: Env, rec: LocalRecord, state: State) {
	if (env.store.kind !== 'memory') return;
	const pointer = rec.saveMode === 'every-page' ? (env.devicePointer ?? env.pointer) : env.pointer;
	if (!pointer) return;
	const first = state.data.events[0];
	pointer.set(rec.slug, {
		sessionId: rec.sessionId,
		resumeToken: rec.resumeToken,
		...(rec.saveMode === 'end-only' && first?.type === 'start' ? { start: first } : {})
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

	// No local copy, no link: this tab may still know its session (memory-only, R4-3/R6-5).
	let pointerStart: unknown;
	let fromPointer = false;
	if (!rec && !o.resumeToken && (env.pointer || env.devicePointer)) {
		const p = env.pointer?.get(o.slug) ?? env.devicePointer?.get(o.slug) ?? null;
		if (p) {
			o = { ...o, resumeToken: p.resumeToken };
			pointerStart = p.start;
			fromPointer = true;
		}
	}

	// A resume link on a device without a local copy: the server copy is the truth.
	if (!rec && o.resumeToken) {
		let r: ResumeResponse;
		try {
			r = await withRetry(env, () => env.api.resume(o.resumeToken!));
		} catch (e) {
			if (fromPointer) {
				env.pointer?.clear(o.slug);
				env.devicePointer?.clear(o.slug);
			}
			throw bootError(e);
		}
		rec = newRecord(o.slug, { ...r, resumeToken: o.resumeToken }, env.now());
		await env.store.put(rec);
		const plan = await loadPlan(env, r.planUrl, r.planChecksum, null).catch((e) => Promise.reject(bootError(e)));
		rec.plan = plan;
		const senv = await storeFor(env, plan, rec);
		const server = asSnapshot(r.snapshot);
		let state: State;
		let restarted = false;
		if (server) {
			const restored = E.restore(plan, server, { clock: env.now });
			if (!E.isState(restored)) throw new BootError('invalid', ui.restoreFailed);
			state = restored;
			rec.snapshot = server;
			rec.syncedEngineRev = server.revision;
		} else if (fromPointer && rec.saveMode === 'end-only' && !r.submitted) {
			// The copy was in memory and the refresh lost it (R6-5).
			state = restartEngine(senv, plan, rec, o, pointerStart);
			rec.snapshot = E.snapshot(state);
			restarted = true;
		} else {
			state = startEngine(senv, plan, rec, o);
			rec.snapshot = E.snapshot(state);
		}
		rec.serverRevision = r.revision;
		await senv.store.put(rec);
		remember(senv, rec, state);
		const s = new Session(senv, rec, plan, state, true, !server);
		s.errorsHidden = !!server;
		if (restarted) s.notice = 'restarted';
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
		const senv = await storeFor(env, plan, rec);
		const state = startEngine(senv, plan, rec, o);
		rec.snapshot = E.snapshot(state);
		await senv.store.put(rec);
		remember(senv, rec, state);
		return new Session(senv, rec, plan, state, true, true);
	}

	// A local copy exists (refresh, tab killed, came back later).
	const plan = await loadPlan(env, rec.planUrl, rec.planChecksum, rec.plan).catch((e) => Promise.reject(bootError(e)));
	rec.plan = plan;
	const last = env.backup?.take(rec.slug, rec.sessionId) ?? null;
	if (last && (!rec.snapshot || (isPrefix(rec.snapshot, last) && last.data.events.length > rec.snapshot.data.events.length))) {
		rec.snapshot = last; // the pagehide copy is newer than the last IndexedDB write
	}
	let state: State;
	let restored = false;
	const local = rec.snapshot ? E.restore(plan, rec.snapshot, { clock: env.now }) : null;
	if (local && E.isState(local)) {
		state = local;
		restored = true;
	} else {
		state = startEngine(env, plan, rec, o);
		rec.snapshot = E.snapshot(state);
	}
	await env.store.put(rec);
	const s = new Session(env, rec, plan, state, rec.saveMode !== 'every-page', !restored);
	s.errorsHidden = restored;
	return s;
}
