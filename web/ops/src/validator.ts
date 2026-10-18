/**
 * The default validator: `@osp/spec`'s `parse` / `validate` (port of `osp_spec`), a port of
 * `osp_spec.bank.check_fragment` on top of them, and `@osp/engine`'s `parseExpr` (port of
 * `osp_expr.parse`) for condition text.
 */

import { parseExpr } from '@osp/engine';
import { Fragment, parse as specParse, pointer, validate as specValidate } from '@osp/spec';
import { has, isObj, slice, type Json, type JsonObject } from './py.ts';
import { fragmentKind, isRich } from './spec.ts';
import type { Diagnostic, ParsedExpression, Validator } from './types.ts';

const MAX_ITEMS = 200;
const TEXT_KEYS = new Set(['label', 'help', 'constraintMessage', 'title', 'minLabel', 'maxLabel', 'message']);
const CONDITION_KEYS = new Set(['showIf', 'constraint']);

function bank(code: string, ptr: string, message: string): Diagnostic {
	const severity = code === 'bank.external_ref' ? 'warning' : 'error';
	return { severity, code, message, pointer: ptr };
}

function* questionsOf(obj: JsonObject, kind: string): Generator<JsonObject> {
	if (kind === 'question') {
		yield obj;
		return;
	}
	const pages = kind === 'page' ? [obj] : ((obj.pages as Json[] | null | undefined) ?? []);
	for (const p of pages) {
		const items = isObj(p) ? ((p.items as Json[] | null | undefined) ?? []) : [];
		for (const q of items) if (isObj(q)) yield q;
	}
}

function* textMaps(obj: Json): Generator<JsonObject> {
	if (isObj(obj)) {
		for (const k of Object.keys(obj)) {
			const v = obj[k]!;
			if (TEXT_KEYS.has(k) && isObj(v) && !isRich(v)) yield v;
			else if (!CONDITION_KEYS.has(k)) yield* textMaps(v);
		}
	} else if (Array.isArray(obj)) for (const v of obj) yield* textMaps(v);
}

function allIds(obj: Json, out: Set<string>): Set<string> {
	if (isObj(obj)) {
		if (typeof obj.id === 'string' && has(obj, 'id')) out.add(obj.id);
		for (const k of Object.keys(obj)) allIds(obj[k]!, out);
	} else if (Array.isArray(obj)) for (const v of obj) allIds(v, out);
	return out;
}

function fresh(base: string, taken: Set<string>): string {
	let name = base;
	let n = 2;
	while (taken.has(name)) name = `${base}_${n++}`;
	taken.add(name);
	return name;
}

/** `osp_spec.bank.fragment_survey`: a one-block survey holding the fragment, and where it is. */
function fragmentSurvey(fragment: JsonObject): [JsonObject, string] {
	const kind = fragmentKind(fragment) ?? 'block';
	const obj = has(fragment, kind) ? fragment[kind]! : null;
	const taken = allIds(fragment, new Set());
	const langs: string[] = [];
	for (const m of textMaps(fragment)) for (const lang of Object.keys(m)) if (!langs.includes(lang)) langs.push(lang);
	let block: Json;
	let where: string;
	if (kind === 'block') {
		block = obj;
		where = '/blocks/0';
	} else if (kind === 'page') {
		block = { id: fresh('osp_bank_block', taken), pages: [obj] };
		where = '/blocks/0/pages/0';
	} else {
		const page = { id: fresh('osp_bank_page', taken), items: [obj] };
		block = { id: fresh('osp_bank_block', taken), pages: [page] };
		where = '/blocks/0/pages/0/items/0';
	}
	const blockId = isObj(block) && has(block, 'id') ? block.id! : null;
	const list = (k: string): Json[] => (Array.isArray(fragment[k]) ? [...(fragment[k] as Json[])] : []);
	const survey: JsonObject = {
		specVersion: 'osp-survey/0.1',
		id: 'osp_bank_fragment',
		metadata: { title: 'Bank fragment', languages: langs.length ? langs : ['en'] },
		choiceLists: list('choiceLists'),
		variables: list('variables'),
		blocks: [block],
		flow: [{ type: 'block', id: fresh('osp_bank_flow', taken), block: blockId }]
	};
	return [survey, where];
}

function remap(ptr: string, where: string, kind: string): string {
	if (ptr.startsWith(where)) return '/' + kind + ptr.slice(where.length);
	for (const top of ['/choiceLists', '/variables']) if (ptr === top || ptr.startsWith(top + '/')) return ptr;
	return '';
}

/** `osp_spec.bank.check_fragment`. Never throws. */
export function checkFragment(fragment: Json): Diagnostic[] {
	try {
		if (!isObj(fragment)) return [bank('bank.fragment_invalid', '', 'a fragment must be a JSON object')];
		const r = Fragment.run(fragment);
		if (!r.ok) return r.errors.slice(0, 20).map((e) => bank('bank.fragment_invalid', pointer(...e.loc), slice(e.msg, 0, 200)));
		const kind = fragmentKind(fragment);
		if (kind === null) return [bank('bank.kind_mismatch', '', 'a fragment holds exactly one of question, page or block')];
		const items = [...questionsOf(fragment[kind] as JsonObject, kind)].length;
		if (items > MAX_ITEMS) return [bank('bank.too_large', '/' + kind, `${items} items; a fragment holds at most ${MAX_ITEMS}`)];
		const [survey, where] = fragmentSurvey(fragment);
		return specValidate(survey)
			.filter((d) => d.code !== 'flow.empty' && d.code !== 'block.unused')
			.map((d) => ({ ...d, pointer: remap(d.pointer, where, kind) }));
	} catch (e) {
		return [bank('bank.fragment_invalid', '', slice(`could not check: ${e instanceof Error ? e.name : 'Exception'}`, 0, 200))];
	}
}

function parseExpression(text: string): ParsedExpression {
	const r = parseExpr(text);
	if (r.ok && r.expr !== null) return { expr: r.expr as unknown as Json };
	return { expr: null, diagnostics: r.diagnostics.map((d) => ({ code: d.code, message: d.message, start: d.start, end: d.end })) };
}

/** The validator the ops use by default (the ported osp-spec and osp-expr). */
export const SPEC_VALIDATOR: Validator = {
	parse(doc) {
		const [model, diagnostics] = specParse(doc);
		return { valid: model !== null, diagnostics: diagnostics as Diagnostic[] };
	},
	validate: (doc) => specValidate(doc) as Diagnostic[],
	checkFragment,
	parseExpression
};
