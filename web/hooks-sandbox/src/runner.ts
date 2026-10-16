/**
 * Engine integration (runtime-design.md §7a "Rules"): every hook call is an engine `hook`
 * effect with an invocation id and the revision it saw; the outcome is checked by the host
 * (`validateActions`) and recorded with `resolve(state, effect, HookResolution)`.
 *
 * - Stale results (the state moved on while the hook ran) are refused and logged by the
 *   engine, never applied.
 * - Flow-critical hooks (they write a hook variable a condition reads) that fail get one
 *   retry prompt; a second failure ends the session with outcome `hook-failed`. They never
 *   silently take another path. Other hooks fail open.
 * - Everything is in the event log, so replay and verification never run hook code.
 * - Actions never trigger hooks, and calls are queued: one hook at a time.
 *
 * The runtime app (R3) drives the session through `begin/resume/answer/next/back/
 * beforeSubmit/submitted`, or calls `fire` itself and keeps `state` in step with `setState`.
 */

import {
	context,
	next as engineNext,
	nodeSeed,
	result,
	tryAnswer,
	tryBack,
	tryResolve,
	view,
	type EngineEvent,
	type HookAction,
	type HookEffect,
	type HookResolution,
	type Plan,
	type State
} from '@osp/engine';
import type { Invoker } from './host.ts';
import {
	DEFAULT_TIMEOUT_MS,
	buildRedirectUrl,
	checkManifest,
	criticalEvents,
	type HandlerDecl,
	type HookEvent,
	type HookManifest
} from './manifest.ts';
import { validateActions } from './validate.ts';

export class HookManifestError extends Error {
	constructor(readonly problems: string[]) {
		super(`invalid hook manifest: ${problems.join('; ')}`);
	}
}

export type FireOutcome =
	| { outcome: 'skipped' }
	| { outcome: 'ok'; actions: HookAction[]; diagnostics: string[] }
	| { outcome: 'failed-open'; error: string }
	| { outcome: 'stale' }
	| { outcome: 'refused'; reason: string }
	/** A flow-critical hook failed: show a retry prompt, then call `retry()`. */
	| { outcome: 'retry'; event: HookEvent; error: string }
	/** A flow-critical hook failed after its retry: the session ended `hook-failed`. */
	| { outcome: 'hook-failed'; error: string };

export type NextOutcome =
	| { outcome: 'advanced' | 'ended' | 'invalid' | 'rejected' | 'effect' }
	| { outcome: 'hook'; hook: Extract<FireOutcome, { outcome: 'retry' | 'hook-failed' }> };

export interface ParentMessage {
	source: 'osp-hooks';
	type: string;
	payload: unknown;
}

/**
 * The hook call in flight, persisted (synchronously, next to the snapshot) so a tab that
 * dies mid-hook (e.g. the renderer crashed on a hook's memory use) can tell on reload.
 */
export interface InflightMarker {
	invocationId: string;
	event: HookEvent;
	data: unknown;
	retry: boolean;
}
export interface InflightStore {
	get(): InflightMarker | null;
	set(m: InflightMarker | null): void;
}

export const CRASHED = 'crashed';

export interface HookRunnerOptions {
	plan: Plan;
	manifest: HookManifest;
	invoker: Invoker;
	state: State;
	/** Called after every state change (persist the snapshot here). */
	onState?: (state: State) => void;
	/** Delivers an accepted `postToParent`. Default: `window.parent.postMessage(msg, origin)`. */
	deliverToParent?: (origin: string, msg: ParentMessage) => void;
	/** Where the in-flight marker lives (crash recovery in `resume`). */
	inflight?: InflightStore;
}

function defaultDeliver(origin: string, msg: ParentMessage): void {
	if (typeof window === 'undefined' || !window.parent || window.parent === window) return;
	window.parent.postMessage(msg, origin);
}

const clone = <T>(x: T): T => JSON.parse(JSON.stringify(x)) as T;

function pick<V>(rec: Record<string, V>, keep: Set<string>): Record<string, V> {
	const out: Record<string, V> = {};
	for (const [k, v] of Object.entries(rec)) if (keep.has(k)) out[k] = v;
	return out;
}

