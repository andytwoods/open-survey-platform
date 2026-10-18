/**
 * The question bank in the builder (task QB5, planning/question-bank.md §6): pure helpers
 * for the Bank section, the insert, the provenance line and the notices. No survey logic:
 * these only choose where an item goes (the server's `insert_bank_item` op validates) and
 * read what the survey already carries (`source` on question, page and block).
 */
import type { components } from '@osp/api-client';
import { walk } from '../flow/model';
import type { OutlineNode } from '../model/outline';
import type { DropTarget } from '../outline/moves';
import { placeOf, type Place } from '../structure/ops';
import type { Invocation } from '../sync/transport';
import type { PatchOperation } from '../sync/json-patch';

export type BankSummary = components['schemas']['BankSummaryOut'];
export type BankItemOut = components['schemas']['BankItemOut'];
export type BankList = components['schemas']['BankList'];
export type BankVersion = components['schemas']['BankVersionOut'];
export type BankPreviewOut = components['schemas']['BankPreviewOut'];
export type InstrumentStub = components['schemas']['InstrumentStubOut'];
export type BankKind = 'question' | 'page' | 'block';
export type BankSourceName = 'lab' | 'host' | 'bundled';

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const list = (v: unknown): Obj[] => (Array.isArray(v) ? v.filter(isObj) : []);

/** The `source` record an inserted question, page or block carries (osp_spec Source). */
export interface SourceRef {
	bank: string;
	version: number;
	library: 'lab' | 'host' | 'bundled' | 'file';
	item?: string;
	checksum?: string;
}

export function sourceOf(obj: unknown): SourceRef | null {
	if (!isObj(obj) || !isObj(obj.source)) return null;
	const s = obj.source;
	if (typeof s.bank !== 'string' || typeof s.version !== 'number' || typeof s.library !== 'string') return null;
	return s as unknown as SourceRef;
}

/** Every object (block, page, question) with its own `source`, in document order. */
export function ownSources(survey: unknown): { id: string; type: BankKind; source: SourceRef }[] {
	const out: { id: string; type: BankKind; source: SourceRef }[] = [];
	if (!isObj(survey)) return out;
	for (const b of list(survey.blocks)) {
		const bs = sourceOf(b);
		if (bs && typeof b.id === 'string') out.push({ id: b.id, type: 'block', source: bs });
		for (const p of list(b.pages)) {
			const ps = sourceOf(p);
			if (ps && typeof p.id === 'string') out.push({ id: p.id, type: 'page', source: ps });
			for (const q of list(p.items)) {
				const qs = sourceOf(q);
				if (qs && typeof q.id === 'string') out.push({ id: q.id, type: 'question', source: qs });
			}
		}
	}
	return out;
}

/** The highest version of bank item `id` the survey holds, or null when it holds none. */
export function insertedVersion(survey: unknown, id: string): number | null {
	let best: number | null = null;
	for (const s of ownSources(survey)) {
		if (s.source.bank === id && (best === null || s.source.version > best)) best = s.source.version;
	}
	return best;
}

/** "A newer version exists": the survey holds this item at a version below the current one. */
export function hasNewerVersion(summary: Pick<BankSummary, 'id' | 'version'>, survey: unknown): boolean {
	const v = insertedVersion(survey, summary.id);
	return v !== null && v < summary.version;
}

// -- where an item goes ------------------------------------------------------------------

/** The op's destination keys by kind: a question's page, a page's block, a block's index + flow. */
export type BankDestination =
	| { kind: 'question'; page: string; index?: number }
	| { kind: 'page'; block: string; index?: number }
	| { kind: 'block'; index?: number; flow: { after?: string } };

function lastBlock(roots: readonly OutlineNode[]): OutlineNode | undefined {
	return [...roots].reverse().find((b) => b.type === 'block');
}

/** The flow node showing `blockId`, if any (where a new block's node goes after). */
export function flowNodeOf(survey: unknown, blockId: string | undefined): string | undefined {
	if (!blockId) return undefined;
	return walk(survey).find((r) => r.type === 'block' && r.node.block === blockId)?.id;
}

function blockFlow(survey: unknown, roots: readonly OutlineNode[], index: number | undefined): { after?: string } {
	// After the block before the insertion point; at the very start (or without blocks)
	// the node is appended to the flow (the op has no "before").
	const before = index === undefined ? lastBlock(roots) : index > 0 ? roots[index - 1] : undefined;
	const after = flowNodeOf(survey, before?.type === 'block' ? before.id : undefined);
	return after ? { after } : {};
}

