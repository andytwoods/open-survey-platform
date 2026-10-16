/**
 * Read-only projection of an osp-survey draft into the tree the panes display
 * (blocks → pages → questions). Display only: no validation, no defaults, no survey
 * semantics. Anything malformed is skipped rather than thrown on (the server owns
 * validity). The mock tree (`?mock`) uses the same node shape.
 */
import type { PatchOperation } from '../sync/json-patch';

export type NodeType = 'survey' | 'block' | 'page' | 'question';
export type Family = 'choice' | 'text' | 'number' | 'matrix' | 'scale' | 'note';

export interface OutlineNode {
	id: string;
	type: NodeType;
	label: string;
	/** Display-only card family. */
	family?: Family;
	/** The question's model type (e.g. "single"), for display. */
	questionType?: string;
	children?: OutlineNode[];
}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const list = (v: unknown): Obj[] => (Array.isArray(v) ? v.filter(isObj) : []);

const FAMILY: Record<string, Family> = {
	integer: 'number',
	decimal: 'number',
	text: 'text',
	date: 'text',
	single: 'choice',
	multi: 'choice',
	note: 'note'
};

export function defaultLanguage(doc: unknown): string {
	const meta = isObj(doc) ? doc.metadata : undefined;
	if (isObj(meta)) {
		if (typeof meta.defaultLanguage === 'string') return meta.defaultLanguage;
		if (Array.isArray(meta.languages) && typeof meta.languages[0] === 'string') return meta.languages[0];
	}
	return 'en';
}

/** A Text value (string or {lang: string}) in `lang`, falling back to any language. */
export function textIn(text: unknown, lang: string): string {
	if (typeof text === 'string') return text;
	if (isObj(text)) {
		const v = text[lang];
		if (typeof v === 'string') return v;
		const first = Object.values(text).find((x) => typeof x === 'string');
		return typeof first === 'string' ? first : '';
	}
	return '';
}

/** `old` with its `lang` text replaced: keeps other languages, keeps a plain string plain. */
export function withText(old: unknown, lang: string, value: string): string | Record<string, string> {
	if (isObj(old)) {
		const out: Record<string, string> = {};
		for (const [k, v] of Object.entries(old)) if (typeof v === 'string') out[k] = v;
		out[lang] = value;
		return out;
	}
	if (typeof old === 'string') return value;
	return { [lang]: value };
}

export function surveyTitle(doc: unknown): string {
	return isObj(doc) && isObj(doc.metadata) ? textIn(doc.metadata.title, defaultLanguage(doc)).trim() : '';
}

export function outlineFromSurvey(doc: unknown): OutlineNode[] {
	if (!isObj(doc)) return [];
	const lang = defaultLanguage(doc);
	return list(doc.blocks)
		.filter((b) => typeof b.id === 'string')
		.map((b) => ({
			id: b.id as string,
			type: 'block' as const,
			label: (typeof b.title === 'string' && b.title.trim()) || (b.id as string),
			children: list(b.pages)
				.filter((p) => typeof p.id === 'string')
				.map((p) => ({
					id: p.id as string,
					type: 'page' as const,
					label: textIn(p.title, lang).trim() || (p.id as string),
					children: list(p.items)
						.filter((q) => typeof q.id === 'string')
						.map((q) => {
							const qt = typeof q.type === 'string' ? q.type : '';
							return {
								id: q.id as string,
								type: 'question' as const,
								label: textIn(q.label, lang).trim() || `(${q.id as string})`,
								family: FAMILY[qt] ?? 'text',
								questionType: qt
							};
						})
				}))
		}));
}

/** The raw model object with this id (block, page or question), for property editors. */
export function findObject(doc: unknown, id: string): Obj | undefined {
	if (!isObj(doc)) return undefined;
	for (const b of list(doc.blocks)) {
		if (b.id === id) return b;
		for (const p of list(b.pages)) {
			if (p.id === id) return p;
			for (const q of list(p.items)) if (q.id === id) return q;
		}
	}
	return undefined;
}

/** Where "Add question" goes: the selected page, the selected question's page, else the last page. */
export function targetPage(roots: readonly OutlineNode[], selectedId: string | null): string | undefined {
	let last: string | undefined;
	for (const b of roots) {
		for (const p of b.children ?? []) {
			last = p.id;
			if (selectedId && (p.id === selectedId || p.children?.some((q) => q.id === selectedId))) return p.id;
		}
		if (selectedId === b.id && b.children?.length) return b.children[b.children.length - 1].id;
	}
	return last;
}

/** Ids of every node in the tree. */
export function allIds(roots: readonly OutlineNode[], out = new Set<string>()): Set<string> {
	for (const n of roots) {
		out.add(n.id);
		if (n.children) allIds(n.children, out);
	}
	return out;
}

/** JSON pointer of the block, page or question with this id (to match diagnostics). */
export function pointerOf(doc: unknown, id: string): string | undefined {
	if (!isObj(doc) || !Array.isArray(doc.blocks)) return undefined;
	for (const [bi, b] of doc.blocks.entries()) {
		if (!isObj(b)) continue;
		if (b.id === id) return `/blocks/${bi}`;
		if (!Array.isArray(b.pages)) continue;
		for (const [pi, p] of b.pages.entries()) {
			if (!isObj(p)) continue;
			if (p.id === id) return `/blocks/${bi}/pages/${pi}`;
			if (!Array.isArray(p.items)) continue;
			for (const [qi, q] of p.items.entries()) {
				if (isObj(q) && q.id === id) return `/blocks/${bi}/pages/${pi}/items/${qi}`;
			}
		}
	}
	return undefined;
}

/** Does a diagnostic at `pointer` concern the object at `base` (itself or inside it)? */
export function pointerWithin(pointer: string, base: string): boolean {
	return pointer === base || pointer.startsWith(base + '/');
}

/** The id of a question the patch added (to select it after "Add question"). */
export function addedQuestionId(patch: readonly PatchOperation[]): string | undefined {
	for (const p of patch) {
		if (p.op === 'add' && /^\/blocks\/\d+\/pages\/\d+\/items\/(\d+|-)$/.test(p.path) && isObj(p.value)) {
			if (typeof p.value.id === 'string') return p.value.id;
		}
	}
	return undefined;
}
