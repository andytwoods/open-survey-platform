/**
 * Helpers over the survey as plain JSON (port of `osp_ops.doc`): locating objects by id,
 * fresh ids, and finding (and repairing) references. Ops only run on structurally valid
 * surveys, so the shapes here are the `osp-spec` model's shapes.
 */

import { KEYWORDS } from './models.ts';
import { PyException, toPointer, type PathPart } from './patch.ts';
import { deepCopy, get as dget, has, isObj, pyLen, reprStr, slice, strip, type Json, type JsonObject } from './py.ts';
import { Ctx, OpError, diag, setIndexBuilder } from './registry.ts';
import { RESERVED_NAMES, isRich, pipesOf } from './spec.ts';

import { Loc, type Path } from './loc.ts';

export { Loc, type Path };

/** `^[A-Za-z_][A-Za-z0-9_]*$` as Python's `re.match` reads it (`$` also matches before a final newline). */
export const IDENT = /^[A-Za-z_][A-Za-z0-9_]*\n?$/;
export const PIPE = /\$\{([^}]*)\}/g;

export const QUESTION = 'question';
export const PAGE = 'page';
export const BLOCK = 'block';
export const CHOICE_LIST = 'choiceList';
export const VARIABLE = 'variable';
export const QUOTA = 'quota';
export const NODE = 'node';

// --- paths -------------------------------------------------------------------------------------

/** Follow `path` into `doc` (the shapes are known: the survey parsed). */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function get(doc: Json, path: readonly PathPart[]): any {
	let cur: Json = doc;
	for (const p of path) {
		if (Array.isArray(cur)) cur = cur[p as number]!;
		else cur = (cur as JsonObject)[p as string]!;
		if (cur === undefined) throw new PyException('KeyError');
	}
	return cur;
}

/** `obj.get(key, [])` for a list-valued key. */
function list(obj: JsonObject, key: string): Json[] {
	const v = has(obj, key) ? obj[key] : undefined;
	return Array.isArray(v) ? v : [];
}

/** Every flow node with its path, depth first, parents before children. */
export function* flowNodes(nodes: Json[], path: Path): Generator<[Path, JsonObject]> {
	for (let i = 0; i < nodes.length; i++) {
		const n = nodes[i] as JsonObject;
		const np = [...path, i];
		yield [np, n];
		if (dget(n, 'type') === 'branch') {
			yield* flowNodes(list(n, 'then'), [...np, 'then']);
			yield* flowNodes(list(n, 'else'), [...np, 'else']);
		} else if (dget(n, 'type') === 'randomiser') {
			yield* flowNodes(list(n, 'children'), [...np, 'children']);
		}
	}
}

/** Id -> location. With duplicate ids (a broken survey) the first one wins. */
export function buildIndex(doc: Json): Map<string, Loc> {
	const out = new Map<string, Loc>();
	const d = doc as JsonObject;
	const claim = (id: Json | undefined, loc: Loc): void => {
		if (typeof id === 'string' && !out.has(id)) out.set(id, loc);
	};
	list(d, 'choiceLists').forEach((cl, i) => claim((cl as JsonObject).id, new Loc(CHOICE_LIST, ['choiceLists', i])));
	list(d, 'blocks').forEach((b, i) => {
		const bo = b as JsonObject;
		claim(bo.id, new Loc(BLOCK, ['blocks', i]));
		(bo.pages as JsonObject[]).forEach((page, j) => {
			claim(page.id, new Loc(PAGE, ['blocks', i, 'pages', j]));
			(page.items as JsonObject[]).forEach((q, k) => claim(q.id, new Loc(QUESTION, ['blocks', i, 'pages', j, 'items', k])));
		});
	});
	list(d, 'variables').forEach((v, i) => claim((v as JsonObject).id, new Loc(VARIABLE, ['variables', i])));
	list(d, 'quotas').forEach((q, i) => claim((q as JsonObject).id, new Loc(QUOTA, ['quotas', i])));
	for (const [path, n] of flowNodes(list(d, 'flow'), ['flow'])) claim(n.id, new Loc(NODE, path));
	return out;
}