/**
 * "Insert" at the selection: a question after the selected question (else at the end of
 * the selected or last page), a page after the selected item's page (else at the end of
 * its block, else the last block), a block after the selected item's block (else last).
 * Null when the survey has nowhere to put it (no page for a question, no block for a page).
 */
export function destinationAtSelection(
	kind: BankKind,
	roots: readonly OutlineNode[],
	survey: unknown,
	selectedId: string | null
): BankDestination | null {
	const at = placeOf(roots, selectedId);
	if (kind === 'question') {
		let page: OutlineNode | undefined = at?.page;
		if (!page && at?.type === 'block') page = at.block.children?.at(-1);
		if (!page) page = lastBlock(roots)?.children?.at(-1) ?? roots.flatMap((b) => b.children ?? []).at(-1);
		if (!page) return null;
		const index = at?.type === 'question' && at.questionIndex !== undefined ? at.questionIndex + 1 : undefined;
		return { kind, page: page.id, ...(index !== undefined ? { index } : {}) };
	}
	if (kind === 'page') {
		const block = at?.block ?? lastBlock(roots);
		if (!block) return null;
		const index = at?.pageIndex !== undefined ? at.pageIndex + 1 : undefined;
		return { kind, block: block.id, ...(index !== undefined ? { index } : {}) };
	}
	const index = at ? at.blockIndex + 1 : undefined;
	return { kind, ...(index !== undefined ? { index } : {}), flow: blockFlow(survey, roots, index) };
}

/** The same place an object sits at now (for "Replace with v<n>": delete it, insert there). */
export function destinationReplacing(roots: readonly OutlineNode[], survey: unknown, at: Place): BankDestination {
	if (at.type === 'question') return { kind: 'question', page: at.page!.id, index: at.questionIndex ?? 0 };
	if (at.type === 'page') return { kind: 'page', block: at.block.id, index: at.pageIndex ?? 0 };
	return { kind: 'block', index: at.blockIndex, flow: blockFlow(survey, roots, at.blockIndex) };
}

/**
 * A drop on the canvas or outline gives a gap between questions (`parent` page, `slot`).
 * A question goes exactly there; a page goes before that page (top gap) or after it; a
 * block goes before that page's block (the very first gap) or after it.
 */
export function destinationFromGap(
	kind: BankKind,
	roots: readonly OutlineNode[],
	survey: unknown,
	target: DropTarget
): BankDestination | null {
	if (target.parent === null) return kind === 'block' ? { kind, index: target.slot, flow: blockFlow(survey, roots, target.slot) } : null;
	const at = placeOf(roots, target.parent);
	if (!at) return null;
	if (kind === 'question') {
		if (at.type !== 'page') return null;
		return { kind, page: at.page!.id, index: target.slot };
	}
	if (at.type === 'block') {
		if (kind === 'page') return { kind, block: at.block.id, index: target.slot };
		const index = at.blockIndex + 1;
		return { kind, index, flow: blockFlow(survey, roots, index) };
	}
	if (kind === 'page') return { kind, block: at.block.id, index: (at.pageIndex ?? 0) + (target.slot > 0 ? 1 : 0) };
	const first = (at.pageIndex ?? 0) === 0 && target.slot === 0;
	const index = at.blockIndex + (first ? 0 : 1);
	return { kind, index, flow: blockFlow(survey, roots, index) };
}

/** What a drop would do, for screen readers and the live hint. */
export function describeDestination(roots: readonly OutlineNode[], label: string, d: BankDestination): string {
	if (d.kind === 'question') {
		const page = roots.flatMap((b) => b.children ?? []).find((p) => p.id === d.page);
		const kids = page?.children ?? [];
		const where = page?.label ?? d.page;
		if (d.index === undefined || d.index >= kids.length) return `Insert ${label} at the end of ${where}`;
		if (d.index === 0) return `Insert ${label} at the start of ${where}`;
		return `Insert ${label} between ${kids[d.index - 1].label} and ${kids[d.index].label} on ${where}`;
	}
	if (d.kind === 'page') {
		const block = roots.find((b) => b.id === d.block);
		const kids = block?.children ?? [];
		const where = block?.label ?? d.block;
		if (d.index === undefined || d.index >= kids.length) return `Insert ${label} as the last page of ${where}`;
		if (d.index === 0) return `Insert ${label} as the first page of ${where}`;
		return `Insert ${label} as a page after ${kids[d.index - 1].label} in ${where}`;
	}
	if (d.index === undefined || d.index >= roots.length) return `Insert ${label} as a new block at the end`;
	if (d.index === 0) return `Insert ${label} as a new block before ${roots[0].label}`;
	return `Insert ${label} as a new block after ${roots[d.index - 1].label}`;
}