/** Index just after the last event that moved to a new page (or the end). */
function lastArrival(events: EngineEvent[]): number {
	for (let i = events.length - 1; i >= 0; i--) {
		const e = events[i]!;
		if (e.rejected !== undefined) continue;
		if (e.type === 'start' || e.type === 'back') return i + 1;
		if ((e.type === 'next' || e.type === 'resolve') && e.result && e.result.outcome !== 'invalid') return i + 1;
	}
	return 0;
}

function recorded(events: EngineEvent[], event: HookEvent, from = 0): boolean {
	for (let i = from; i < events.length; i++) {
		const e = events[i]!;
		if (e.type === 'resolve' && e.rejected === undefined && e.effect.kind === 'hook' && e.effect.event === event) return true;
	}
	return false;
}

export class HookRunner {
	readonly plan: Plan;
	readonly manifest: HookManifest;
	readonly critical: Set<HookEvent>;
	private readonly invoker: Invoker;
	private readonly onState?: (s: State) => void;
	private readonly deliver: (origin: string, msg: ParentMessage) => void;
	private readonly inflight?: InflightStore;
	private current: State;
	private chain: Promise<unknown> = Promise.resolve();
	private retryPending: { event: HookEvent; data: unknown } | null = null;
	private submitting: Promise<FireOutcome> | null = null;
	private submittedOnce: Promise<FireOutcome> | null = null;

	constructor(opts: HookRunnerOptions) {
		const problems = checkManifest(opts.plan, opts.manifest);
		if (problems.length) throw new HookManifestError(problems);
		this.plan = opts.plan;
		this.manifest = opts.manifest;
		this.invoker = opts.invoker;
		this.current = opts.state;
		this.onState = opts.onState;
		this.deliver = opts.deliverToParent ?? defaultDeliver;
		this.inflight = opts.inflight;
		this.critical = criticalEvents(opts.plan, opts.manifest);
	}

	get state(): State {
		return this.current;
	}

	/** Keep the runner in step when the runtime changes the state itself (e.g. a quota). */
	setState(s: State): void {
		this.current = s;
		this.onState?.(s);
	}

	/** Resolves when every queued hook has finished. */
	idle(): Promise<void> {
		return this.chain.then(() => undefined);
	}

	/** Queue a hook call for `event`. Skipped when the manifest has no handler for it. */
	fire(event: HookEvent, data: unknown = {}): Promise<FireOutcome> {
		return this.enqueue(() => this.fireNow(event, data, false));
	}

	/** After a `retry` outcome: run that hook again. A second failure ends `hook-failed`. */
	retry(): Promise<FireOutcome> {
		const p = this.retryPending;
		if (!p) return Promise.resolve({ outcome: 'skipped' });
		this.retryPending = null;
		return this.enqueue(() => this.fireNow(p.event, p.data, true));
	}

	get awaitingRetry(): HookEvent | null {
		return this.retryPending?.event ?? null;
	}

	/** The declared end redirect the hooks chose, filled and checked; null if none. */
	redirectUrl(): string | null {
		return buildRedirectUrl(this.manifest, this.current.data.hooks?.redirect ?? null);
	}

	/**
	 * Call from `pagehide`: a clean unload (refresh, close) clears the in-flight marker, so
	 * `resume` simply runs the interrupted hook again. A marker that survives means the page
	 * died (crash, killed tab) and `resume` treats the hook as failed instead.
	 */
	unloading(): void {
		this.inflight?.set(null);
	}

	dispose(): void {
		this.invoker.dispose();
	}

	// --- Session flow ------------------------------------------------------------------

	/** A new session: `onStart` (declared URL parameters only), then the first page. */
	async begin(): Promise<FireOutcome> {
		const declared = new Set(this.manifest.urlParams ?? []);
		const r = await this.fire('onStart', { urlParams: pick(this.current.data.urlParams, declared) });
		if (r.outcome === 'retry' || r.outcome === 'hook-failed') return r;
		return this.arrive();
	}

