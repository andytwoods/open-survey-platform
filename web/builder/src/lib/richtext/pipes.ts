/**
 * Piping chips (planning/rich-text.md §4): the candidates the picker offers, read from the
 * survey JSON the client holds (a convenience, like the condition editor's question list),
 * and the server's `ref.*` / `pipe.*` diagnostics mapped onto the chips they are about.
 * The validator is the truth (AGENTS.md rule 8): nothing here decides what is valid.
 */
import { questionsFromSurvey, textOf } from '../conditions/questions';
import type { PanelDiagnostic } from '../properties/types';
import { asRich, pipesOf, type RichValue } from './convert';

export type PipeGroup = 'Earlier questions' | 'Variables' | 'Built-ins';

export interface PipeCandidate {
	/** What goes into `${…}`. */
	id: string;
	/** The question text, variable kind or built-in description, in the editing language. */
	label: string;
	group: PipeGroup;
}

/** Built-ins every pipe-capable field may use (`osp_spec.validate.BUILTIN_PIPES`). */
export const BUILTIN_PIPES: readonly PipeCandidate[] = [
	{ id: '$trial', label: 'Trial number (a repeated block)', group: 'Built-ins' },
	{ id: '$position.index', label: 'Position of this item on the page', group: 'Built-ins' },
	{ id: '$position.of', label: 'Number of items on the page', group: 'Built-ins' },
	{ id: '$pagesDone', label: 'Pages completed so far', group: 'Built-ins' },
	{ id: '$language', label: "The participant's language", group: 'Built-ins' },
	{ id: '$device', label: "The participant's device class", group: 'Built-ins' }
];

/** Built-ins known only once the session has ended (`ENDING_PIPES`): endings and redirects. */
export const ENDING_PIPES: readonly PipeCandidate[] = [
	{ id: '$response.id', label: 'The response id assigned at submit', group: 'Built-ins' },
	{ id: '$session.id', label: 'The session id', group: 'Built-ins' },
	{ id: '$outcome', label: 'The outcome the survey ended with', group: 'Built-ins' }
];

type Json = Record<string, unknown>;
const obj = (v: unknown): Json | null => (typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Json) : null);

export interface CandidateOptions {
	/** Only items before this question (or page, or block) in document order. */
	before?: string | null;
	lang?: string;
	/** Also offer the end-of-session built-ins (endings, redirects). */
	ending?: boolean;
}

/** Ids of every item (and matrix row) on or after the target, so "earlier" can stop there. */
function idsFrom(survey: unknown, target: string): Set<string> | null {
	const s = obj(survey);
	if (!s) return null;
	const out = new Set<string>();
	let found = false;
	const blocks = Array.isArray(s.blocks) ? s.blocks : [];
	for (const block of blocks.map(obj)) {
		if (block?.id === target) found = true;
		for (const page of (Array.isArray(block?.pages) ? block!.pages : []).map(obj)) {
			if (page?.id === target) found = true;
			for (const q of (Array.isArray(page?.items) ? page!.items : []).map(obj)) {
				if (!q || typeof q.id !== 'string') continue;
				if (q.id === target) found = true;
				if (found) {
					out.add(q.id);
					for (const row of (Array.isArray(q.rows) ? q.rows : []).map(obj)) {
						if (row && typeof row.id === 'string') out.add(`${q.id}_${row.id}`);
					}
				}
			}
		}
	}
	return found ? out : null;
}

/**
 * What the picker lists: questions with a value before the target (matrix rows as
 * `matrix_row`), the survey's variables, and the built-ins. Any input; never throws.
 */
export function pipeCandidates(survey: unknown, { before, lang = 'en', ending = false }: CandidateOptions = {}): PipeCandidate[] {
	const later = before ? idsFrom(survey, before) : null;
	const questions: PipeCandidate[] = questionsFromSurvey(survey, lang)
		.filter((q) => !later || !later.has(q.id))
		.map((q) => ({ id: q.id, label: q.label || q.id, group: 'Earlier questions' }));
	const s = obj(survey);
	const variables: PipeCandidate[] = (Array.isArray(s?.variables) ? s!.variables : [])
		.map(obj)
		.filter((v): v is Json => !!v && typeof v.id === 'string' && v.id !== '')
		.map((v) => ({
			id: v.id as string,
			label: textOf(v.label, lang) || (typeof v.kind === 'string' ? `${v.kind} variable` : 'Variable'),
			group: 'Variables'
		}));
	return [...questions, ...variables, ...BUILTIN_PIPES, ...(ending ? ENDING_PIPES : [])];
}

/** The candidate's visible name in a chip: its id (ids are what researchers know). */
export function chipLabel(id: string): string {
	return id;
}

// --- Diagnostics on chips -----------------------------------------------------------------

/** Walk an RFC 6901 pointer (relative, decoded) into a JSON value. */
function at(value: unknown, parts: string[]): unknown {
	let cur: unknown = value;
	for (const p of parts) {
		if (Array.isArray(cur)) cur = cur[Number(p)];
		else if (obj(cur)) cur = (cur as Json)[p];
		else return undefined;
	}
	return cur;
}

function unescape(seg: string): string {
	return seg.replace(/~1/g, '/').replace(/~0/g, '~');
}

/**
 * Server diagnostics about the pipes of one field, by pipe id: the chip with that id gets
 * the error style and the message as its tooltip. A diagnostic pointing at a pipe node
 * (`…/blocks/0/content/3`) is resolved through the value; one pointing at the field (a
 * plain string) names the id in its message (`'${age}' …`, `… age …`).
 */
export function pipeProblems(
	raw: unknown,
	language: string,
	diagnostics: readonly PanelDiagnostic[] | undefined,
	fieldPointer: string
): Map<string, string> {
	const out = new Map<string, string>();
	const ids = new Set<string>();
	for (const v of [raw, obj(raw)?.[language]]) if (typeof v === 'string' || obj(v)) for (const id of pipesOf(v as RichValue)) ids.add(id);
	for (const d of diagnostics ?? []) {
		if (!d || typeof d.pointer !== 'string') continue;
		if (!(d.code.startsWith('ref.') || d.code.startsWith('pipe.') || d.code === 'consent.pipe')) continue;
		if (d.pointer !== fieldPointer && !d.pointer.startsWith(fieldPointer + '/')) continue;
		const rel = d.pointer.slice(fieldPointer.length).split('/').filter(Boolean).map(unescape);
		const node = at(raw, rel);
		const pipe = obj(node)?.pipe;
		if (typeof pipe === 'string') {
			if (!out.has(pipe)) out.set(pipe, d.message);
			continue;
		}
		const quoted = /\$\{([^}]+)\}/.exec(d.message)?.[1]?.trim();
		if (quoted) {
			if (!out.has(quoted)) out.set(quoted, d.message);
			continue;
		}
		for (const id of ids) {
			if (new RegExp(`(^|[^A-Za-z0-9_$.])${id.replace(/[.$]/g, '\\$&')}($|[^A-Za-z0-9_])`).test(d.message) && !out.has(id)) {
				out.set(id, d.message);
			}
		}
	}
	return out;
}

/** The chips a value shows that the server flagged, for a count in the field's description. */
export function flaggedPipes(value: RichValue | undefined, problems: ReadonlyMap<string, string>): string[] {
	return [...new Set(pipesOf(asRich(value)).filter((id) => problems.has(id)))];
}