setIndexBuilder(buildIndex);

export function locate(ctx: Ctx, id: string, ...kinds: string[]): Loc {
	const loc = ctx.index().get(id);
	if (loc === undefined || (kinds.length && !kinds.includes(loc.kind))) {
		const what = kinds.length ? kinds.join(' or ') : 'object';
		throw new OpError('op.not_found', `no ${what} with id ${reprStr(slice(id, 0, 64))}`);
	}
	return loc;
}

/** Every id and explicit variable name in use, plus the survey id. */
export function takenNames(doc: Json): Set<string> {
	const d = doc as JsonObject;
	const names = new Set(buildIndex(doc).keys());
	names.add((dget(d, 'id') as string | undefined) ?? '');
	for (const b of list(d, 'blocks')) {
		for (const page of (b as JsonObject).pages as JsonObject[]) {
			for (const q of page.items as JsonObject[]) {
				if (typeof dget(q, 'name') === 'string') names.add(q.name as string);
				for (const r of rowVariables(q)) names.add(r);
			}
		}
	}
	for (const v of list(d, 'variables')) {
		const vo = v as JsonObject;
		if (typeof dget(vo, 'name') === 'string') names.add(vo.name as string);
	}
	return names;
}

/** A matrix's row variable ids `<id>_<row>` and export names `<name>_<row>`. */
export function rowVariables(q: JsonObject): Set<string> {
	if (dget(q, 'type') !== 'matrix') return new Set();
	const name = dget(q, 'name');
	const prefixes = new Set([q.id as string, (truthyStr(name) ? name : q.id) as string]);
	const rows = dget(q, 'rows');
	const out = new Set<string>();
	for (const p of prefixes) for (const r of Array.isArray(rows) ? rows : []) out.add(`${p}_${(r as JsonObject).id as string}`);
	return out;
}

function truthyStr(v: Json | undefined): boolean {
	return v !== undefined && v !== null && v !== '' && v !== false && v !== 0;
}

function lowerSet(names: Iterable<string>): Set<string> {
	const out = new Set<string>();
	for (const n of names) out.add(n.toLowerCase());
	return out;
}

function isFree(candidate: string, takenLower: Set<string>): boolean {
	return (
		!takenLower.has(candidate.toLowerCase()) &&
		!KEYWORDS.has(candidate) &&
		!RESERVED_NAMES.has(candidate.toLowerCase()) &&
		pyLen(candidate) <= 64
	);
}

/** Whether `candidate` could be a new id or name (case-insensitive, not reserved, <= 64). */
export function isFreeId(doc: Json, candidate: string, also: Set<string> = new Set()): boolean {
	return isFree(candidate, lowerSet([...takenNames(doc), ...also]));
}

/** The first free id `prefix1`, `prefix2` ... (or `prefix` itself if `exactFirst`). */
export function freshId(doc: Json, prefix: string, o: { exactFirst?: boolean; also?: Set<string> } = {}): string {
	const taken = lowerSet([...takenNames(doc), ...(o.also ?? [])]);
	if (o.exactFirst && isFree(prefix, taken)) return prefix;
	let n = 1;
	while (!isFree(`${prefix}${n}`, taken)) n++;
	return `${prefix}${n}`;
}

/** A caller-chosen id (checked: valid identifier, not in use) or a fresh one. */
export function claimId(ctx: Ctx, id: string | null, prefix: string): string {
	if (id === null) return freshId(ctx.doc, prefix);
	if (!IDENT.test(id) || pyLen(id) > 64) throw new OpError('op.params', `${reprStr(slice(id, 0, 64))} is not a valid id`, '/id');
	if (takenNames(ctx.doc).has(id)) throw new OpError('op.duplicate_id', `id ${reprStr(id)} is already used`, '/id');
	return id;
}

