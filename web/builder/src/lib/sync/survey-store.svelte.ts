/**
 * The survey store (builder-design §4, planning/client-edits.md CE5). It holds the draft
 * JSON, its revision and diagnostics, applies every edit in the browser and saves it.
 *
 * - `submit(ops)` is one user gesture = one transaction (a drag or a bulk paste is one call
 *   with many ops, so it is one undo step). It runs the ops locally with `@osp/ops`
 *   (`applyTransaction`: the same ops, errors, patches and inverses as the server's
 *   osp-ops) and shows the result at once (optimistic). A local rejection changes nothing
 *   and is surfaced like a server one. The diagnostics shown are `@osp/spec`'s for the
 *   local document, replaced by the server's when the save lands (server wins).
 * - Saves queue in order: each sends the JSON Patch from the last saved document to its
 *   own (`PUT …/draft` via `SurveyTransport.saveDraft`), with the op names for the audit
 *   log and a transaction id that makes a retry of a save that landed a no-op (`replayed`).
 * - 409 (someone else saved): refetch, re-run every pending transaction's ops on the newer
 *   draft (rebase) and save again; if they no longer apply, show the conflict banner with
 *   the latest draft. 422 (the server refuses the document): roll the change back, re-run
 *   the later pending ones without it, and show the diagnostics as a rejection.
 * - Network failures keep the save queued and retry with backoff (offline). 401 (the host
 *   session ended, planning/pages-split.md D9): saving stops until `resume()`; nothing
 *   pending is dropped.
 * - Undo/redo are local: each transaction's inverse (from @osp/ops) is kept on this page
 *   load's stacks; undoing applies it like any edit and saves it as a normal draft PUT.
 *
 * No survey logic lives here: @osp/ops applies the ops and the server validates the save.
 */
import { applyTransaction, DEFAULT_ENV, type Json, type OpsEnv } from '@osp/ops';
import type { PatchOperation } from './json-patch';
import type { Diagnostic, EditResult, Invocation, Result, SaveResult, SurveyDoc, SurveyTransport } from './transport';

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

export interface SubmitOptions {
	/**
	 * Rejection codes the caller handles itself (e.g. asks before retrying with `force`):
	 * a rejection whose first diagnostic has one of them is returned but not surfaced.
	 */
	quiet?: readonly string[];
}

/** An undo or redo step: the ops that reverse a transaction. */
interface Step {
	ops: Invocation[];
}

/** A local transaction (edit, undo or redo) not yet saved. */
interface Change {
	kind: 'edit' | 'undo' | 'redo';
	/** The ops applied (re-run on a rebase; sent for the audit log). */
	ops: Invocation[];
	txnId: string;
	/** The document after this change (and every change before it in the queue). */
	after: SurveyDoc;
	/** RFC 6902, from the document before this change to `after`. */
	patch: PatchOperation[];
	/** The stack step this change pushed (its inverse, kept up to date on a rebase). */
	step: Step | null;
	/** Undo what the change did to the undo/redo stacks (when it is rolled back). */
	unstack: () => void;
	attempts: number;
}

export interface Flushable {
	flush(): void;
}

export interface SurveyStoreOptions {
	transport: SurveyTransport;
	newTransactionId?: () => string;
	sleep?: (ms: number) => Promise<void>;
	/** Backoff before retrying after a network failure (last value repeats). */
	retryDelays?: readonly number[];
	/** Give up on a save after this many consecutive 409s. */
	maxConflictRetries?: number;
	onUnauthenticated?: () => void;
	/** The validator and expression parser the ops use (default: @osp/spec, @osp/engine). */
	env?: OpsEnv;
}