	/**
	 * After a refresh or on another device: `onResume`, then `onPageInit` again if the
	 * current page's one never got recorded (e.g. the refresh came mid-hook), then
	 * `onPageShown`.
	 */
	async resume(): Promise<FireOutcome> {
		const crash = await this.enqueue(() => this.recoverCrash());
		if (crash.outcome === 'retry' || crash.outcome === 'hook-failed') return crash;
		const r = await this.fire('onResume', {});
		if (r.outcome === 'retry' || r.outcome === 'hook-failed') return r;
		const s = this.current;
		if (s.data.ended) return recorded(s.data.events, 'onBeforeSubmit') ? r : this.beforeSubmit();
		if (!recorded(s.data.events, 'onPageInit', lastArrival(s.data.events))) return this.arrive();
		return this.pageShown();
	}

	/** Answer a question; fires `onAnswer` if the hook declares it reads that question. */
	answer(itemId: string, value: unknown): Promise<FireOutcome> {
		const before = this.current.data.values[itemId] ?? null;
		const r = tryAnswer(this.current, itemId, value);
		if (r.rejected) return Promise.resolve({ outcome: 'refused', reason: r.rejected });
		this.setState(r.state);
		if (!this.manifest.handlers.onAnswer?.reads.includes(itemId)) return Promise.resolve({ outcome: 'skipped' });
		const after = r.state.data.values[itemId] ?? null;
		return this.fire('onAnswer', { itemId, value: after, oldValue: before });
	}

	/** Submit the page: `onPageNext` (may reject), engine `next`, then the next page's hooks. */
	async next(): Promise<NextOutcome> {
		await this.idle();
		if (this.retryPending) return { outcome: 'hook', hook: { outcome: 'retry', event: this.retryPending.event, error: 'pending' } };
		const s = this.current;
		if (s.data.ended) return { outcome: 'ended' };
		if (s.data.pending) return { outcome: 'effect' };
		const pn = await this.fire('onPageNext', { page: view(s).page });
		if (pn.outcome === 'retry' || pn.outcome === 'hook-failed') return { outcome: 'hook', hook: pn };
		if (pn.outcome === 'ok' && pn.actions.some((a) => a.kind === 'rejectPage')) return { outcome: 'rejected' };
		const r = engineNext(this.current);
		this.setState(r.state);
		if (r.result.outcome === 'invalid') {
			const errors = Object.entries(view(r.state).errors).map(([itemId, e]) => ({ itemId, kind: e.kind }));
			await this.fire('onValidationError', { errors });
			return { outcome: 'invalid' };
		}
		if (r.result.outcome === 'effect') return { outcome: 'effect' };
		const a = await this.arrive();
		if (a.outcome === 'retry' || a.outcome === 'hook-failed') return { outcome: 'hook', hook: a };
		return { outcome: r.result.outcome === 'ended' ? 'ended' : 'advanced' };
	}

	/** Go back: engine `back`, `onBack`, then the page's hooks. Returns `onBack`'s outcome. */
	async back(): Promise<FireOutcome> {
		await this.idle();
		const from = view(this.current).page;
		const r = tryBack(this.current);
		if (r.rejected) return { outcome: 'refused', reason: r.rejected };
		this.setState(r.state);
		const b = await this.fire('onBack', { from });
		if (b.outcome === 'retry' || b.outcome === 'hook-failed') return b;
		const a = await this.arrive();
		return a.outcome === 'retry' || a.outcome === 'hook-failed' ? a : b;
	}

	/**
	 * After the state moved to a new page or the end outside the runner (e.g. R3 resolved a
	 * quota): `onPageInit` + `onPageShown`, or `onBeforeSubmit` at the end.
	 */
	async arrive(): Promise<FireOutcome> {
		const s = this.current;
		if (s.data.ended) return this.beforeSubmit();
		if (view(s).status !== 'page') return { outcome: 'skipped' };
		const init = await this.fire('onPageInit', { page: view(s).page });
		if (init.outcome === 'retry' || init.outcome === 'hook-failed') return init;
		return this.pageShown();
	}

	private pageShown(): Promise<FireOutcome> {
		const s = this.current;
		const v = view(s);
		const page = v.page;
		const choices: Record<string, unknown> = {};
		for (const it of v.items) if (s.data.orders.choices[it.id]) choices[it.id] = s.data.orders.choices[it.id];
		return this.fire('onPageShown', {
			page,
			visibleItems: v.items.map((i) => i.id),
			orders: { items: page ? (s.data.orders.items[page] ?? null) : null, choices }
		});
	}