/** Insert (null = append). Returns the index used. Index may equal length (append). */
export function insertAt(lst: Json[], index: number | null, item: Json): number {
	if (index === null) {
		lst.push(item);
		return lst.length - 1;
	}
	if (index > lst.length) throw new OpError('op.not_allowed', `index ${index} is past the end (length ${lst.length})`);
	lst.splice(index, 0, item);
	return index;
}

// --- text and expression sites -------------------------------------------------------------------

const TEXT_KEYS_QUESTION = ['label', 'help', 'constraintMessage', 'minLabel', 'maxLabel'];

function present(obj: JsonObject, key: string): boolean {
	return has(obj, key) && obj[key] !== null;
}

/** Every translatable `Text` value in the survey, with its path. */
export function* textSites(doc: Json): Generator<[Path, Json]> {
	const d = doc as JsonObject;
	const md = (dget(d, 'metadata') ?? {}) as JsonObject;
	for (const key of ['title', 'description']) if (present(md, key)) yield [['metadata', key], md[key]!];
	const consent = dget(d, 'consent');
	if (isObj(consent)) {
		for (const key of ['text', 'agreeLabel', 'declineLabel']) if (present(consent, key)) yield [['consent', key], consent[key]!];
	}
	const lists = list(d, 'choiceLists');
	for (let i = 0; i < lists.length; i++) {
		const choices = (lists[i] as JsonObject).choices as JsonObject[];
		for (let k = 0; k < choices.length; k++) yield [['choiceLists', i, 'choices', k, 'label'], choices[k]!.label!];
	}
	const blocks = list(d, 'blocks');
	for (let i = 0; i < blocks.length; i++) {
		const pages = (blocks[i] as JsonObject).pages as JsonObject[];
		for (let j = 0; j < pages.length; j++) {
			const page = pages[j]!;
			if (present(page, 'title')) yield [['blocks', i, 'pages', j, 'title'], page.title!];
			const items = page.items as JsonObject[];
			for (let k = 0; k < items.length; k++) {
				const q = items[k]!;
				const qp: Path = ['blocks', i, 'pages', j, 'items', k];
				for (const key of TEXT_KEYS_QUESTION) if (present(q, key)) yield [[...qp, key], q[key]!];
				const choices = dget(q, 'choices');
				if (Array.isArray(choices) && choices.length) {
					for (let m = 0; m < choices.length; m++) yield [[...qp, 'choices', m, 'label'], (choices[m] as JsonObject).label!];
				}
				if (dget(q, 'type') === 'matrix') {
					const rows = dget(q, 'rows');
					if (Array.isArray(rows)) {
						for (let m = 0; m < rows.length; m++) yield [[...qp, 'rows', m, 'label'], (rows[m] as JsonObject).label!];
					}
				}
			}
		}
	}
	for (const [path, n] of flowNodes(list(d, 'flow'), ['flow'])) {
		if (dget(n, 'type') === 'end' && present(n, 'message')) yield [[...path, 'message'], n.message!];
	}
	const settings = dget(d, 'settings');
	const endings = isObj(settings) ? dget(settings, 'endings') : undefined;
	if (isObj(endings)) {
		const eo = endings;
		for (const outcome of Object.keys(eo)) {
			const ending = eo[outcome];
			if (!isObj(ending)) continue;
			for (const key of ['title', 'body']) {
				if (present(ending, key)) yield [['settings', 'endings', outcome, key], ending[key]!];
			}
			const redirect = dget(ending, 'redirect');
			if (isObj(redirect)) {
				if (present(redirect, 'label')) yield [['settings', 'endings', outcome, 'redirect', 'label'], redirect.label!];
				const params = dget(redirect, 'params');
				if (isObj(params)) {
					for (const name of Object.keys(params)) {
						yield [['settings', 'endings', outcome, 'redirect', 'params', name], params[name]!];
					}
				}
			}
		}
	}
}