function defaultTxnId(): string {
	if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
	return `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}

const REJECTED = 'The edit was rejected.';
const CONFLICT =
	'This survey was changed elsewhere, and your pending change no longer applies. You are now seeing the latest version.';

export class SurveyStore {
	surveyId = $state('');
	/** Title from the survey list/detail; the model's own title wins once loaded. */
	title = $state('');
	/** The draft as edited here: the last saved document plus every pending change. */
	survey = $state.raw<SurveyDoc | null>(null);
	/** The server's revision of the last saved document (what publish and exports use). */
	revision = $state(0);
	/** Bumped whenever `survey` changes here (edits, undo, rollbacks, reloads). */
	version = $state(0);
	diagnostics = $state.raw<Diagnostic[]>([]);
	/** The survey's lab, when the transport says (null: unknown). */
	tenantId = $state<string | null>(null);
	/** Published versions of this survey (responses may exist for each): 0 = never published. */
	publishedVersions = $state(0);
	/** The last rejected edit (422), until the next successful one or `clearRejection`. */
	rejection = $state.raw<Rejection | null>(null);
	conflict = $state.raw<{ message: string } | null>(null);
	offline = $state(false);
	/** Load failure or a non-retryable error. */
	error = $state<string | null>(null);
	loading = $state(false);
	/** Changes applied here and not yet saved. */
	pending = $state(0);
	/**
	 * Edits (and undo/redo) made since load, never decreasing: "saved" after this grew means
	 * the edit was saved, not the one before it (the save status shows it as `data-edits`).
	 */
	edits = $state(0);
	/** A 401 stopped saving: the queue is kept until `resume()`. */
	paused = $state(false);
	#resume: (() => void) | null = null;
	#dirty = $state(0);
	#undo = $state.raw<Step[]>([]);
	#redo = $state.raw<Step[]>([]);
	#ids = new WeakMap<Step, string>();

	/** The last document the server stored, at `revision`. */
	#saved: SurveyDoc | null = null;
	#queue: Change[] = [];
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
	readonly #env: OpsEnv;

	constructor(o: SurveyStoreOptions) {
		this.#t = o.transport;
		this.#newTxn = o.newTransactionId ?? defaultTxnId;
		this.#sleep = o.sleep ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
		this.#delays = o.retryDelays ?? [1000, 2000, 4000, 8000, 15000];
		this.#maxConflicts = o.maxConflictRetries ?? 5;
		this.#onUnauth = o.onUnauthenticated ?? (() => {});
		this.#env = o.env ?? DEFAULT_ENV;
	}

	get canUndo(): boolean {
		return this.#undo.length > 0;
	}
	get canRedo(): boolean {
		return this.#redo.length > 0;
	}
	/** Transaction ids of the steps on the undo stack, oldest first (for tests). */
	get undoStack(): readonly string[] {
		return this.#undo.map((s) => this.#ids.get(s) ?? '');
	}
	get redoStack(): readonly string[] {
		return this.#redo.map((s) => this.#ids.get(s) ?? '');
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
			const r = await this.#refetch();
			if (r.kind !== 'ok') {
				this.#fail(r);
				return false;
			}
			this.#show(this.#saved);
			this.publishedVersions = r.data.publishedVersions ?? 0;
			return true;
		} finally {
			this.loading = false;
		}
	}

	/** Fetch the latest draft as the saved document (`survey` is the caller's to set). */
	async #refetch() {
		const r = await this.#t.load(this.surveyId);
		if (r.kind === 'ok') {
			this.title = r.data.title;
			this.tenantId = r.data.tenantId ?? null;
			this.#saved = r.data.survey;
			this.revision = r.data.revision;
			this.diagnostics = r.data.diagnostics ?? this.#validate(r.data.survey);
		}
		return r;
	}

	#show(doc: SurveyDoc | null) {
		this.survey = doc;
		this.version += 1;
	}

	#validate(doc: SurveyDoc): Diagnostic[] {
		return this.#env.validator.parse(doc as Json).diagnostics;
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

	/** Edits queued or buffered and not yet saved (the page's leave guard). */
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

	/** Apply one gesture's ops as one transaction, here and now; it is saved in the background. */
	submit(ops: Invocation[], options: SubmitOptions = {}): Promise<Outcome> {
		if (!ops.length) return Promise.resolve({ status: 'dropped', message: 'No change.' });
		this.edits += 1;
		const quiet = options.quiet ?? [];
		return Promise.resolve(
			this.#local('edit', ops, (inverse) => {
				const step: Step = { ops: inverse };
				this.#undo = [...this.#undo, step];
				const redo = this.#redo;
				this.#redo = [];
				return {
					step,
					unstack: () => {
						this.#undo = this.#undo.filter((s) => s !== step);
						if (!this.#redo.length) this.#redo = redo;
					}
				};
			}, (r) => !quiet.includes(r.diagnostics[0]?.code ?? ''))
		);
	}

	undo(): Promise<Outcome> {
		return this.#reverse('undo');
	}

	redo(): Promise<Outcome> {
		return this.#reverse('redo');
	}

	#reverse(kind: 'undo' | 'redo'): Promise<Outcome> {
		this.flushBuffers();
		const from = kind === 'undo' ? this.#undo : this.#redo;
		const step = from.at(-1);
		if (step === undefined) {
			return Promise.resolve({ status: 'dropped', message: kind === 'undo' ? 'Nothing to undo.' : 'Nothing to redo.' });
		}
		this.edits += 1;
		const take = () => {
			if (kind === 'undo') this.#undo = this.#undo.filter((s) => s !== step);
			else this.#redo = this.#redo.filter((s) => s !== step);
		};
		const out = this.#local(kind, step.ops, (inverse) => {
			take();
			const back: Step = { ops: inverse };
			if (kind === 'undo') this.#redo = [...this.#redo, back];
			else this.#undo = [...this.#undo, back];
			return {
				step: back,
				unstack: () => {
					if (kind === 'undo') {
						this.#redo = this.#redo.filter((s) => s !== back);
						this.#undo = [...this.#undo, step];
					} else {
						this.#undo = this.#undo.filter((s) => s !== back);
						this.#redo = [...this.#redo, step];
					}
				}
			};
		});
		// A step that no longer applies (the survey changed since) or changes nothing is
		// dropped, as before.
		if (out.status !== 'applied' || out.result.transactionId === null) take();
		return Promise.resolve(out);
	}

	/**
	 * Apply `ops` to the local draft. On success `stack(inverse)` records the undo/redo step
	 * and the change is queued for saving.
	 */
	#local(
		kind: Change['kind'],
		ops: Invocation[],
		stack: (inverse: Invocation[]) => { step: Step; unstack: () => void },
		surface: (r: Rejection) => boolean = () => true
	): Outcome {
		if (!this.survey) return { status: 'dropped', message: 'The survey is not loaded.' };
		const tx = applyTransaction({ survey: this.survey as Json, revision: 0 }, ops, 0, this.#env);
		if (tx.status !== 'ok') {
			const r = { message: REJECTED, diagnostics: tx.diagnostics };
			if (surface(r)) this.rejection = r;
			return { status: 'rejected', ...r };
		}
		this.rejection = null;
		this.diagnostics = tx.diagnostics;
		const patch = tx.patch as unknown as PatchOperation[];
		if (!patch.length) {
			return { status: 'applied', result: { revision: this.#localRevision(), patch, diagnostics: tx.diagnostics, transactionId: null } };
		}
		const txnId = this.#newTxn();
		const { step, unstack } = stack(tx.inverse as Invocation[]);
		this.#ids.set(step, txnId);
		const after = tx.draft.survey as SurveyDoc;
		this.#queue.push({ kind, ops, txnId, after, patch, step, unstack, attempts: 0 });
		this.pending = this.#queue.length;
		this.#show(after);
		if (!this.#draining) this.#draining = this.#drain();
		return { status: 'applied', result: { revision: this.#localRevision(), patch, diagnostics: tx.diagnostics, transactionId: txnId } };
	}

	/** The revision the server will be at once every pending change is saved. */
	#localRevision(): number {
		return this.revision + this.#queue.length;
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
		if (r.kind !== 'ok') {
			this.#fail(r);
			return;
		}
		this.error = null;
		this.#show(this.#saved);
	}

	/** Resolves when every pending change has been saved (or given up on). */
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

	// -- saving -----------------------------------------------------------------------

	async #drain() {
		// `#draining` is cleared synchronously when the loop sees an empty queue, so a change
		// queued by a continuation of the last save always starts a new drain.
		for (;;) {
			const c = this.#queue[0];
			if (!c) {
				this.#draining = null;
				return;
			}
			const r = await this.#t.saveDraft(this.surveyId, {
				baseRevision: this.revision,
				patch: c.patch,
				ops: c.ops,
				transactionId: c.txnId
			});
			if (this.#queue[0] !== c) continue; // the queue was reset meanwhile
			switch (r.kind) {
				case 'ok':
					this.#saved = c.after;
					this.#done(c, r.data);
					break;
				case 'rejected':
					this.offline = false;
					this.#rollback(c, { message: r.message, diagnostics: r.diagnostics });
					break;
				case 'conflict':
					await this.#conflicted(c);
					break;
				case 'offline':
					this.offline = true;
					await this.#backoff(c);
					break;
				case 'error':
					if (r.status === 401) {
						await this.#pause();
						break;
					}
					this.offline = false;
					this.#fail(r);
					this.#rollback(c, null);
			}
		}
	}

	#done(c: Change, data: SaveResult) {
		this.offline = false;
		this.error = null;
		this.revision = data.revision;
		this.#queue.shift();
		this.pending = this.#queue.length;
		// The server's diagnostics describe the saved document: show them once nothing newer
		// is pending (a replayed save answers none: keep ours).
		if (!this.#queue.length && !data.replayed) this.diagnostics = data.diagnostics;
	}

	async #backoff(c: Change) {
		const d = this.#delays;
		await this.#sleep(d[Math.min(c.attempts, d.length - 1)] ?? 1000);
		c.attempts++;
	}

	/** A 401 on a save: keep the queue, stop sending until `resume()`. */
	async #pause(): Promise<void> {
		this.offline = false;
		this.paused = true;
		this.#onUnauth();
		await new Promise<void>((r) => (this.#resume = r));
	}

	/** 409: fetch the newer draft and rebase every pending change onto it. */
	async #conflicted(c: Change) {
		c.attempts++;
		if (c.attempts > this.#maxConflicts) {
			this.#enterConflict('The survey keeps changing elsewhere; your change was not applied.');
			return;
		}
		const f = await this.#refetch();
		if (f.kind === 'offline') {
			this.offline = true;
			await this.#backoff(c);
			return;
		}
		if (f.kind !== 'ok') {
			this.#fail(f);
			this.#discard();
			this.#show(this.#saved);
			return;
		}
		this.offline = false;
		const failed = this.#rebase(false);
		if (failed) this.#enterConflict(CONFLICT, failed);
	}

	/**
	 * Re-run every pending change's ops on the saved document, in order. With `drop`, a
	 * change that no longer applies is rolled back and the rest go on; without, the first
	 * one that fails stops the rebase and its diagnostics are returned.
	 */
	#rebase(drop: boolean): Diagnostic[] | null {
		let doc = this.#saved as SurveyDoc;
		const kept: Change[] = [];
		for (const c of this.#queue) {
			const tx = applyTransaction({ survey: doc as Json, revision: 0 }, c.ops, 0, this.#env);
			if (tx.status !== 'ok') {
				if (!drop) return tx.diagnostics;
				c.unstack();
				continue;
			}
			c.after = tx.draft.survey as SurveyDoc;
			c.patch = tx.patch as unknown as PatchOperation[];
			if (c.step) c.step.ops = tx.inverse as Invocation[];
			doc = c.after;
			kept.push(c);
		}
		this.#queue = kept;
		this.pending = kept.length;
		this.#show(doc);
		this.diagnostics = this.#validate(doc);
		return null;
	}

	/** The server refused `c` (or failed it): undo it here, keep what came after it. */
	#rollback(c: Change, rejection: Rejection | null) {
		c.unstack();
		this.#queue = this.#queue.filter((q) => q !== c);
		if (rejection) this.rejection = rejection;
		this.#rebase(true);
	}

	/** Pending changes no longer apply: show the latest draft, drop them, say so. */
	#enterConflict(message: string, diagnostics: Diagnostic[] = []) {
		this.conflict = { message };
		if (diagnostics.length) this.rejection = { message, diagnostics };
		this.#discard();
		this.#show(this.#saved);
	}

	#discard() {
		for (const c of this.#queue.splice(0).reverse()) c.unstack();
		this.pending = 0;
	}

	#fail(r: Exclude<Result<unknown>, { kind: 'ok' }>) {
		this.error = r.message;
		if (r.kind === 'error' && r.status === 401) this.#onUnauth();
	}
}

