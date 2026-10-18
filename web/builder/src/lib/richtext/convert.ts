/**
 * The survey model's rich tree (`@osp/engine` `RichText`, planning/rich-text.md §3) to and
 * from the editor's ProseMirror JSON, and plain strings to and from the tree. Pure, no DOM,
 * tolerant of malformed input (an unknown node is dropped, never thrown on).
 *
 * `fromDoc(toDoc(x)) === canonical(x)` for every tree the level allows (convert.test.ts).
 */
import { isRichText, normaliseText, type InlineRun, type Mark, type RichBlock, type RichText, type TextRun } from '@osp/engine';
import type { Level } from './levels';

/** A survey text value for one language. */
export type RichValue = string | RichText;

// --- ProseMirror JSON --------------------------------------------------------------------

export interface PmMark {
	type: string;
	attrs?: Record<string, unknown>;
}

export interface PmNode {
	type: string;
	attrs?: Record<string, unknown>;
	content?: PmNode[];
	marks?: PmMark[];
	text?: string;
}

/** Node and mark names of the editor schema (editor.ts registers exactly these). */
export const N = {
	doc: 'doc',
	paragraph: 'paragraph',
	heading: 'heading',
	bulletList: 'bulletList',
	orderedList: 'orderedList',
	listItem: 'listItem',
	text: 'text',
	hardBreak: 'hardBreak',
	pipe: 'pipe'
} as const;

export const M = { bold: 'bold', italic: 'italic', link: 'link', lang: 'lang' } as const;

// --- Pipes -------------------------------------------------------------------------------

/** `${…}` in plain text: the validator's regex (`osp_spec.validate._PIPE`). */
export const PIPE_RE = /\$\{([^}]*)\}/g;

const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;
const BUILTIN = /^\$[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*$/;

/**
 * Whether the inner text of `${…}` names something the engine could fill: an identifier
 * (a question, row or variable) or a `$built-in`. Anything else stays literal text, as the
 * plan compiler treats it; the server's `ref.*` diagnostics decide whether the id exists.
 */
export function isPipeRef(inner: string): boolean {
	return IDENT.test(inner) || BUILTIN.test(inner);
}

/** Plain text as inline runs: `${id}` references become pipe nodes, newlines breaks. */
export function plainRuns(text: string): InlineRun[] {
	const out: InlineRun[] = [];
	const push = (t: string) => {
		if (t === '') return;
		const lines = t.split('\n');
		lines.forEach((line, i) => {
			if (i > 0) out.push({ br: true });
			if (line !== '') out.push({ text: line });
		});
	};
	let last = 0;
	for (const m of text.matchAll(PIPE_RE)) {
		const at = m.index ?? 0;
		const inner = m[1]!;
		if (!isPipeRef(inner.trim())) continue;
		push(text.slice(last, at));
		out.push({ pipe: inner.trim() });
		last = at + m[0].length;
	}
	push(text.slice(last));
	return out;
}

/** A plain string as the one-paragraph tree it is. */
export function plainToRich(text: string): RichText {
	return { type: 'rich', blocks: [{ type: 'p', content: plainRuns(text) }] };
}

/** Any value as a tree: strings are parsed, trees pass, anything else is empty. */
export function asRich(value: unknown): RichText {
	if (typeof value === 'string') return plainToRich(value);
	if (isRichText(value) && Array.isArray(value.blocks)) return value;
	return { type: 'rich', blocks: [] };
}

// --- Canonical form ----------------------------------------------------------------------

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);

function sameFormat(a: TextRun, b: TextRun): boolean {
	return (
		(a.href ?? '') === (b.href ?? '') &&
		(a.lang ?? '') === (b.lang ?? '') &&
		(a.marks ?? []).join() === (b.marks ?? []).join()
	);
}

function cleanRun(node: unknown): InlineRun | null {
	if (!isObj(node)) return null;
	if (node.br === true) return { br: true };
	if (typeof node.pipe === 'string') return node.pipe.trim() ? { pipe: node.pipe.trim() } : null;
	if (typeof node.text !== 'string') return null;
	const run: TextRun = { text: node.text };
	const marks = Array.isArray(node.marks) ? node.marks.filter((m): m is Mark => m === 'b' || m === 'i') : [];
	const ordered = (['b', 'i'] as const).filter((m) => marks.includes(m));
	if (ordered.length) run.marks = ordered;
	if (typeof node.href === 'string' && node.href !== '') run.href = node.href;
	if (typeof node.lang === 'string' && node.lang !== '') run.lang = node.lang;
	return run;
}

