/**
 * Variables, metadata, custom properties and page/block duplication (ports of
 * `variable_ops`, `metadata_ops`, `custom_property_ops`, `duplicate_ops`).
 */

import {
	BLOCK,
	PAGE,
	QUESTION,
	VARIABLE,
	claimId,
	deleteWithRefs,
	freshId,
	get,
	insertAt,
	locate,
	remapIds,
	setKey,
	stripLanguages,
	translationsIn
} from '../doc.ts';
import { MAX_CUSTOM_PROPERTIES } from '../models.ts';
import { toPointer } from '../patch.ts';
import { S } from '../pyd.ts';
import { deepCopy, get as dget, has, isObj, slice, sorted, strip, type Json, type JsonObject } from '../py.ts';
import { REVERSE_PATCH, OpError, op, type Ctx, type Invocation } from '../registry.ts';
import { Index, JsonDict, def, flag, opt, params, req, str } from './params.ts';

// --- variables ------------------------------------------------------------------------------------

const AddVariable = params('AddVariable', [req('variable', JsonDict), Index]);

op('add_variable', AddVariable, { label: 'Add variable', area: 'variables' }, (ctx, p): Invocation => {
	const v0 = deepCopy(p.variable as JsonObject);
	const vid = claimId(ctx, typeof dget(v0, 'id') === 'string' ? (v0.id as string) : null, 'var');
	const v: JsonObject = { id: vid };
	for (const k of Object.keys(v0)) if (k !== 'id') setKey(v, k, v0[k]!);
	if (!has(ctx.d, 'variables')) ctx.d.variables = [];
	insertAt(ctx.d.variables as Json[], p.index, v);
	ctx.touch();
	return { op: 'delete_variable', params: { id: vid, force: true } };
});

const DeleteVariable = params('DeleteVariable', [req('id', str), flag('cascade'), flag('force')]);

op('delete_variable', DeleteVariable, { label: 'Delete variable', area: 'variables' }, (ctx, p): Invocation => {
	const loc = locate(ctx, p.id, VARIABLE);
	const [v, cascaded] = deleteWithRefs(ctx, loc, new Set([p.id]), { cascade: p.cascade, force: p.force, what: `variable '${p.id}'` });
	if (cascaded) return REVERSE_PATCH;
	return { op: 'add_variable', params: { variable: v, index: loc.index } };
});

// --- metadata -------------------------------------------------------------------------------------

const SetTitle = params('SetTitle', [req('title', S.union(['str', S.str()], ['dict[str,str]', S.dict(S.str(), S.str())]))]);

op('set_title', SetTitle, { label: 'Set survey title', area: 'metadata' }, (ctx, p): Invocation => {
	const md = ctx.d.metadata as JsonObject;
	const old = deepCopy(md.title!);
	md.title = deepCopy(p.title);
	return { op: 'set_title', params: { title: old } };
});

const SetLanguages = params('SetLanguages', [
	req('languages', S.list(S.str(), { min: 1, max: 200 })),
	opt('default_language', str),
	flag('cascade'),
	flag('force')
]);

op('set_languages', SetLanguages, { label: 'Set languages', area: 'metadata' }, (ctx, p): Invocation => {
	const md = ctx.d.metadata as JsonObject;
	const oldLangs = [...(md.languages as string[])];
	const hadDefault = has(md, 'defaultLanguage');
	const oldDefault = hadDefault ? md.defaultLanguage! : null;
	const keep = new Set(p.languages as string[]);
	const dropped = new Set(oldLangs.filter((l) => !keep.has(l)));
	let cascaded = false;
	if (dropped.size && !p.force) {
		const found = translationsIn(ctx.doc, dropped);
		if (found.length && !p.cascade) {
			throw new OpError(
				'op.dangling_ref',
				`${found.length} translation(s) in ${sorted(dropped).join(', ')} would be orphaned ` +
					`(first at ${found[0]}); pass cascade: true to delete them`,
				found[0]
			);
		}
		if (found.length) {
			stripLanguages(ctx.doc, dropped);
			cascaded = true;
		}
	}
	md.languages = [...(p.languages as string[])];
	if (p.default_language === null) delete md.defaultLanguage;
	else md.defaultLanguage = p.default_language;
	if (cascaded || (hadDefault && oldDefault === null)) return REVERSE_PATCH;
	const out: JsonObject = { languages: oldLangs, force: true };
	if (oldDefault !== null) out.default_language = oldDefault;
	return { op: 'set_languages', params: out };
});

// --- custom properties ------------------------------------------------------------------------------

const SetCustomProperty = params('SetCustomProperty', [
	req('target', str),
	req('key', str),
	def(
		'value',
		S.nullable(S.union(['str', S.str()], ['int', S.int()], ['float', S.float()], ['bool', S.bool])),
		null
	),
	flag('unset')
]);