	/** `onBeforeSubmit`, once per session however often it is called. Then submit `result(state)`. */
	beforeSubmit(): Promise<FireOutcome> {
		if (this.submitting) return this.submitting;
		if (recorded(this.current.data.events, 'onBeforeSubmit')) return Promise.resolve({ outcome: 'skipped' });
		this.submitting = this.enqueue(() => {
			if (recorded(this.current.data.events, 'onBeforeSubmit')) return Promise.resolve({ outcome: 'skipped' } as FireOutcome);
			return this.fireNow('onBeforeSubmit', { record: this.filteredRecord() }, false);
		}).finally(() => {
			this.submitting = null;
		});
		return this.submitting;
	}

	/** After the server acknowledged the submit: `onSubmitted`, once. */
	submitted(): Promise<FireOutcome> {
		if (!this.submittedOnce) {
			this.submittedOnce = recorded(this.current.data.events, 'onSubmitted')
				? Promise.resolve({ outcome: 'skipped' })
				: this.fire('onSubmitted', {});
		}
		return this.submittedOnce;
	}

	// --- Internals ---------------------------------------------------------------------

	/**
	 * The previous page died while a hook ran (its result never got recorded). Record that
	 * as a failure, never re-run it blindly: a non-critical hook is switched off for the rest
	 * of the session; a flow-critical one gets its retry prompt, and a crash on the retry
	 * ends the session `hook-failed`.
	 */
	private async recoverCrash(): Promise<FireOutcome> {
		const m = this.inflight?.get() ?? null;
		if (!m) return { outcome: 'skipped' };
		this.inflight!.set(null);
		const events = this.current.data.events;
		const done = events.some((e) => e.type === 'resolve' && e.effect.kind === 'hook' && e.effect.invocationId === m.invocationId && e.rejected === undefined);
		if (done || !this.manifest.handlers[m.event]) return { outcome: 'skipped' };
		const critical = this.critical.has(m.event);
		const s = this.current;
		if (s.data.ended && m.event !== 'onBeforeSubmit' && m.event !== 'onSubmitted') return { outcome: 'skipped' };
		const revision = s.data.revision;
		const effect: HookEffect = { kind: 'hook', invocationId: `${m.event}@${revision}`, event: m.event, revision };
		const status = critical && (m.retry || this.failedOnThisPage(m.event)) ? 'fatal' : 'failed';
		const r = tryResolve(s, effect, { status, actions: [], seed: 0, now: this.now(s), error: CRASHED });
		this.setState(r.state);
		if (r.rejected) return { outcome: 'refused', reason: r.rejected };
		if (status === 'fatal') return { outcome: 'hook-failed', error: CRASHED };
		if (critical) {
			this.retryPending = { event: m.event, data: m.data };
			return { outcome: 'retry', event: m.event, error: CRASHED };
		}
		return { outcome: 'failed-open', error: CRASHED };
	}

	/** Events whose non-critical hook crashed the page earlier in this session. */
	private crashed(event: HookEvent): boolean {
		return this.current.data.events.some(
			(e) =>
				e.type === 'resolve' &&
				e.rejected === undefined &&
				e.effect.kind === 'hook' &&
				e.effect.event === event &&
				(e.value as HookResolution | null)?.error === CRASHED
		);
	}

	private now(s: State): number {
		try {
			const t = Number(s.clock());
			return Number.isFinite(t) ? t : 0;
		} catch {
			return 0;
		}
	}

	private enqueue(f: () => Promise<FireOutcome>): Promise<FireOutcome> {
		const run = this.chain.then(f);
		this.chain = run.catch(() => undefined);
		return run;
	}

	/** `ctx` limited to the hook's declared reads (§7a "Declared reads"). */
	private ctxFor(state: State, decl: HandlerDecl) {
		const c = context(state);
		const reads = new Set(decl.reads);
		return clone({ ...c, results: pick(c.results, reads), vars: pick(c.vars, reads) });
	}