/** Runs with empty text dropped and adjacent equally-formatted text runs merged. */
export function canonicalRuns(runs: unknown): InlineRun[] {
	const out: InlineRun[] = [];
	for (const raw of Array.isArray(runs) ? runs : []) {
		const run = cleanRun(raw);
		if (!run) continue;
		if ('text' in run) {
			if (run.text === '') continue;
			const last = out[out.length - 1];
			if (last && 'text' in last && sameFormat(last, run)) {
				last.text += run.text;
				continue;
			}
		}
		out.push(run);
	}
	return out;
}

/** The tree in canonical form: the shape `fromDoc` produces for the same content. */
export function canonical(tree: RichText): RichText {
	const blocks: RichBlock[] = [];
	for (const b of Array.isArray(tree.blocks) ? tree.blocks : []) {
		if (!isObj(b)) continue;
		if (b.type === 'p') blocks.push({ type: 'p', content: canonicalRuns(b.content) });
		else if (b.type === 'h') {
			const level = b.level === 2 || b.level === 3 ? b.level : 1;
			blocks.push({ type: 'h', level, content: canonicalRuns(b.content) });
		} else if (b.type === 'ul' || b.type === 'ol') {
			const items = (Array.isArray(b.items) ? b.items : []).map(canonicalRuns);
			blocks.push({ type: b.type, items: items.length ? items : [[]] });
		}
	}
	return { type: 'rich', blocks: blocks.length ? blocks : [{ type: 'p', content: [] }] };
}

/** Deep equality of two values after canonicalising rich trees (what "unchanged" means). */
export function sameValue(a: unknown, b: unknown): boolean {
	return JSON.stringify(normalForm(a)) === JSON.stringify(normalForm(b));
}

/**
 * The value the field commits: the tree normalised to a plain string when it carries no
 * formatting (RT-D3, `normaliseText`), including breaks written back as newlines so an
 * existing multi-line plain text stays plain; `""` when empty.
 */
export function normalForm(value: unknown): RichValue {
	if (value === undefined || value === null) return '';
	if (typeof value === 'string') return value;
	if (!isRichText(value)) return '';
	const tree = canonical(value);
	const plain = plainIfPossible(tree);
	if (plain !== null) return plain;
	const n = normaliseText(tree);
	return typeof n === 'string' ? n : tree;
}

function plainIfPossible(tree: RichText): string | null {
	if (tree.blocks.length !== 1 || tree.blocks[0]!.type !== 'p') return null;
	let s = '';
	for (const r of tree.blocks[0]!.content) {
		if ('br' in r) s += '\n';
		else if ('pipe' in r) s += `\${${r.pipe}}`;
		else if (r.marks || r.href || r.lang) return null;
		else s += r.text;
	}
	return s;
}

// --- Tree -> ProseMirror -----------------------------------------------------------------

function runToPm(run: InlineRun): PmNode | null {
	if ('br' in run) return { type: N.hardBreak };
	if ('pipe' in run) return { type: N.pipe, attrs: { id: run.pipe } };
	if (run.text === '') return null;
	const marks: PmMark[] = [];
	if (run.marks?.includes('b')) marks.push({ type: M.bold });
	if (run.marks?.includes('i')) marks.push({ type: M.italic });
	if (run.href) marks.push({ type: M.link, attrs: { href: run.href } });
	if (run.lang) marks.push({ type: M.lang, attrs: { lang: run.lang } });
	const node: PmNode = { type: N.text, text: run.text };
	if (marks.length) node.marks = marks;
	return node;
}

function runsToPm(runs: InlineRun[]): PmNode[] {
	return runs.map(runToPm).filter((n): n is PmNode => n !== null);
}

const paragraph = (runs: InlineRun[]): PmNode => {
	const content = runsToPm(runs);
	return content.length ? { type: N.paragraph, content } : { type: N.paragraph };
};

/**
 * The editor document for a value at a level. Content the level's schema cannot hold is
 * lowered rather than lost (a heading in a stem becomes a paragraph; several blocks in an
 * inline field become one paragraph with breaks): the server's diagnostics say why.
 */
