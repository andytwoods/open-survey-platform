/**
 * The survey store and op client (builder-design §4). It holds the draft JSON, its
 * revision and diagnostics, and is the only thing that sends edits.
 *
 * - `submit(ops)` is one user gesture = one transaction (a drag or a bulk paste is one
 *   call with many ops, so it is one undo step). Items are queued and sent one at a time,
 *   each against the latest revision.
 * - 200: the server's RFC 6902 patch is applied to the local copy (refetch if it doesn't
 *   apply). 422: nothing changed; the diagnostics are surfaced. 409: refetch, then replay
 *   the pending ops; if the server now rejects them, show the conflict banner.
 * - Network failures keep the item queued and retry with backoff; the transaction id
 *   makes a retry of a request that did land a no-op (the server says `replayed`).
 * - Undo/redo call the API's undo/redo with transaction ids from this session's stacks.
 * - 401 (the host session ended, planning/pages-split.md D9): the item stays queued and
 *   sending stops until `resume()`; nothing pending is dropped.
 *
 * No survey logic lives here: the server validates and applies every op.
 */
import { applyPatch } from './json-patch';
import type { Diagnostic, EditResult, Invocation, Result, SurveyDoc, SurveyTransport } from './transport';

export type SaveState = 'loading' | 'saved' | 'saving' | 'offline' | 'conflict' | 'error' | 'signed-out';

export type Outcome =
	| { status: 'applied'; result: EditResult }
	| { status: 'rejected'; message: string; diagnostics: Diagnostic[] }
	| { status: 'conflict'; message: string }
	| { status: 'dropped'; message: string };

export interface Rejection {
	message: string;
	diagnostics: Diagnostic[];
}

interface OpsItem {
	kind: 'ops';
	ops: Invocation[];
	txnId: string;
	/** Set after a 409: this item is being replayed onto a newer revision. */
	replay: boolean;
	attempts: number;
	resolve: (o: Outcome) => void;
}

interface ReverseItem {
	kind: 'undo' | 'redo';
	/** The transaction to reverse, taken off its stack when the item is first sent. */
	txn: string | null;
	attempts: number;
	resolve: (o: Outcome) => void;
}

type Item = OpsItem | ReverseItem;

export interface Flushable {
	flush(): void;
}

export interface SurveyStoreOptions {
	transport: SurveyTransport;
	newTransactionId?: () => string;
	sleep?: (ms: number) => Promise<void>;
	/** Backoff before retrying after a network failure (last value repeats). */
	retryDelays?: readonly number[];
	/** Give up on an item after this many consecutive 409s. */
	maxConflictRetries?: number;
	onUnauthenticated?: () => void;
}