/** The `insert_bank_item` op for an item's document at a destination. */
export function insertOp(summary: Pick<BankSummary, 'id' | 'source'>, item: BankItemOut, d: BankDestination): Invocation {
	const source: Record<string, unknown> = { bank: summary.id, version: item.version, library: summary.source };
	if (item.checksum) source.checksum = item.checksum;
	const { kind, ...where } = d;
	void kind;
	return { op: 'insert_bank_item', params: { fragment: item.document.fragment, source, ...where } };
}

/** The id of the block, page or question a patch added (the inserted object). */
export function addedObjectId(patch: readonly PatchOperation[], kind: BankKind): string | undefined {
	const re = {
		block: /^\/blocks\/(\d+|-)$/,
		page: /^\/blocks\/\d+\/pages\/(\d+|-)$/,
		question: /^\/blocks\/\d+\/pages\/\d+\/items\/(\d+|-)$/
	}[kind];
	for (const p of patch) {
		if (p.op === 'add' && re.test(p.path) && isObj(p.value) && typeof p.value.id === 'string') return p.value.id;
	}
	return undefined;
}

// -- what an item holds ------------------------------------------------------------------

export interface PreviewItem {
	id: string;
	type: string;
	label: string;
	/** Matrix rows or inline/shared choice labels, for a glance at the content. */
	rows?: string[];
	choices?: string[];
}

export function textOf(text: unknown, lang?: string): string {
	if (typeof text === 'string') return text;
	if (!isObj(text)) return '';
	const keys = Object.keys(text);
	const k = lang && typeof text[lang] === 'string' ? lang : keys.find((x) => typeof text[x] === 'string');
	return k ? String(text[k]) : '';
}

/** The items of a bank item's fragment (question, page or block), flattened for a preview. */
export function fragmentItems(document: unknown, lang?: string): PreviewItem[] {
	if (!isObj(document) || !isObj(document.fragment)) return [];
	const f = document.fragment;
	const lists = new Map(list(f.choiceLists).map((cl) => [String(cl.id), list(cl.choices).map((c) => textOf(c.label, lang))]));
	const questions: Obj[] = [];
	if (isObj(f.question)) questions.push(f.question);
	else if (isObj(f.page)) questions.push(...list(f.page.items));
	else if (isObj(f.block)) for (const p of list(f.block.pages)) questions.push(...list(p.items));
	return questions.map((q) => {
		const out: PreviewItem = { id: String(q.id ?? ''), type: String(q.type ?? ''), label: textOf(q.label, lang) };
		if (q.type === 'matrix') out.rows = list(q.rows).map((r) => textOf(r.label, lang));
		const inline = Array.isArray(q.choices) ? list(q.choices).map((c) => textOf(c.label, lang)) : undefined;
		const shared = typeof q.choiceList === 'string' ? lists.get(q.choiceList) : undefined;
		if (inline?.length || shared?.length) out.choices = inline?.length ? inline : shared;
		return out;
	});
}

/** The scoring variables a fragment carries. */
export function fragmentVariables(document: unknown): string[] {
	if (!isObj(document) || !isObj(document.fragment)) return [];
	return list(document.fragment.variables).map((v) => String(v.id ?? ''));
}

// -- words -------------------------------------------------------------------------------

export const LICENCE_LABELS: Record<string, string> = {
	'public-domain': 'Public domain',
	cc0: 'CC0',
	'cc-by-4.0': 'CC BY 4.0',
	'free-use': 'Free to use',
	'author-permission': 'With permission',
	'free-noncommercial': 'Non-commercial',
	'licensed-to-lab': 'Licensed to this lab',
	unknown: 'Licence not stated'
};

