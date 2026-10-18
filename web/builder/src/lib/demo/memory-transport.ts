/**
 * The demo's survey "server" (task DEMO2): a `SurveyTransport` that keeps the draft in
 * memory and applies every edit with @osp/ops, the TypeScript port of osp-ops, exactly as
 * the API's `survey.apply_ops` / `survey.undo` / `survey.redo` do in Python:
 *
 * - `applyOps` runs the ops as one transaction against `baseRevision` (all or nothing; a
 *   stale base is a conflict, a refused op a rejection with its diagnostics). A
 *   transaction that changes nothing is not logged (`transactionId: null`). A retry with a
 *   transaction id that already landed is answered `replayed`, not applied twice.
 * - Each logged transaction keeps its inverse. Undo applies that inverse as a new
 *   transaction (`u:` id) whose own inverse is logged too, so redo of an undo id is the
 *   same move again (`r:` id). Undo of an undo, or redo of anything else, is refused.
 * - Diagnostics are @osp/spec's `validate` (CE4: the same as osp_spec).
 *
 * Nothing leaves the page. `onChange` lets the demo keep the draft across its own page
 * navigations (state.ts).
 */
import { applyPatch, applyTransaction, deepCopy, type Invocation as OpInvocation, type Json } from '@osp/ops';
import { validate } from '@osp/spec';
import type { Diagnostic, EditResult, Invocation, LoadedSurvey, Result, SurveyDoc, SurveyTransport } from '../sync/transport';

export const UNDO_PREFIX = 'u:';
export const REDO_PREFIX = 'r:';
const CLIENT_TXN = /^[A-Za-z0-9_-]{1,36}$/;

export interface DemoDraft {
	id: string;
	title: string;
	revision: number;
	survey: SurveyDoc;
}

interface Logged {
	/** The revision the transaction produced. */
	revision: number;
	inverse: OpInvocation[];
}

export interface MemoryTransportOptions {
	/** Called after every change of the draft (not on reads). */
	onChange?: (draft: DemoDraft) => void;
	newId?: () => string;
}

function newId(): string {
	if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID().replace(/-/g, '').slice(0, 30);
	return Math.random().toString(36).slice(2, 14) + Date.now().toString(36);
}

const notFound = (): Result<never> => ({ kind: 'error', status: 404, code: 'not_found', message: 'Survey not found.' });
const invalid = (message: string): Result<never> => ({ kind: 'rejected', message, diagnostics: [], failedIndex: null });

export class MemorySurveyTransport implements SurveyTransport {
	#draft: DemoDraft;
	#log = new Map<string, Logged>();
	#opts: MemoryTransportOptions;

	constructor(draft: DemoDraft, opts: MemoryTransportOptions = {}) {
		this.#draft = { ...draft, survey: deepCopy(draft.survey as Json) as SurveyDoc };
		this.#opts = opts;
	}

