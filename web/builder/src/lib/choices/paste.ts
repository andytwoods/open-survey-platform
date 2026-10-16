/**
 * Bulk paste parsing for the choice list editor. One choice per non-blank line:
 *
 *   code<TAB>label         (from a spreadsheet; any code, e.g. "SD<TAB>Strongly disagree")
 *   1 Strongly disagree    (also "1. …", "1) …", "1: …", "1 = …", "1 - …")
 *   Strongly disagree      (auto-coded with the next integer)
 *
 * A leading number is read as a code only when *every* line without a tab starts with
 * one, so a single label such as "3 or more" in a list of labels stays a label.
 * Auto codes follow the server's `bulk_paste_choices`: `replace` counts from 1, `append`
 * from after the highest integer code, and an explicit integer code moves the counter on.
 *
 * The preview sends every code explicitly (`code<TAB>label` lines), so what the user sees
 * is exactly what the server stores.
 */
import { codeKey, codeShapeError, mixedTypes, nextCode, parseCode, type ChoiceCode, type ChoiceOp } from './model';

export type PasteMode = 'replace' | 'append';
/** The server's limit on `bulk_paste_choices.text` (characters). */
export const MAX_PASTE = 100_000;

export interface PastedRow {
	/** 1-based line number in the pasted text. */
	line: number;
	code: ChoiceCode;
	label: string;
	/** The code was assigned, not typed. */
	auto: boolean;
	error: string | null;
	warning: string | null;
}

export interface PastePreview {
	rows: PastedRow[];
	errors: number;
	/** List-level problems (e.g. too long, nothing to paste). */
	problems: string[];
	/** Mixed integer and text codes (a warning, not an error). */
	mixed: boolean;
	/** The text to send: one `code<TAB>label` line per row. */
	text: string;
}

const LEADING = /^\s*(-?[0-9]{1,15})(?:\s*[.):=]\s*|\s+[-–]\s+|\s+)(\S.*?)\s*$/;

interface Line {
	n: number;
	raw: string;
	tab: number;
}

export function parsePaste(
	text: string,
	existing: readonly { value: unknown }[] = [],
	mode: PasteMode = 'replace'
): PastePreview {
	const src = typeof text === 'string' ? text : '';
	const lines: Line[] = src
		.split(/\r\n|\r|\n/)
		.map((raw, i) => ({ n: i + 1, raw, tab: raw.indexOf('\t') }))
		.filter((l) => l.raw.trim() !== '')
		.map((l) => (l.tab >= 0 && l.raw.slice(0, l.tab).trim() === '' ? { ...l, raw: l.raw.trim(), tab: -1 } : l));
	const plain = lines.filter((l) => l.tab < 0);
	const numbered = plain.length > 0 && plain.every((l) => LEADING.test(l.raw));

	let next = mode === 'replace' ? 1 : nextCode(existing);
	const rows: PastedRow[] = [];
	for (const l of lines) {
		let code: ChoiceCode;
		let label: string;
		let auto = false;
		let typed: string | null = null;
		if (l.tab >= 0) {
			typed = l.raw.slice(0, l.tab).trim();
			code = parseCode(typed);
			label = l.raw.slice(l.tab + 1).trim();
		} else if (numbered) {
			const m = LEADING.exec(l.raw)!;
			code = Number(m[1]);
			label = m[2];
		} else {
			code = next++;
			label = l.raw.trim();
			auto = true;
		}
		if (typeof code === 'number') next = Math.max(next, code + 1);
		rows.push({
			line: l.n,
			code,
			label,
			auto,
			error: typed === null ? null : codeShapeError(typed),
			warning: label ? null : 'Empty label.'
		});
	}

	// Duplicates: within the paste, and (append) against the codes already in the list.
	const kept = mode === 'append' ? existing.map((c) => codeKey(c?.value)) : [];
	const seen = new Map<string, number>();
	for (const k of kept) seen.set(k, -1);
	for (const [i, r] of rows.entries()) {
		const k = codeKey(r.code);
		if (r.error) continue;
		if (seen.has(k)) {
			const first = seen.get(k)!;
			r.error = first < 0 ? `Code ${k} is already in the list.` : `Code ${k} is used more than once.`;
			if (first >= 0 && !rows[first].error) rows[first].error = `Code ${k} is used more than once.`;
		} else seen.set(k, i);
	}

	const problems: string[] = [];
	if (!rows.length) problems.push('Nothing to paste: every line is blank.');
	const out = rows.map((r) => `${r.code}\t${r.label}`).join('\n');
	if (out.length > MAX_PASTE) problems.push(`Too long: at most ${MAX_PASTE.toLocaleString('en')} characters.`);
	const all = [...(mode === 'append' ? existing.map((c) => c?.value as ChoiceCode) : []), ...rows.map((r) => r.code)];
	return {
		rows,
		errors: rows.filter((r) => r.error).length + problems.length,
		problems,
		mixed: mixedTypes(all),
		text: out
	};
}

/** One `bulk_paste_choices` for a clean preview; nothing when it has errors. */
export function pasteOps(owner: string, preview: PastePreview, mode: PasteMode): ChoiceOp[] {
	if (preview.errors > 0 || !preview.rows.length) return [];
	return [{ op: 'bulk_paste_choices', params: { owner, text: preview.text, mode } }];
}
