/**
 * A `SurveyTransport` with no server: the draft lives in memory (unit tests, dev pages and
 * the serverless demo). It answers `saveDraft` the way `PUT /api/surveys/{id}/draft` does
 * for everything the browser can check on its own: a stale `baseRevision` is a conflict,
 * a patch that doesn't apply (`op.patch`), a structurally invalid result
 * (`op.invalid_result`) or new text the model refuses (`op.invalid_text`) is rejected with
 * nothing kept, a no-op patch keeps the revision, and a transaction id seen before is
 * `replayed`. (The server's duplicate-id and dangling-reference guards are left out: the
 * ops already refuse those, and the server stays the authority.)
 */
import { applyPatch, PatchError, SPEC_VALIDATOR, TEXT_CODES, type Json } from '@osp/ops';
import type { Diagnostic, LoadedSurvey, Result, SaveRequest, SaveResult, SurveyDoc, SurveyTransport } from './transport';

export interface MemoryDraft {
	id: string;
	title: string;
	survey: SurveyDoc;
	revision: number;
	publishedVersions?: number;
}

export interface MemoryTransport extends SurveyTransport {
	/** The stored draft (read it, or change it to play "someone else saved"). */
	draft: MemoryDraft;
	/** Every save request received, in order (also the refused ones). */
	readonly saves: SaveRequest[];
}

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

function err(code: string, message: string): Diagnostic {
	return { severity: 'error', code, message, pointer: '' };
}

function newErrors(before: Diagnostic[], after: Diagnostic[], codes: ReadonlySet<string>): Diagnostic[] {
	const seen = new Map<string, number>();
	for (const d of before) if (codes.has(d.code)) seen.set(`${d.code}\0${d.message}`, (seen.get(`${d.code}\0${d.message}`) ?? 0) + 1);
	return after.filter((d) => {
		if (!codes.has(d.code) || d.severity !== 'error') return false;
		const k = `${d.code}\0${d.message}`;
		const n = seen.get(k) ?? 0;
		if (n > 0) {
			seen.set(k, n - 1);
			return false;
		}
		return true;
	});
}

export function memoryTransport(initial: MemoryDraft): MemoryTransport {
	const done = new Map<string, number>(); // transaction id -> revision it was stored as
	const t: MemoryTransport = {
		draft: clone(initial),
		saves: [],
		async load(): Promise<Result<LoadedSurvey>> {
			const d = t.draft;
			const diagnostics = SPEC_VALIDATOR.parse(d.survey as Json).diagnostics;
			return {
				kind: 'ok',
				data: { id: d.id, title: d.title, revision: d.revision, survey: clone(d.survey), diagnostics, publishedVersions: d.publishedVersions ?? 0 }
			};
		},
		async saveDraft(_surveyId, body): Promise<Result<SaveResult>> {
			t.saves.push(clone(body));
			const d = t.draft;
			const landed = done.get(body.transactionId);
			if (landed !== undefined && landed > body.baseRevision) {
				return { kind: 'ok', data: { revision: landed, diagnostics: [], transactionId: body.transactionId, replayed: true } };
			}
			if (body.baseRevision !== d.revision) {
				return { kind: 'conflict', currentRevision: d.revision, message: `base revision ${body.baseRevision} is stale; current is ${d.revision}` };
			}
			let next: Json;
			try {
				next = applyPatch(d.survey as Json, body.patch as unknown as Json[]);
			} catch (e) {
				const message = e instanceof PatchError ? e.message : 'the patch does not apply';
				return { kind: 'rejected', message: 'The change does not apply to the saved draft.', diagnostics: [err('op.patch', message)], failedIndex: null };
			}
			const after = SPEC_VALIDATOR.parse(next);
			if (!after.valid) {
				return {
					kind: 'rejected',
					message: 'The saved survey would not be structurally valid.',
					diagnostics: [err('op.invalid_result', 'the edit would make the survey invalid'), ...after.diagnostics],
					failedIndex: null
				};
			}
			const bad = newErrors(SPEC_VALIDATOR.parse(d.survey as Json).diagnostics, after.diagnostics, TEXT_CODES);
			if (bad.length) {
				return {
					kind: 'rejected',
					message: 'The survey would hold text the model refuses.',
					diagnostics: [err('op.invalid_text', `the edit would add: ${bad[0]!.message}`), ...bad],
					failedIndex: null
				};
			}
			if (JSON.stringify(next) === JSON.stringify(d.survey)) {
				return { kind: 'ok', data: { revision: d.revision, diagnostics: after.diagnostics, transactionId: null } };
			}
			t.draft = { ...d, survey: next as SurveyDoc, revision: d.revision + 1 };
			done.set(body.transactionId, t.draft.revision);
			return { kind: 'ok', data: { revision: t.draft.revision, diagnostics: after.diagnostics, transactionId: body.transactionId } };
		}
	};
	return t;
}