function defaultTxnId(): string {
	if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
	return `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}

export class SurveyStore {
	surveyId = $state('');
	/** Title from the survey list/detail; the model's own title wins once loaded. */
	title = $state('');
	survey = $state.raw<SurveyDoc | null>(null);
	revision = $state(0);
	diagnostics = $state.raw<Diagnostic[]>([]);
	/** The last rejected edit (422), until the next successful one or `clearRejection`. */
	rejection = $state.raw<Rejection | null>(null);
	conflict = $state.raw<{ message: string } | null>(null);
	offline = $state(false);
	/** Load failure or a non-retryable error. */
	error = $state<string | null>(null);
	loading = $state(false);
	/** Queued items (ops, undo, redo) not yet answered. */
	pending = $state(0);
	/** A 401 stopped sending: the queue is kept until `resume()`. */
	paused = $state(false);
	#resume: (() => void) | null = null;
	#dirty = $state(0);
	#undo = $state<string[]>([]);
	#redo = $state<string[]>([]);

	#queue: Item[] = [];
	#draining: Promise<void> | null = null;
	// Not reactive: only iterated on flush.
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	#buffers = new Set<Flushable>();
	readonly #t: SurveyTransport;
	readonly #newTxn: () => string;
	readonly #sleep: (ms: number) => Promise<void>;
	readonly #delays: readonly number[];
	readonly #maxConflicts: number;
	readonly #onUnauth: () => void;

	constructor(o: SurveyStoreOptions) {
		this.#t = o.transport;
		this.#newTxn = o.newTransactionId ?? defaultTxnId;
		this.#sleep = o.sleep ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
		this.#delays = o.retryDelays ?? [1000, 2000, 4000, 8000, 15000];
		this.#maxConflicts = o.maxConflictRetries ?? 5;
		this.#onUnauth = o.onUnauthenticated ?? (() => {});
	}

	get canUndo(): boolean {
		return this.#undo.length > 0;
	}
	get canRedo(): boolean {
		return this.#redo.length > 0;
	}
	/** Transaction ids on the undo stack, oldest first (read-only view, for tests). */
	get undoStack(): readonly string[] {
		return this.#undo;
	}
	get redoStack(): readonly string[] {
		return this.#redo;
	}

	get saveState(): SaveState {
		if (this.loading && !this.survey) return 'loading';
		if (this.paused) return 'signed-out';
		if (this.conflict) return 'conflict';
		if (this.offline) return 'offline';
		if (this.pending > 0 || this.#dirty > 0) return 'saving';
		if (this.error) return 'error';
		return 'saved';
	}

	// -- loading ------------------------------------------------------------------------

	async load(surveyId: string): Promise<boolean> {
		this.surveyId = surveyId;
		this.loading = true;
		this.error = null;
		try {
			const r = await this.#t.load(surveyId);
			if (r.kind !== 'ok') {
				this.#fail(r);
				return false;
			}
			this.title = r.data.title;
			this.survey = r.data.survey;
			this.revision = r.data.revision;
			if (r.data.diagnostics) this.diagnostics = r.data.diagnostics;
			return true;
		} finally {
			this.loading = false;
		}
	}

	/** Fetch the latest draft (after a 409, a replayed retry or an unappliable patch). */
	async #refetch(): Promise<Result<unknown>> {
		const r = await this.#t.load(this.surveyId);
		if (r.kind === 'ok') {
			this.title = r.data.title;
			this.survey = r.data.survey;
			this.revision = r.data.revision;
			if (r.data.diagnostics) this.diagnostics = r.data.diagnostics;
		}
		return r;
	}

	// -- text buffers -----------------------------------------------------------------

	/** Register a text buffer so undo and navigation flush it first. */
	registerBuffer(b: Flushable): () => void {
		this.#buffers.add(b);
		return () => this.#buffers.delete(b);
	}

	/** For TextBuffer's onDirty: counts buffers holding unsent text ("saving"). */
	markDirty(dirty: boolean) {
		this.#dirty = Math.max(0, this.#dirty + (dirty ? 1 : -1));
	}

	flushBuffers() {
		for (const b of [...this.#buffers]) b.flush();
	}

	/** Edits queued or buffered and not yet acknowledged (the page's leave guard). */
	get unsaved(): boolean {
		return this.pending > 0 || this.#dirty > 0;
	}

	/** Send again after a 401 paused the queue (e.g. the host session is back). */
	resume() {
		const r = this.#resume;
		this.#resume = null;
		this.paused = false;
		r?.();
	}

	// -- edits ------------------------------------------------------------------------

	/** Send one gesture's ops as one transaction. Resolves when the server has answered. */
	submit(ops: Invocation[]): Promise<Outcome> {
		if (!ops.length) return Promise.resolve({ status: 'dropped', message: 'No change.' });
		return this.#enqueue((resolve) => ({
			kind: 'ops',
			ops,
			txnId: this.#newTxn(),
			replay: false,
			attempts: 0,
			resolve
		}));
	}

	undo(): Promise<Outcome> {
		this.flushBuffers();
		return this.#enqueue((resolve) => ({ kind: 'undo', txn: null, attempts: 0, resolve }));
	}

	redo(): Promise<Outcome> {
		this.flushBuffers();
		return this.#enqueue((resolve) => ({ kind: 'redo', txn: null, attempts: 0, resolve }));
	}

	clearRejection() {
		this.rejection = null;
	}

	/** Dismiss the conflict banner (the draft shown is already the server's latest). */
	dismissConflict() {
		this.conflict = null;
	}

	/** Reload from the server (conflict banner's "Reload"). */
	async reload(): Promise<void> {
		await this.settled();
		this.conflict = null;
		const r = await this.#refetch();
		if (r.kind !== 'ok') this.#fail(r);
		else this.error = null;
	}

	/** Resolves when every queued item has been answered. */
	async settled(): Promise<void> {
		while (this.#draining) await this.#draining;
	}

	/** Like `settled`, but also resolves while a 401 has paused the queue (no progress possible). */
	async settledOrPaused(): Promise<void> {
		if (this.paused || !this.#draining) return;
		await new Promise<void>((resolve) => {
			const tick = () => (this.paused || !this.#draining ? resolve() : setTimeout(tick, 50));
			tick();
		});
	}

	/** A 401 on a write: keep the item, stop sending until `resume()`. */
	async #pause(): Promise<null> {
		this.offline = false;
		this.paused = true;
		this.#onUnauth();
		await new Promise<void>((r) => (this.#resume = r));
		return null;
	}

	#enqueue(make: (resolve: (o: Outcome) => void) => Item): Promise<Outcome> {
		return new Promise<Outcome>((resolve) => {
			this.#queue.push(make(resolve));
			this.pending = this.#queue.length;
			if (!this.#draining) this.#draining = this.#drain();
		});
	}

	async #drain() {
		// `#draining` is cleared synchronously when the loop sees an empty queue, so an
		// item enqueued by a continuation of the last resolve always starts a new drain.
		for (;;) {
			if (!this.#queue.length) {
				this.#draining = null;
				return;
			}
			const item = this.#queue[0];
			const out = item.kind === 'ops' ? await this.#sendOps(item) : await this.#sendReverse(item);
			if (out === null) continue; // retry
			if (this.#queue[0] === item) this.#queue.shift();
			this.pending = this.#queue.length;
			item.resolve(out);
		}
	}

	async #backoff(item: Item) {
		const d = this.#delays;
		await this.#sleep(d[Math.min(item.attempts, d.length - 1)] ?? 1000);
		item.attempts++;
	}

	/** Accept a successful edit: apply its patch (or refetch). */
	async #accept(data: EditResult) {
		this.offline = false;
		this.error = null;
		if (data.replayed) {
			// A retry of a request that had landed: the patch is empty, so refetch.
			await this.#refetch();
			return;
		}
		if (data.patch.length) {
			try {
				this.survey = applyPatch(this.survey, data.patch);
			} catch {
				const r = await this.#refetch();
				if (r.kind === 'ok') {
					this.diagnostics = data.diagnostics;
					return;
				}
			}
		}
		this.revision = data.revision;
		this.diagnostics = data.diagnostics;
	}

	/** 409 / offline, shared by both item kinds. Returns null to retry the item. */
	async #retryable(item: Item, r: Result<unknown>): Promise<Outcome | null> {
		if (r.kind === 'offline') {
			this.offline = true;
			await this.#backoff(item);
			return null;
		}
		// 409: refetch, then send again against the new revision.
		item.attempts++;
		if (item.attempts > this.#maxConflicts) {
			return this.#enterConflict('The survey keeps changing elsewhere; your change was not applied.');
		}
		const f = await this.#refetch();
		if (f.kind === 'offline') {
			this.offline = true;
			await this.#backoff(item);
		} else if (f.kind !== 'ok') {
			this.#fail(f);
			const out: Outcome = { status: 'dropped', message: f.message };
			this.#dropAll(out);
			return out;
		}
		for (const q of this.#queue) if (q.kind === 'ops') q.replay = true;
		return null;
	}

	async #sendOps(item: OpsItem): Promise<Outcome | null> {
		const r = await this.#t.applyOps(this.surveyId, {
			ops: item.ops,
			baseRevision: this.revision,
			transactionId: item.txnId
		});
		switch (r.kind) {
			case 'ok':
				await this.#accept(r.data);
				this.rejection = null;
				if (r.data.transactionId) {
					this.#undo = [...this.#undo, r.data.transactionId];
					this.#redo = [];
				}
				return { status: 'applied', result: r.data };
			case 'rejected':
				this.offline = false;
				if (item.replay) {
					// Someone else's change makes ours invalid: banner, drop what's pending.
					return this.#enterConflict(
						'This survey was changed elsewhere, and your pending change no longer applies. You are now seeing the latest version.',
						r.diagnostics
					);
				}
				this.rejection = { message: r.message, diagnostics: r.diagnostics };
				return { status: 'rejected', message: r.message, diagnostics: r.diagnostics };
			case 'error':
				if (r.status === 401) return this.#pause();
				this.offline = false;
				this.#fail(r);
				return { status: 'dropped', message: r.message };
			default:
				return this.#retryable(item, r);
		}
	}

	async #sendReverse(item: ReverseItem): Promise<Outcome | null> {
		const undo = item.kind === 'undo';
		if (item.txn === null) {
			const stack = undo ? this.#undo : this.#redo;
			const txn = stack.at(-1);
			if (txn === undefined) {
				return { status: 'dropped', message: undo ? 'Nothing to undo.' : 'Nothing to redo.' };
			}
			item.txn = txn;
			if (undo) this.#undo = this.#undo.slice(0, -1);
			else this.#redo = this.#redo.slice(0, -1);
		}
		const body = { transactionId: item.txn, baseRevision: this.revision };
		const r = undo ? await this.#t.undo(this.surveyId, body) : await this.#t.redo(this.surveyId, body);
		switch (r.kind) {
			case 'ok':
				await this.#accept(r.data);
				this.rejection = null;
				if (r.data.transactionId) {
					if (undo) this.#redo = [...this.#redo, r.data.transactionId];
					else this.#undo = [...this.#undo, r.data.transactionId];
				}
				return { status: 'applied', result: r.data };
			case 'rejected':
				this.offline = false;
				this.rejection = { message: r.message, diagnostics: r.diagnostics };
				return { status: 'rejected', message: r.message, diagnostics: r.diagnostics };
			case 'error':
				if (r.status === 401) return this.#pause();
				this.offline = false;
				return { status: 'dropped', message: r.message };
			default:
				return this.#retryable(item, r);
		}
	}

	#enterConflict(message: string, diagnostics: Diagnostic[] = []): Outcome {
		this.conflict = { message };
		if (diagnostics.length) this.rejection = { message, diagnostics };
		const out: Outcome = { status: 'conflict', message };
		this.#dropAll(out);
		return out;
	}

	#dropAll(outcome: Outcome) {
		const items = this.#queue.splice(0);
		for (const q of items) q.resolve(outcome);
		this.pending = 0;
	}

	#fail(r: Exclude<Result<unknown>, { kind: 'ok' }>) {
		this.error = r.message;
		if (r.kind === 'error' && r.status === 401) this.#onUnauth();
	}
}