/** Licence classes a researcher can give a lab item when saving (question-bank.md §2.1). */
export const SAVE_LICENCES: { value: string; label: string; hint: string }[] = [
	{ value: 'unknown', label: 'Not stated (default)', hint: 'Fine for the lab; cannot be shared with other labs until a licence is chosen.' },
	{ value: 'cc-by-4.0', label: 'Our own words, CC BY 4.0', hint: 'The lab wrote these items and lets others reuse them with credit.' },
	{ value: 'cc0', label: 'Our own words, CC0 (public domain dedication)', hint: 'No conditions on reuse.' },
	{ value: 'public-domain', label: 'Public domain (published as such)', hint: 'The holder states the items are in the public domain.' },
	{ value: 'author-permission', label: 'Written permission from the author', hint: 'Keep the letter with your lab records.' },
	{ value: 'free-use', label: 'Free to use (redistribution not stated)', hint: 'Can be used here; not shared at host level.' },
	{ value: 'free-noncommercial', label: 'Free for non-commercial research', hint: 'Shown as a notice whenever it is inserted.' },
	{ value: 'licensed-to-lab', label: 'Licensed to this lab (owners only)', hint: 'Stays private to the lab; never shared or exported except as backup.' }
];

export const SOURCE_LABELS: Record<string, string> = { lab: 'My lab', host: 'Shared on this host', bundled: 'Bundled', file: 'From a file' };
export const KIND_LABELS: Record<BankKind, string> = { question: 'Question', page: 'Page', block: 'Block' };

/** "PHQ-9 · bundled · v1": the provenance line of an inserted object. */
export function provenanceLabel(source: SourceRef, title?: string | null): string {
	const name = title && title.trim() ? title : source.bank;
	return `${name} · ${(SOURCE_LABELS[source.library] ?? source.library).toLowerCase()} · v${source.version}`;
}

/**
 * The notice an insert shows once per survey (question-bank.md §6): a non-commercial
 * item's condition, a licensed item's privacy reminder. Null for the other classes.
 */
export function insertNotice(summary: Pick<BankSummary, 'licenceClass' | 'title'>, document: unknown): string | null {
	const doc = isObj(document) ? document : {};
	const licence = isObj(doc.licence) ? doc.licence : {};
	const citation = isObj(doc.citation) && typeof doc.citation.text === 'string' ? doc.citation.text : '';
	if (summary.licenceClass === 'free-noncommercial') {
		const holder = typeof licence.holder === 'string' ? ` (${licence.holder})` : '';
		return `${summary.title}${holder}: free for non-commercial research only.${citation ? ` Cite: ${citation}` : ''}`;
	}
	if (summary.licenceClass === 'licensed-to-lab') {
		return `${summary.title} is licensed to this lab: do not share this survey's JSON outside the lab.`;
	}
	return null;
}

export const NOTICE_KEY = (surveyId: string, licenceClass: string) => `osp.bank.notice.${surveyId}.${licenceClass}`;

/** Was this notice shown for this survey already (in this browser session)? Remembers it. */
export function noticeShownOnce(
	surveyId: string,
	licenceClass: string,
	storage: Pick<Storage, 'getItem' | 'setItem'> | undefined = safeSession()
): boolean {
	const key = NOTICE_KEY(surveyId, licenceClass);
	try {
		if (storage?.getItem(key)) return true;
		storage?.setItem(key, '1');
	} catch {
		// Blocked storage: show it every time.
	}
	return false;
}

function safeSession(): Storage | undefined {
	try {
		return typeof sessionStorage === 'undefined' ? undefined : sessionStorage;
	} catch {
		return undefined;
	}
}

/** Tags typed as "a, b; c" → ["a", "b", "c"] (unique, trimmed, at most 20 of 40 chars). */
export function parseTags(text: string): string[] {
	const out: string[] = [];
	for (const raw of text.split(/[,;\n]/)) {
		const t = raw.trim().slice(0, 40);
		if (t && !out.includes(t)) out.push(t);
	}
	return out.slice(0, 20);
}

/** Item lines for the licensed-instrument wizard: non-empty, trimmed. */
export function itemLines(text: string): string[] {
	return text
		.split(/\r?\n/)
		.map((l) => l.trim())
		.filter(Boolean);
}

/** Labels added and removed between two versions' items (a plain diff for the Versions dialog). */
export function labelDiff(older: unknown, newer: unknown): { added: string[]; removed: string[] } {
	const a = fragmentItems(older).flatMap((i) => [i.label, ...(i.rows ?? [])]);
	const b = fragmentItems(newer).flatMap((i) => [i.label, ...(i.rows ?? [])]);
	return { added: b.filter((x) => !a.includes(x)), removed: a.filter((x) => !b.includes(x)) };
}

/** The file name of an exported bank item. */
export function exportFileName(summary: Pick<BankSummary, 'abbreviation' | 'title' | 'id' | 'version'>): string {
	const stem = (summary.abbreviation || summary.title || summary.id).replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || 'bank-item';
	return `${stem}-v${summary.version}.osp-bank.json`;
}