export function toDoc(value: RichValue | undefined | null, level: Level): PmNode {
	const tree = canonical(asRich(value));
	if (level === 'inline') {
		const runs: InlineRun[] = [];
		tree.blocks.forEach((b, i) => {
			const parts = 'items' in b ? b.items : [b.content];
			parts.forEach((p, j) => {
				if (i > 0 || j > 0) runs.push({ br: true });
				runs.push(...p);
			});
		});
		return { type: N.doc, content: [paragraph(canonicalRuns(runs))] };
	}
	const content: PmNode[] = [];
	for (const b of tree.blocks) {
		if (b.type === 'p') content.push(paragraph(b.content));
		else if (b.type === 'h') {
			if (level === 'block') content.push({ ...paragraph(b.content), type: N.heading, attrs: { level: b.level } });
			else content.push(paragraph(b.content));
		} else {
			content.push({
				type: b.type === 'ul' ? N.bulletList : N.orderedList,
				content: b.items.map((item) => ({ type: N.listItem, content: [paragraph(item)] }))
			});
		}
	}
	return { type: N.doc, content: content.length ? content : [{ type: N.paragraph }] };
}

// --- ProseMirror -> tree -----------------------------------------------------------------

function pmRuns(nodes: PmNode[] | undefined): InlineRun[] {
	const out: InlineRun[] = [];
	for (const n of nodes ?? []) {
		if (!isObj(n)) continue;
		if (n.type === N.hardBreak) out.push({ br: true });
		else if (n.type === N.pipe) {
			const id = n.attrs?.id;
			if (typeof id === 'string' && id.trim()) out.push({ pipe: id.trim() });
		} else if (n.type === N.text && typeof n.text === 'string') {
			const run: TextRun = { text: n.text };
			const marks: Mark[] = [];
			for (const m of n.marks ?? []) {
				if (m.type === M.bold) marks.push('b');
				else if (m.type === M.italic) marks.push('i');
				else if (m.type === M.link && typeof m.attrs?.href === 'string') run.href = m.attrs.href;
				else if (m.type === M.lang && typeof m.attrs?.lang === 'string') run.lang = m.attrs.lang;
			}
			if (marks.length) run.marks = marks;
			out.push(run);
		} else if (Array.isArray(n.content)) {
			// An unknown inline wrapper: keep its text.
			out.push(...pmRuns(n.content));
		}
	}
	return canonicalRuns(out);
}

/** The runs of a list item: its paragraphs joined by breaks (the model has no nesting). */
function itemRuns(item: PmNode): InlineRun[] {
	const runs: InlineRun[] = [];
	(item.content ?? []).forEach((child, i) => {
		if (i > 0) runs.push({ br: true });
		runs.push(...(Array.isArray(child.content) ? pmRuns(child.content) : pmRuns([child])));
	});
	return canonicalRuns(runs);
}

/** The tree for an editor document (canonical form). */
export function fromDoc(doc: PmNode): RichText {
	const blocks: RichBlock[] = [];
	for (const b of doc.content ?? []) {
		if (!isObj(b)) continue;
		if (b.type === N.paragraph) blocks.push({ type: 'p', content: pmRuns(b.content) });
		else if (b.type === N.heading) {
			const lv = Number(b.attrs?.level);
			blocks.push({ type: 'h', level: lv === 2 || lv === 3 ? lv : 1, content: pmRuns(b.content) });
		} else if (b.type === N.bulletList || b.type === N.orderedList) {
			const items = (b.content ?? []).filter((li) => li.type === N.listItem).map(itemRuns);
			blocks.push({ type: b.type === N.bulletList ? 'ul' : 'ol', items: items.length ? items : [[]] });
		} else if (Array.isArray(b.content)) {
			blocks.push({ type: 'p', content: pmRuns(b.content) });
		}
	}
	return { type: 'rich', blocks: blocks.length ? blocks : [{ type: 'p', content: [] }] };
}

// --- Inspection ----------------------------------------------------------------------------

/** Every pipe id of a value, in reading order (repeats kept). */
export function pipesOf(value: RichValue | undefined | null): string[] {
	const tree = asRich(value);
	const out: string[] = [];
	for (const b of tree.blocks) {
		const parts = 'items' in b ? b.items : [b.content];
		for (const runs of parts) for (const r of runs) if ('pipe' in r) out.push(r.pipe);
	}
	return out;
}

/** Whether a value shows nothing: no text and no pipes (an empty tree equals `""`). */
export function isEmptyValue(value: RichValue | undefined | null): boolean {
	if (value === undefined || value === null) return true;
	if (typeof value === 'string') return value.trim() === '';
	for (const b of asRich(value).blocks) {
		const parts = 'items' in b ? b.items : [b.content];
		for (const runs of parts) for (const r of runs) if ('pipe' in r || ('text' in r && r.text.trim() !== '')) return false;
	}
	return true;
}