	/** The draft as it is now (a copy). */
	get draft(): DemoDraft {
		return { ...this.#draft, survey: deepCopy(this.#draft.survey as Json) as SurveyDoc };
	}

	diagnostics(): Diagnostic[] {
		return validate(this.#draft.survey) as Diagnostic[];
	}

	async load(surveyId: string): Promise<Result<LoadedSurvey>> {
		if (surveyId !== this.#draft.id) return notFound();
		const d = this.draft;
		return {
			kind: 'ok',
			data: { id: d.id, title: d.title, revision: d.revision, survey: d.survey, diagnostics: this.diagnostics(), publishedVersions: 0 }
		};
	}

	async applyOps(
		surveyId: string,
		body: { ops: Invocation[]; baseRevision: number; transactionId: string }
	): Promise<Result<EditResult>> {
		if (surveyId !== this.#draft.id) return notFound();
		const txn = body.transactionId;
		if (typeof txn !== 'string' || !CLIENT_TXN.test(txn)) return invalid('transactionId must be 1-36 of [A-Za-z0-9_-]');
		const done = this.#log.get(txn);
		if (done && Number.isInteger(body.baseRevision) && done.revision > body.baseRevision) {
			return { kind: 'ok', data: { revision: done.revision, patch: [], diagnostics: [], transactionId: txn, replayed: true } };
		}
		const ops = (body.ops ?? []).map((o) => ({ op: o.op, params: o.params ?? {} })) as OpInvocation[];
		return this.#commit(ops, body.baseRevision, txn);
	}

	async undo(surveyId: string, body: { transactionId: string; baseRevision: number }): Promise<Result<EditResult>> {
		if (surveyId !== this.#draft.id) return notFound();
		if (typeof body.transactionId === 'string' && body.transactionId.startsWith(UNDO_PREFIX)) {
			return invalid('That transaction is an undo: redo it instead.');
		}
		return this.#reverse(body.transactionId, body.baseRevision, UNDO_PREFIX);
	}

	async redo(surveyId: string, body: { transactionId: string; baseRevision: number }): Promise<Result<EditResult>> {
		if (surveyId !== this.#draft.id) return notFound();
		if (!(typeof body.transactionId === 'string' && body.transactionId.startsWith(UNDO_PREFIX))) {
			return invalid('Only an undo transaction can be redone.');
		}
		return this.#reverse(body.transactionId, body.baseRevision, REDO_PREFIX);
	}

	/**
	 * Save protocol of planning/client-edits.md §3 (`PUT …/draft`, task CE5): the builder
	 * applied the ops itself and sends the JSON Patch; it is applied here, the result
	 * validated, and an invalid result refused with nothing saved.
	 */
	putDraft(
		surveyId: string,
		body: { baseRevision: number; patch: unknown }
	): Result<{ revision: number; diagnostics: Diagnostic[] }> {
		if (surveyId !== this.#draft.id) return notFound();
		if (body.baseRevision !== this.#draft.revision) {
			return { kind: 'conflict', currentRevision: this.#draft.revision, message: 'The draft changed meanwhile.' };
		}
		let next: Json;
		try {
			next = applyPatch(this.#draft.survey as Json, body.patch);
		} catch (e) {
			return invalid(`The patch does not apply: ${(e as Error)?.message ?? 'error'}`);
		}
		const diagnostics = validate(next) as Diagnostic[];
		if (diagnostics.some((d) => d.severity === 'error' && d.code.startsWith('schema.'))) {
			return { kind: 'rejected', message: 'The edited survey is not valid; nothing was saved.', diagnostics, failedIndex: null };
		}
		const changed = Array.isArray(body.patch) && body.patch.length > 0;
		this.#draft = { ...this.#draft, survey: next as SurveyDoc, revision: this.#draft.revision + (changed ? 1 : 0) };
		if (changed) this.#opts.onChange?.(this.draft);
		return { kind: 'ok', data: { revision: this.#draft.revision, diagnostics } };
	}

	#reverse(txn: unknown, baseRevision: number, prefix: string): Result<EditResult> {
		const logged = typeof txn === 'string' ? this.#log.get(txn) : undefined;
		if (!logged) return { kind: 'error', status: 404, code: 'not_found', message: 'Transaction not found.' };
		return this.#commit(logged.inverse, baseRevision, prefix + (this.#opts.newId ?? newId)());
	}

	#commit(ops: OpInvocation[], baseRevision: number, txn: string): Result<EditResult> {
		const before = { survey: this.#draft.survey as Json, revision: this.#draft.revision };
		const r = applyTransaction(before, ops, baseRevision);
		if (r.status === 'conflict') {
			return { kind: 'conflict', currentRevision: this.#draft.revision, message: r.diagnostics[0]?.message ?? 'Conflict.' };
		}
		if (r.status === 'rejected') {
			return {
				kind: 'rejected',
				message: r.diagnostics[0]?.message ?? 'The edit was rejected.',
				diagnostics: r.diagnostics as Diagnostic[],
				failedIndex: r.failedIndex
			};
		}
		const diagnostics = r.diagnostics as Diagnostic[];
		if (!r.patch.length) {
			return { kind: 'ok', data: { revision: this.#draft.revision, patch: [], diagnostics, transactionId: null } };
		}
		this.#draft = { ...this.#draft, survey: r.draft.survey as SurveyDoc, revision: r.draft.revision };
		this.#log.set(txn, { revision: r.draft.revision, inverse: r.inverse });
		this.#opts.onChange?.(this.draft);
		return {
			kind: 'ok',
			data: { revision: r.draft.revision, patch: r.patch as unknown as EditResult['patch'], diagnostics, transactionId: txn }
		};
	}
}