/** The plain strings of a `Text` (a string, or the plain ones per language). */
export function* stringsOf(text: Json, path: Path): Generator<[Path, string]> {
	if (typeof text === 'string') yield [path, text];
	else if (isObj(text) && !isRich(text)) {
		for (const lang of Object.keys(text)) {
			const s = text[lang];
			if (typeof s === 'string') yield [[...path, lang], s];
		}
	}
}

/** The `{pipe: id}` nodes of a `Text`'s rich trees, as `(path to the node, id)`. */
export function* pipeNodesOf(text: Json, path: Path): Generator<[Path, string]> {
	if (isRich(text)) {
		for (const [sub, pid] of pipesOf(text)) yield [[...path, ...sub], pid];
	} else if (isObj(text)) {
		for (const lang of Object.keys(text)) {
			const v = text[lang]!;
			if (isRich(v)) for (const [sub, pid] of pipesOf(v)) yield [[...path, lang, ...sub], pid];
		}
	}
}

/** Every expression with its path and whether the field is required. */
export function* exprSites(doc: Json): Generator<[Path, boolean, Json]> {
	const d = doc as JsonObject;
	const blocks = list(d, 'blocks');
	for (let i = 0; i < blocks.length; i++) {
		const pages = (blocks[i] as JsonObject).pages as JsonObject[];
		for (let j = 0; j < pages.length; j++) {
			const items = pages[j]!.items as JsonObject[];
			for (let k = 0; k < items.length; k++) {
				const q = items[k]!;
				for (const key of ['showIf', 'constraint']) {
					if (present(q, key)) yield [['blocks', i, 'pages', j, 'items', k, key], false, q[key]!];
				}
			}
		}
	}
	const vars = list(d, 'variables');
	for (let i = 0; i < vars.length; i++) {
		const v = vars[i] as JsonObject;
		if (dget(v, 'kind') === 'computed') yield [['variables', i, 'expr'], true, v.expr!];
	}
	const quotas = list(d, 'quotas');
	for (let i = 0; i < quotas.length; i++) yield [['quotas', i, 'when'], true, (quotas[i] as JsonObject).when!];
	for (const [path, n] of flowNodes(list(d, 'flow'), ['flow'])) {
		if (dget(n, 'type') === 'branch') yield [[...path, 'if'], true, n.if!];
	}
}

/** Ids referenced by an expression in its JSON form. */
export function exprRefs(e: Json): Set<string> {
	const out = new Set<string>();
	const stack: Json[] = [e];
	while (stack.length) {
		const cur = stack.pop()!;
		if (isObj(cur)) {
			if (dget(cur, 'kind') === 'ref' && typeof dget(cur, 'id') === 'string') out.add(cur.id as string);
			for (const k of Object.keys(cur)) stack.push(cur[k]!);
		} else if (Array.isArray(cur)) stack.push(...cur);
	}
	return out;
}

export function pipeRefs(s: string): Set<string> {
	const out = new Set<string>();
	for (const m of s.matchAll(PIPE)) out.add(strip(m[1]!));
	return out;
}

/** A copy of `node` with refs, `${id}` pipes, `{pipe: id}` nodes and `choiceList` names remapped. */
export function remapIds(node: Json, ids: Map<string, string>): Json {
	if (isObj(node)) {
		if (dget(node, 'kind') === 'ref' && typeof node.id === 'string' && ids.has(node.id)) {
			return { ...node, id: ids.get(node.id)! };
		}
		const keys = Object.keys(node);
		if (keys.length === 1 && typeof dget(node, 'pipe') === 'string' && ids.has(node.pipe as string)) {
			return { pipe: ids.get(node.pipe as string)! };
		}
		const out: JsonObject = {};
		for (const k of keys) setKey(out, k, k === 'id' ? node[k]! : remapIds(node[k]!, ids));
		if (typeof dget(out, 'choiceList') === 'string' && ids.has(out.choiceList as string)) {
			out.choiceList = ids.get(out.choiceList as string)!;
		}
		return out;
	}
	if (Array.isArray(node)) return node.map((v) => remapIds(v, ids));
	if (typeof node === 'string') {
		return node.replace(PIPE, (_m, inner: string) => `\${${ids.get(strip(inner)) ?? inner}}`);
	}
	return node;
}

