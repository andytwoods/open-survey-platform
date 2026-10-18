/**
 * Pure helpers behind the grid (matrix) rows editor (task B15): reading the editor's
 * inputs out of a survey, op builders for each gesture, and naming the places that refer
 * to a row. Display and pre-send checks only: the server validates every op (AGENTS.md
 * rule 8). Every function accepts hostile input and never throws.
 *
 * Row `r` of grid `m` is the single-choice variable `m_r` (semantics.md §2, C2c-1), so a
 * row id never changes: renaming edits the label only. Params follow `osp-ops`
 * matrix_row_ops.py.
 */
import { isRichText } from '@osp/engine';
import type { SpecMatrixRow, SpecText } from '../cards/types';
import {
	labelIn,
	labelValueIn,
	sameLabel,
	withLabel,
	type ChoiceDiagnostic,
	type ChoiceOp,
	type LabelValue
} from '../choices/model';
import type { LabelContext } from '../choices/ops';

export type { SpecMatrixRow };
export type RowOp = ChoiceOp;
export type RowDiagnostic = ChoiceDiagnostic;

/** What the editor needs about one grid question. */
export interface RowsQuestion {
	id: string;
	label?: SpecText;
	/** The grid's own `required`: the default for every row that does not say. */
	required: boolean;
	rows: readonly SpecMatrixRow[];
}

/** The outcome of a submit, as the survey store reports it (only what the editor reads). */
export interface RowsOutcome {
	status: string;
	diagnostics?: readonly RowDiagnostic[];
}

export type RowsSubmit = (ops: RowOp[], options?: { quiet?: readonly string[] }) => Promise<RowsOutcome> | RowsOutcome | void;

type Json = Record<string, unknown>;

function isObj(v: unknown): v is Json {
	return !!v && typeof v === 'object' && !Array.isArray(v);
}

function arr(v: unknown): unknown[] {
	return Array.isArray(v) ? v : [];
}

function clone<T>(v: T): T {
	return JSON.parse(JSON.stringify(v ?? null)) as T;
}

/** The grid's rows with a usable id (string, not repeated). */
export function rowsOf(q: unknown): SpecMatrixRow[] {
	const seen = new Set<string>();
	const out: SpecMatrixRow[] = [];
	for (const r of arr(isObj(q) ? q.rows : undefined)) {
		if (!isObj(r) || typeof r.id !== 'string' || !r.id || seen.has(r.id)) continue;
		seen.add(r.id);
		const label = typeof r.label === 'string' || isObj(r.label) ? (r.label as SpecText) : '';
		out.push({ id: r.id, label, required: typeof r.required === 'boolean' ? r.required : null });
	}
	return out;
}

/** Every grid question in the survey, with its pointer. */
function grids(survey: unknown): { q: Json; pointer: string }[] {
	const out: { q: Json; pointer: string }[] = [];
	if (!isObj(survey)) return out;
	arr(survey.blocks).forEach((b, bi) => {
		if (!isObj(b)) return;
		arr(b.pages).forEach((p, pi) => {
			if (!isObj(p)) return;
			arr(p.items).forEach((q, qi) => {
				if (isObj(q) && typeof q.id === 'string') out.push({ q, pointer: `/blocks/${bi}/pages/${pi}/items/${qi}` });
			});
		});
	});
	return out;
}

/** Everything RowsEditor needs about grid `questionId`, or `question: null`. */
export function rowsEditorInputs(survey: unknown, questionId: string) {
	const found = grids(survey).find(({ q }) => q.id === questionId && q.type === 'matrix');
	const md = isObj(survey) && isObj(survey.metadata) ? survey.metadata : {};
	const languages = arr(md.languages).filter((l): l is string => typeof l === 'string');
	return {
		question: found
			? ({
					id: questionId,
					label: found.q.label as SpecText | undefined,
					required: found.q.required === true,
					rows: rowsOf(found.q)
				} satisfies RowsQuestion)
			: null,
		pointer: found ? `${found.pointer}/rows` : undefined,
		languages,
		defaultLanguage: typeof md.defaultLanguage === 'string' ? md.defaultLanguage : languages[0]
	};
}

/** The variable id of a row: `<grid id>_<row id>`. */
export const rowVariable = (questionId: string, rowId: string) => `${questionId}_${rowId}`;

