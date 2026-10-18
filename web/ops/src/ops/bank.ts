/**
 * Question bank ops (port of `osp_ops.bank_ops`): `insert_bank_item` inserts a bank item's
 * fragment as one op (fresh ids where the fragment's clash, shared choice lists reused,
 * `source` written, optionally a flow node), and `clear_source` drops provenance.
 *
 * The fragment check (`osp_spec.bank.check_fragment`: the fragment model, then the survey
 * validator on a throwaway survey holding it) comes from the injected validator.
 */

import { BLOCK, NODE, PAGE, QUESTION, get, insertAt, isFreeId, locate, remapIds } from '../doc.ts';
import { Source } from '../models.ts';
import { PyException } from '../patch.ts';
import { dump, validate } from '../pyd.ts';
import { deepCopy, get as dget, has, isObj, slice, type Json, type JsonObject } from '../py.ts';
import { REVERSE_PATCH, OpError, diag, op, type Ctx, type Diagnostic, type Invocation } from '../registry.ts';
import { canonicalJson, fragmentChecksum, fragmentKind } from '../spec.ts';
import { Index, JsonDict, opt, params, req, str } from './params.ts';

const ID_MAX = 64;
const MAX_ITEMS = 200;

const FlowPlacement = params('FlowPlacement', [opt('after', str)]);

const InsertBankItem = params('InsertBankItem', [
	req('fragment', JsonDict),
	req('source', JsonDict),
	opt('page', str),
	opt('block', str),
	Index,
	opt('flow', FlowPlacement)
]);

// --- id claiming -----------------------------------------------------------------------------------

class Claims {
	readonly ids = new Map<string, string>();
	readonly names = new Map<string, string>();
	readonly assigned = new Set<string>();
	constructor(readonly ctx: Ctx) {}

	free(candidate: string, rows: readonly string[]): boolean {
		return [candidate, ...rows.map((r) => `${candidate}_${r}`)].every((c) => isFreeId(this.ctx.doc, c, this.assigned));
	}

	pick(base: string, rows: readonly string[] = []): string {
		if (this.free(base, rows)) {
			this.assigned.add(base);
			return base;
		}
		for (let n = 2; ; n++) {
			const suffix = `_${n}`;
			const cand = `${slice(base, 0, Math.max(0, ID_MAX - suffix.length))}${suffix}`;
			if (this.free(cand, rows)) {
				this.assigned.add(cand);
				return cand;
			}
		}
	}

	claim(old: string, rows: readonly string[] = []): string {
		const nu = this.pick(old, rows);
		this.ids.set(old, nu);
		for (const r of rows) this.ids.set(`${old}_${r}`, `${nu}_${r}`);
		return nu;
	}

	claimName(name: string): void {
		if (!this.names.has(name)) this.names.set(name, this.pick(name));
	}
}

function rowsOf(q: JsonObject): string[] {
	if (dget(q, 'type') !== 'matrix') return [];
	const rows = dget(q, 'rows');
	return (Array.isArray(rows) ? rows : []).filter(isObj).map((r) => r.id as string);
}

function claimObject(claims: Claims, obj: JsonObject, kind: string): void {
	claims.claim(obj.id as string, kind === 'question' ? rowsOf(obj) : []);
	if (kind === 'question') {
		if (typeof dget(obj, 'name') === 'string') claims.claimName(obj.name as string);
		return;
	}
	for (const child of (kind === 'block' ? obj.pages : obj.items) as JsonObject[]) {
		claimObject(claims, child, kind === 'block' ? 'page' : 'question');
	}
}

function rebuild(obj: JsonObject, kind: string, claims: Claims): JsonObject {
	const children = kind === 'block' ? 'pages' : kind === 'page' ? 'items' : null;
	const out: JsonObject = { id: claims.ids.get(obj.id as string)! };
	for (const k of Object.keys(obj)) {
		if (k === 'id' || k === 'source' || k === children) continue;
		out[k] = deepCopy(obj[k]!);
	}
	if (kind === 'question' && typeof dget(out, 'name') === 'string') out.name = claims.names.get(out.name as string)!;
	if (children !== null) {
		out[children] = (obj[children] as JsonObject[]).map((c) => rebuild(c, kind === 'block' ? 'page' : 'question', claims));
	}
	return out;
}