export function setKey(obj: JsonObject, key: string, value: Json): void {
	if (key === '__proto__') Object.defineProperty(obj, key, { value, writable: true, enumerable: true, configurable: true });
	else obj[key] = value;
}

// --- references to deleted objects ------------------------------------------------------------------

export class RefSite {
	constructor(
		readonly path: Path,
		readonly kind: string,
		readonly target: string
	) {}
	get pointer(): string {
		return toPointer(this.path);
	}
}

function sortedSet(s: Set<string>): string[] {
	return [...s].sort((a, b) => cmpStr(a, b));
}

function cmpStr(a: string, b: string): number {
	const x = Array.from(a);
	const y = Array.from(b);
	for (let i = 0; i < Math.min(x.length, y.length); i++) {
		const d = x[i]!.codePointAt(0)! - y[i]!.codePointAt(0)!;
		if (d !== 0) return d;
	}
	return x.length - y.length;
}

/** Every place referring to one of `ids`, outside the subtree at `exclude`. */
export function refSites(doc: Json, ids: Set<string>, exclude: Path | null = null): RefSite[] {
	const out = refSitesAll(doc, ids);
	if (exclude === null) return out;
	const n = exclude.length;
	return out.filter((s) => !(s.path.length >= n && exclude.every((p, i) => s.path[i] === p)));
}

function refSitesAll(doc: Json, ids: Set<string>): RefSite[] {
	const d = doc as JsonObject;
	const out: RefSite[] = [];
	for (const [path, required, e] of exprSites(doc)) {
		for (const t of sortedSet(new Set([...exprRefs(e)].filter((x) => ids.has(x))))) {
			out.push(new RefSite(path, required ? 'expr_required' : 'expr', t));
		}
	}
	for (const [path, text] of textSites(doc)) {
		for (const [sp, s] of stringsOf(text, path)) {
			for (const t of sortedSet(new Set([...pipeRefs(s)].filter((x) => ids.has(x))))) out.push(new RefSite(sp, 'pipe', t));
		}
		for (const [np, pid] of pipeNodesOf(text, path)) if (ids.has(pid)) out.push(new RefSite(np, 'pipe_node', pid));
	}
	const blocks = list(d, 'blocks');
	blocks.forEach((b, i) => {
		((b as JsonObject).pages as JsonObject[]).forEach((page, j) => {
			(page.items as JsonObject[]).forEach((q, k) => {
				const cl = dget(q, 'choiceList');
				if (typeof cl === 'string' && ids.has(cl)) {
					out.push(new RefSite(['blocks', i, 'pages', j, 'items', k, 'choiceList'], 'choice_list', cl));
				}
			});
		});
	});
	list(d, 'quotas').forEach((quota, i) => {
		const blk = dget((quota as JsonObject).onFull as JsonObject, 'block');
		if (typeof blk === 'string' && ids.has(blk)) out.push(new RefSite(['quotas', i, 'onFull', 'block'], 'on_full_block', blk));
	});
	for (const [path, n] of flowNodes(list(d, 'flow'), ['flow'])) {
		const t = dget(n, 'type');
		if (t === 'block' && ids.has(n.block as string)) out.push(new RefSite([...path, 'block'], 'flow_block', n.block as string));
		else if (t === 'quotaCheck' && ids.has(n.quota as string)) {
			out.push(new RefSite([...path, 'quota'], 'quota_check', n.quota as string));
		} else if (t === 'assign') {
			(n.variables as string[]).forEach((vid, k) => {
				if (ids.has(vid)) out.push(new RefSite([...path, 'variables', k], 'assign_var', vid));
			});
		}
	}
	return out;
}