/** Whether the row is required: its own setting, else the grid's (C2c-1). */
export function rowRequired(q: Pick<RowsQuestion, 'required'>, row: Pick<SpecMatrixRow, 'required'>): boolean {
	return typeof row.required === 'boolean' ? row.required : q.required;
}

// --- op builders: one gesture, one transaction ------------------------------------------

/** Add a row (the server picks the id `r<n>`) at `index` (default: the end). */
export function addRowOps(question: string, label: SpecText = '', index?: number): RowOp[] {
	const params: Record<string, unknown> = { question, label: clone(label) };
	if (index !== undefined) params.index = index;
	return [{ op: 'add_matrix_row', params }];
}

export function deleteRowOps(q: RowsQuestion, i: number, force = false): RowOp[] {
	const r = q.rows[i];
	if (!r || q.rows.length <= 1) return [];
	return [{ op: 'delete_matrix_row', params: { question: q.id, row: r.id, ...(force ? { force: true } : {}) } }];
}

/** Move row `from` so it ends up at `to` (both in the current order). */
export function moveRowOps(q: RowsQuestion, from: number, to: number): RowOp[] {
	const r = q.rows[from];
	if (!r || from === to || to < 0 || to >= q.rows.length) return [];
	return [{ op: 'move_matrix_row', params: { question: q.id, row: r.id, index: to } }];
}

/**
 * Change row `i`'s label in the editing language (plain or rich: the server normalises a
 * formatting-free tree to a string). Nothing when the value is unchanged.
 */
export function renameRowOps(q: RowsQuestion, i: number, value: LabelValue, ctx: LabelContext = {}): RowOp[] {
	const r = q.rows[i];
	if (!r) return [];
	const key = ctx.lang ?? ctx.defaultLanguage;
	const has =
		typeof r.label === 'string' ||
		isRichText(r.label) ||
		(key !== undefined && isObj(r.label) && Object.hasOwn(r.label, key));
	if (has && sameLabel(labelValueIn(r.label, key), value)) return [];
	return [
		{
			op: 'rename_matrix_row',
			params: { question: q.id, row: r.id, label: withLabel(r.label, clone(value), ctx.lang, ctx.defaultLanguage) }
		}
	];
}

/**
 * Make row `i` required or not. A row that would match the grid's own `required` follows
 * it again (`required: null`), so changing the grid later still applies to the row.
 */
export function setRequiredOps(q: RowsQuestion, i: number, required: boolean): RowOp[] {
	const r = q.rows[i];
	if (!r) return [];
	const next = required === q.required ? null : required;
	const now = typeof r.required === 'boolean' ? r.required : null;
	if (next === now) return [];
	return [{ op: 'set_matrix_row_required', params: { question: q.id, row: r.id, required: next } }];
}

// --- references to a row ----------------------------------------------------------------

const QUESTION_PTR = /^\/blocks\/(\d+)\/pages\/(\d+)\/items\/(\d+)(\/.*)?$/;

/**
 * A short description of where a diagnostic's pointer is: "<question label> (condition)"
 * or "(text)" for a question, else the pointer itself.
 */
export function describeSite(survey: unknown, pointer: string | undefined, lang?: string): string {
	const p = typeof pointer === 'string' ? pointer : '';
	const m = QUESTION_PTR.exec(p);
	if (m && isObj(survey)) {
		const b = arr(survey.blocks)[Number(m[1])];
		const page = isObj(b) ? arr(b.pages)[Number(m[2])] : undefined;
		const q = isObj(page) ? arr(page.items)[Number(m[3])] : undefined;
		if (isObj(q) && typeof q.id === 'string') {
			const rest = m[4] ?? '';
			const what = /^\/(showIf|constraint)(\/|$)/.test(rest) ? 'condition' : 'text';
			const name = labelIn(q.label, lang) || labelIn(q.label) || q.id;
			return `${name} (${what})`;
		}
	}
	if (p.startsWith('/flow')) return `Survey flow (${p})`;
	return p || 'the survey';
}

/** The referring places of a rejected delete: one per distinct site, described. */
export function referencingSites(
	survey: unknown,
	diagnostics: readonly RowDiagnostic[] | null | undefined,
	lang?: string
): string[] {
	const ds = (diagnostics ?? []).filter((d) => d && d.code === 'op.dangling_ref');
	// The first diagnostic is the summary; the rest point at each site.
	const sites = ds.length > 1 ? ds.slice(1) : ds;
	return [...new Set(sites.map((d) => describeSite(survey, d.pointer, lang)))];
}