// --- insert_bank_item ------------------------------------------------------------------------------

function* questionsOf(obj: JsonObject, kind: string): Generator<JsonObject> {
	if (kind === 'question') {
		yield obj;
		return;
	}
	const pages = kind === 'page' ? [obj] : ((dget(obj, 'pages') as Json[] | null | undefined) ?? []);
	for (const p of pages) {
		if (!isObj(p)) continue;
		for (const q of (dget(p, 'items') as Json[] | null | undefined) ?? []) if (isObj(q)) yield q;
	}
}

/** Without a validator: only "exactly one object" and the size limit of `check_fragment`. */
function minimalCheckFragment(fragment: Json): Diagnostic[] {
	if (!isObj(fragment)) return [{ severity: 'error', code: 'bank.fragment_invalid', message: 'a fragment must be a JSON object', pointer: '' }];
	const kind = fragmentKind(fragment);
	if (kind === null) {
		return [{ severity: 'error', code: 'bank.kind_mismatch', message: 'a fragment holds exactly one of question, page or block', pointer: '' }];
	}
	const obj = fragment[kind];
	const items = isObj(obj) ? [...questionsOf(obj, kind)].length : 0;
	if (items > MAX_ITEMS) {
		return [
			{ severity: 'error', code: 'bank.too_large', message: `${items} items; a fragment holds at most ${MAX_ITEMS}`, pointer: '/' + kind }
		];
	}
	return [];
}

function checkedFragment(ctx: Ctx, raw: JsonObject): [JsonObject, string] {
	const fragment = deepCopy(raw);
	const check = ctx.env.validator.checkFragment ?? minimalCheckFragment;
	const errors = check(fragment).filter((d) => d.severity === 'error');
	if (errors.length) {
		const [first, ...rest] = errors;
		throw new OpError(
			'op.params',
			`the fragment cannot be inserted: ${first!.message}`,
			'/fragment' + first!.pointer,
			...rest.slice(0, 19).map((d) => diag('op.params', d.message, '/fragment' + d.pointer))
		);
	}
	const kind = fragmentKind(fragment);
	if (kind === null) throw new PyException('AssertionError');
	return [fragment, kind];
}

function sourceOf(raw: JsonObject, fragment: JsonObject, localId: Json): JsonObject {
	const r = validate(Source, raw);
	if (!r.ok) {
		const e = r.errs[0]!;
		const where = '/source' + e.loc.filter((part) => typeof part === 'string').map((part) => `/${part}`).join('');
		throw new OpError('op.params', `source: ${slice(e.msg, 0, 200)}`, where);
	}
	const out = dump(r.v, { excludeNone: true }) as JsonObject;
	out.item = localId;
	const checksum = fragmentChecksum(fragment); // evaluated even when set, as `setdefault` does
	if (!has(out, 'checksum')) out.checksum = checksum;
	return out;
}

function destination(ctx: Ctx, p: { page: string | null; block: string | null; flow: Json }, kind: string): Json[] {
	const given: [string, Json][] = [
		['page', p.page],
		['block', p.block],
		['flow', p.flow]
	];
	const wanted = ({ question: 'page', page: 'block', block: 'flow' } as Record<string, string>)[kind];
	for (const [key, value] of given) {
		if (value !== null && key !== wanted) throw new OpError('op.params', `\`${key}\` does not apply when inserting a ${kind}`, `/${key}`);
	}
	if (kind === 'question') {
		if (p.page === null) throw new OpError('op.params', 'a question needs a destination `page`', '/page');
		return get(ctx.doc, locate(ctx, p.page, PAGE).path).items as Json[];
	}
	if (kind === 'page') {
		if (p.block === null) throw new OpError('op.params', 'a page needs a destination `block`', '/block');
		return get(ctx.doc, locate(ctx, p.block, BLOCK).path).pages as Json[];
	}
	if (!has(ctx.d, 'blocks')) ctx.d.blocks = [];
	return ctx.d.blocks as Json[];
}