/** Expressions comparing one of `questionIds` with the choice code `value`. */
export function choiceValueSites(doc: Json, questionIds: Set<string>, value: Json): RefSite[] {
	const out: RefSite[] = [];
	for (const [path, required, e] of exprSites(doc)) {
		if (mentionsCode(e, questionIds, value)) out.push(new RefSite(path, required ? 'expr_required' : 'expr', String(value)));
	}
	return out;
}

function literalIs(node: Json | undefined, value: Json): boolean {
	if (!isObj(node)) return false;
	const lit = dget(node, 'value');
	if (dget(node, 'kind') === 'int') return Number.isInteger(lit) && Number.isInteger(value) && lit === value;
	if (dget(node, 'kind') === 'text') return typeof lit === 'string' && typeof value === 'string' && lit === value;
	return false;
}

function isRefTo(node: Json | undefined, ids: Set<string>): boolean {
	return isObj(node) && dget(node, 'kind') === 'ref' && typeof dget(node, 'id') === 'string' && ids.has(node.id as string);
}

function mentionsCode(e: Json, ids: Set<string>, value: Json): boolean {
	const stack: Json[] = [e];
	while (stack.length) {
		const cur = stack.pop()!;
		if (isObj(cur)) {
			const k = dget(cur, 'kind');
			if (k === 'compare') {
				const left = dget(cur, 'left');
				const right = dget(cur, 'right');
				if ((isRefTo(left, ids) && literalIs(right, value)) || (isRefTo(right, ids) && literalIs(left, value))) return true;
			} else if (k === 'contains') {
				if (isRefTo(dget(cur, 'ref'), ids) && literalIs(dget(cur, 'value'), value)) return true;
			}
			for (const key of Object.keys(cur)) stack.push(cur[key]!);
		} else if (Array.isArray(cur)) stack.push(...cur);
	}
	return false;
}

/** Sort key of a path: ints before strings, then by value (Python tuple ordering). */
function cmpPath(a: Path, b: Path): number {
	for (let i = 0; i < Math.min(a.length, b.length); i++) {
		const x = a[i]!;
		const y = b[i]!;
		const tx = typeof x === 'number' ? 0 : 1;
		const ty = typeof y === 'number' ? 0 : 1;
		if (tx !== ty) return tx - ty;
		if (typeof x === 'number') {
			if (x !== y) return x - (y as number);
		} else {
			const c = cmpStr(x, y as string);
			if (c !== 0) return c;
		}
	}
	return a.length - b.length;
}

/** Apply the dangling-reference policy to `sites`. Returns true if cascade changed anything. */
export function handleRefs(
	ctx: Ctx,
	sites: RefSite[],
	o: { cascade: boolean; force: boolean; what: string; inline?: Map<string, Json[]> }
): boolean {
	ctx.checkDangling = !o.force;
	if (!sites.length || o.force) return false;
	if (!o.cascade) {
		const listed = sites
			.slice(0, 10)
			.map((s) => s.pointer)
			.join(', ');
		const more = sites.length > 10 ? ` (+${sites.length - 10} more)` : '';
		throw new OpError(
			'op.dangling_ref',
			`${o.what} is still referenced at ${listed}${more}; fix those first, or pass cascade: true to repair them`,
			sites[0]!.pointer,
			...sites.map((s) => diag('op.dangling_ref', `refers to '${s.target}'`, s.pointer))
		);
	}
	const blocked = sites.filter((s) => s.kind === 'expr_required');
	if (blocked.length) {
		throw new OpError(
			'op.cascade_blocked',
			`${o.what} is used by required expressions that cascade cannot clear: ` +
				blocked
					.slice(0, 10)
					.map((s) => s.pointer)
					.join(', '),
			blocked[0]!.pointer
		);
	}
	// Python's sort is stable; reverse=True keeps equal keys in their original order.
	const order = sites.map((s, i) => [s, i] as const);
	order.sort((x, y) => cmpPath(y[0].path, x[0].path) || x[1] - y[1]);
	for (const [s] of order) repair(ctx.doc, s, o.inline ?? new Map());
	ctx.touch();
	return true;
}