	/** The ResponseRecord limited to declared reads; no event log, no undeclared URL params. */
	private filteredRecord() {
		const r = result(this.current);
		const reads = new Set(this.manifest.handlers.onBeforeSubmit?.reads ?? []);
		const names = new Set<string>();
		for (const id of reads) {
			const it = this.plan.items[id];
			if (it && it.type !== 'note') names.add(`${it.name}__state`);
		}
		const { events: _events, ...rest } = r;
		void _events;
		return clone({
			...rest,
			answers: pick(r.answers, reads),
			csvState: pick(r.csvState, names),
			embedded: pick(r.embedded, reads),
			computed: pick(r.computed, reads),
			urlParams: pick(r.urlParams, new Set(this.manifest.urlParams ?? [])),
			hooks: r.hooks ? { ...r.hooks, vars: pick(r.hooks.vars, reads) } : undefined
		});
	}

	/**
	 * Did this event's hook already fail on the current page visit? Then this call is its
	 * retry, also after a reload (the retry allowance is in the log, not in memory).
	 */
	private failedOnThisPage(event: HookEvent): boolean {
		const events = this.current.data.events;
		for (let i = lastArrival(events); i < events.length; i++) {
			const e = events[i]!;
			if (e.type === 'resolve' && e.rejected === undefined && e.effect.kind === 'hook' && e.effect.event === event && (e.value as HookResolution | null)?.status === 'failed') return true;
		}
		return false;
	}

	private async fireNow(event: HookEvent, data: unknown, isRetryCall: boolean): Promise<FireOutcome> {
		const decl = this.manifest.handlers[event];
		if (!decl) return { outcome: 'skipped' };
		const s0 = this.current;
		if (s0.data.ended && event !== 'onBeforeSubmit' && event !== 'onSubmitted') return { outcome: 'skipped' };
		const critical = this.critical.has(event);
		if (!critical && this.crashed(event)) return { outcome: 'skipped' };
		const isRetry = isRetryCall || (critical && this.failedOnThisPage(event));
		const revision = s0.data.revision;
		const effect: HookEffect = { kind: 'hook', invocationId: `${event}@${revision}`, event, revision };
		const seed = nodeSeed(this.plan.survey.seedVersion, s0.data.sessionSeed, `hook:${effect.invocationId}`);
		const now = this.now(s0);
		this.inflight?.set({ invocationId: effect.invocationId, event, data: clone(data), retry: isRetry });
		let out;
		try {
			out = await this.invoker.invoke({
				invocationId: effect.invocationId,
				event,
				ctx: this.ctxFor(s0, decl),
				data: clone(data),
				seed,
				now,
				timeoutMs: decl.timeoutMs ?? DEFAULT_TIMEOUT_MS
			});
		} catch (e) {
			out = { status: 'error' as const, error: e instanceof Error ? e.message.slice(0, 80) : 'error' };
		}
		const s1 = this.current;
		let resolution: HookResolution;
		let failure: string | null = null;
		let diagnostics: string[] = [];
		if (out.status === 'ok') {
			const v = validateActions(out.actions, { plan: this.plan, manifest: this.manifest, event, state: s1 });
			diagnostics = v.diagnostics;
			if (v.refused) failure = v.refused;
			else if (critical && v.diagnostics.length) failure = 'invalid-actions';
			resolution = { status: 'ok', actions: v.actions, seed, now };
		} else {
			failure = `${out.status}:${out.error}`.slice(0, 120);
			resolution = { status: 'failed', actions: [], seed, now };
		}
		if (failure) resolution = { status: critical && isRetry ? 'fatal' : 'failed', actions: [], seed, now, error: failure };
		if (diagnostics.length) resolution.diagnostics = diagnostics;
		const r = tryResolve(s1, effect, resolution);
		this.setState(r.state);
		this.inflight?.set(null);
		if (r.rejected === 'stale') return { outcome: 'stale' };
		if (r.rejected) return { outcome: 'refused', reason: r.rejected };
		if (resolution.status === 'fatal') return { outcome: 'hook-failed', error: failure ?? 'failed' };
		if (failure && critical) {
			this.retryPending = { event, data };
			return { outcome: 'retry', event, error: failure };
		}
		if (failure) return { outcome: 'failed-open', error: failure };
		const origin = this.manifest.parent?.origin;
		for (const a of resolution.actions) {
			if (a.kind === 'postToParent' && origin) {
				try {
					this.deliver(origin, { source: 'osp-hooks', type: a.type, payload: clone(a.payload) });
				} catch {
					/* delivery is best effort; the message is in the event log */
				}
			}
		}
		return { outcome: 'ok', actions: resolution.actions, diagnostics };
	}
}