op('set_custom_property', SetCustomProperty, { label: 'Set custom property', area: 'questions' }, (ctx, p): Invocation => {
	const loc = locate(ctx, p.target, QUESTION);
	const q = get(ctx.doc, loc.path) as JsonObject;
	const custom0 = dget(q, 'custom');
	const custom: JsonObject = isObj(custom0) ? { ...custom0 } : {};
	const had = has(custom, p.key);
	const old = had ? deepCopy(custom[p.key]!) : null;
	if (p.unset) delete custom[p.key];
	else {
		if (p.value === null) {
			throw new OpError(
				'op.params',
				'a custom property needs a value (text, number or true/false), or `unset`',
				loc.pointer + toPointer(['custom', slice(p.key, 0, 64)])
			);
		}
		if (!had && Object.keys(custom).length >= MAX_CUSTOM_PROPERTIES) {
			throw new OpError(
				'op.not_allowed',
				`a question may carry at most ${MAX_CUSTOM_PROPERTIES} custom properties`,
				loc.pointer + toPointer(['custom'])
			);
		}
		setKey(custom, p.key, p.value);
	}
	if (Object.keys(custom).length) q.custom = custom;
	else delete q.custom;
	ctx.touch();
	if (!had) return { op: 'set_custom_property', params: { target: p.target, key: p.key, unset: true } };
	return { op: 'set_custom_property', params: { target: p.target, key: p.key, value: old } };
});

// --- duplicate page / block -----------------------------------------------------------------------

const STEM = 52;

const DuplicateById = params('DuplicateById', [req('id', str), opt('new_id', str)]);

function newId(ctx: Ctx, old: string, assigned: Set<string>): string {
	const id = freshId(ctx.doc, `${slice(old, 0, STEM)}_copy`, { exactFirst: true, also: assigned });
	assigned.add(id);
	return id;
}

function copyPage(ctx: Ctx, page: JsonObject, pid: string, ids: Map<string, string>): JsonObject {
	const out: JsonObject = {};
	for (const k of Object.keys(page)) if (k !== 'items') setKey(out, k, deepCopy(page[k]!));
	out.id = pid;
	ids.set(page.id as string, pid);
	const assigned = new Set(ids.values());
	const items: Json[] = [];
	for (const q of page.items as JsonObject[]) {
		const nu = newId(ctx, q.id as string, assigned);
		ids.set(q.id as string, nu);
		if (dget(q, 'type') === 'matrix') {
			const rows = dget(q, 'rows');
			for (const r of Array.isArray(rows) ? rows : []) {
				const rid = (r as JsonObject).id as string;
				ids.set(`${q.id as string}_${rid}`, `${nu}_${rid}`);
			}
		}
		const item: JsonObject = { id: nu };
		for (const k of Object.keys(q)) if (k !== 'id' && k !== 'name') setKey(item, k, deepCopy(q[k]!));
		items.push(item);
	}
	out.items = items;
	return out;
}

op('duplicate_page', DuplicateById, { label: 'Duplicate page', area: 'pages' }, (ctx, p): Invocation => {
	const loc = locate(ctx, p.id, PAGE);
	const pid = p.new_id !== null ? claimId(ctx, p.new_id, 'page') : newId(ctx, p.id, new Set());
	const ids = new Map<string, string>();
	const page = remapIds(copyPage(ctx, get(ctx.doc, loc.path), pid, ids), ids);
	(get(ctx.doc, loc.container) as Json[]).splice(loc.index + 1, 0, page);
	ctx.touch();
	return { op: 'delete_page', params: { id: pid, force: true } };
});

op('duplicate_block', DuplicateById, { label: 'Duplicate block', area: 'blocks' }, (ctx, p): Invocation => {
	const loc = locate(ctx, p.id, BLOCK);
	const orig = get(ctx.doc, loc.path) as JsonObject;
	const bid = p.new_id !== null ? claimId(ctx, p.new_id, 'block') : newId(ctx, p.id, new Set());
	const ids = new Map<string, string>([[orig.id as string, bid]]);
	const pages: Json[] = [];
	for (const page of orig.pages as JsonObject[]) {
		const pid = newId(ctx, page.id as string, new Set(ids.values()));
		pages.push(copyPage(ctx, page, pid, ids));
	}
	const block: JsonObject = {};
	for (const k of Object.keys(orig)) if (k !== 'pages') setKey(block, k, deepCopy(orig[k]!));
	block.id = bid;
	if (typeof dget(block, 'title') === 'string' && strip(block.title as string)) block.title = `${block.title as string} (copy)`;
	block.pages = pages;
	(get(ctx.doc, loc.container) as Json[]).splice(loc.index + 1, 0, remapIds(block, ids));
	ctx.touch();
	return { op: 'delete_block', params: { id: bid, force: true } };
});