function listOf(obj: JsonObject, key: string): Json[] {
	const v = dget(obj, key);
	return Array.isArray(v) ? v : [];
}

op('insert_bank_item', InsertBankItem, { label: 'Insert bank item', area: 'bank' }, (ctx, p): Invocation => {
	const [fragment, kind] = checkedFragment(ctx, p.fragment as JsonObject);
	const obj = fragment[kind] as JsonObject;
	const source = sourceOf(p.source as JsonObject, fragment, obj.id!);
	const dest = destination(ctx, p, kind);
	let flowList: Json[] | null = null;
	let flowIndex: number | null = null;
	if (kind === 'block' && p.flow !== null) {
		const after = (p.flow as JsonObject).after as string | null;
		if (after === null) {
			if (!has(ctx.d, 'flow')) ctx.d.flow = [];
			flowList = ctx.d.flow as Json[];
		} else {
			const loc = locate(ctx, after, NODE);
			flowList = get(ctx.doc, loc.container) as Json[];
			flowIndex = loc.index + 1;
		}
	}

	const claims = new Claims(ctx);
	claimObject(claims, obj, kind);
	const existing = new Map<string, string>();
	for (const cl of listOf(ctx.d, 'choiceLists') as JsonObject[]) {
		const key = canonicalJson(cl.choices!);
		if (!existing.has(key)) existing.set(key, cl.id as string);
	}
	const newLists: JsonObject[] = [];
	for (const cl of listOf(fragment, 'choiceLists') as JsonObject[]) {
		const key = canonicalJson(cl.choices!);
		if (existing.has(key)) claims.ids.set(cl.id as string, existing.get(key)!);
		else {
			existing.set(key, claims.claim(cl.id as string));
			newLists.push({ ...deepCopy(cl), id: existing.get(key)! });
		}
	}
	const newVars: JsonObject[] = [];
	for (const v of listOf(fragment, 'variables') as JsonObject[]) {
		newVars.push({ ...deepCopy(v), id: claims.claim(v.id as string) });
		if (typeof dget(v, 'name') === 'string') {
			claims.claimName(v.name as string);
			newVars[newVars.length - 1]!.name = claims.names.get(v.name as string)!;
		}
	}
	const inserted = remapIds(rebuild(obj, kind, claims), claims.ids) as JsonObject;
	inserted.source = source;
	if (newLists.length) {
		if (!has(ctx.d, 'choiceLists')) ctx.d.choiceLists = [];
		(ctx.d.choiceLists as Json[]).push(...(remapIds(newLists, claims.ids) as Json[]));
	}
	if (newVars.length) {
		if (!has(ctx.d, 'variables')) ctx.d.variables = [];
		(ctx.d.variables as Json[]).push(...(remapIds(newVars, claims.ids) as Json[]));
	}
	insertAt(dest, p.index, inserted);
	if (flowList !== null) {
		const id = inserted.id as string;
		const nodeId = claims.pick(`n_${slice(id, 0, ID_MAX - 2)}`);
		insertAt(flowList, flowIndex, { type: 'block', id: nodeId, block: id });
	}
	ctx.touch();
	return REVERSE_PATCH;
});

// --- clear_source ----------------------------------------------------------------------------------

const ClearSource = params('ClearSource', [req('target', str)]);

op('clear_source', ClearSource, { label: 'Detach from bank item', area: 'bank' }, (ctx, p): Invocation => {
	const loc = locate(ctx, p.target, QUESTION, PAGE, BLOCK);
	const obj = get(ctx.doc, loc.path) as JsonObject;
	if (dget(obj, 'source') === undefined || obj.source === null) {
		throw new OpError('op.not_applicable', `'${slice(p.target, 0, 64)}' carries no bank provenance`, loc.pointer);
	}
	delete obj.source;
	ctx.touch();
	return REVERSE_PATCH;
});