function repair(doc: Json, s: RefSite, inline: Map<string, Json[]>): void {
	const parent = get(doc, s.path.slice(0, -1));
	const key = s.path[s.path.length - 1]!;
	if (s.kind === 'expr' || s.kind === 'on_full_block') {
		delete (parent as JsonObject)[key as string];
	} else if (s.kind === 'pipe') {
		const text = parent[key] as string;
		parent[key] = text.replace(PIPE, (m: string, inner: string) => (strip(inner) === s.target ? '' : m));
	} else if (s.kind === 'pipe_node') {
		(parent as Json[]).splice(key as number, 1);
	} else if (s.kind === 'choice_list') {
		delete (parent as JsonObject).choiceList;
		(parent as JsonObject).choices = deepCopy(inline.get(s.target) ?? []);
	} else if (s.kind === 'flow_block' || s.kind === 'quota_check') {
		removeNode(doc, s.path.slice(0, -1));
	} else if (s.kind === 'assign_var') {
		(parent as Json[]).splice(key as number, 1);
		if ((parent as Json[]).length === 0) removeNode(doc, s.path.slice(0, -2));
	}
}

/** Delete the object at `loc` (whose subtree holds `ids`) under the dangling-reference policy. */
export function deleteWithRefs(
	ctx: Ctx,
	loc: Loc,
	ids: Set<string>,
	o: { cascade: boolean; force: boolean; what: string; inline?: Map<string, Json[]> }
): [Json, boolean] {
	const sites = refSites(ctx.doc, ids, loc.path);
	const cascaded = handleRefs(ctx, sites, o);
	const obj = (get(ctx.doc, loc.container) as Json[]).splice(loc.index, 1)[0]!;
	ctx.touch();
	return [obj, cascaded];
}

/** Ids of a block, page or question and everything inside it. */
export function subtreeIds(obj: Json): Set<string> {
	const out = new Set<string>();
	const stack: Json[] = [obj];
	while (stack.length) {
		const cur = stack.pop()!;
		if (isObj(cur)) {
			if (typeof dget(cur, 'id') === 'string' && dget(cur, 'kind') !== 'ref') {
				out.add(cur.id as string);
				if (dget(cur, 'type') === 'matrix') {
					const rows = dget(cur, 'rows');
					for (const r of Array.isArray(rows) ? rows : []) out.add(`${cur.id as string}_${(r as JsonObject).id as string}`);
				}
			}
			for (const k of Object.keys(cur)) if (k === 'pages' || k === 'items') stack.push(cur[k]!);
		} else if (Array.isArray(cur)) stack.push(...cur);
	}
	return out;
}

function removeNode(doc: Json, nodePath: Path): void {
	const lst = get(doc, nodePath.slice(0, -1)) as Json[];
	lst.splice(nodePath[nodePath.length - 1] as number, 1);
}

/** Remove translations in `langs` from every Text. Returns how many were removed. */
export function stripLanguages(doc: Json, langs: Set<string>): number {
	let n = 0;
	for (const [path, text] of [...textSites(doc)]) {
		if (isObj(text) && !isRich(text)) {
			for (const lang of Object.keys(text).filter((k) => langs.has(k))) {
				delete (get(doc, path) as JsonObject)[lang];
				n++;
			}
		}
	}
	return n;
}

/** Pointers to translations in `langs`. */
export function translationsIn(doc: Json, langs: Set<string>): string[] {
	const out: string[] = [];
	for (const [path, text] of textSites(doc)) {
		if (isObj(text) && !isRich(text)) for (const k of Object.keys(text)) if (langs.has(k)) out.push(toPointer([...path, k]));
	}
	return out;
}
