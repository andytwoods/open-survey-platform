/** `set_property`: set or unset one field of any addressable object (port of `osp_ops.property_ops`). */

import { NODE, QUESTION, VARIABLE, get, locate, setKey } from '../doc.ts';
import { FAMILIES, FIXED_CLASSES, METADATA, NODE_CLASSES, QUESTION_CLASSES, SETTINGS, VARIABLE_CLASSES, type ModelInfo } from '../models.ts';
import { PyException, toPointer, type PathPart } from '../patch.ts';
import { S } from '../pyd.ts';
import { deepCopy, get as dget, has, reprStr, slice, type JsonObject } from '../py.ts';
import { REVERSE_PATCH, OpError, op, type Ctx, type Invocation } from '../registry.ts';
import { normaliseText } from '../spec.ts';
import { def, flag, params, req, str } from './params.ts';

const SINGLETONS: Record<string, [string[], ModelInfo]> = {
	'/metadata': [['metadata'], METADATA],
	'/settings': [['settings'], SETTINGS]
};
const FORBIDDEN = new Set(['id', 'type', 'kind', 'items', 'pages', 'then', 'else', 'children', 'custom']);

function reserved(cls: ModelInfo, prop: string): boolean {
	if (FORBIDDEN.has(prop)) return true;
	if (prop === 'source') return cls !== VARIABLE_CLASSES.embedded;
	return prop === 'instruments' && cls === METADATA;
}

function familyFields(cls: ModelInfo): Set<string> {
	for (const family of FAMILIES) {
		if (Object.values(family).includes(cls)) return new Set(Object.values(family).flatMap((c) => c.fields));
	}
	return new Set(cls.fields);
}

function resolve(ctx: Ctx, target: string): [PathPart[], ModelInfo] {
	if (has(SINGLETONS, target)) {
		const [path, cls] = SINGLETONS[target]!;
		if (path[0] === 'settings' && !has(ctx.d, 'settings')) ctx.d.settings = {};
		return [path, cls];
	}
	const loc = locate(ctx, target);
	const obj = get(ctx.doc, loc.path) as JsonObject;
	let cls: ModelInfo | undefined;
	const pick = (table: Record<string, ModelInfo>, key: unknown): ModelInfo | undefined =>
		typeof key === 'string' && has(table, key) ? table[key] : undefined;
	if (loc.kind === QUESTION) cls = pick(QUESTION_CLASSES, dget(obj, 'type'));
	else if (loc.kind === NODE) cls = pick(NODE_CLASSES, dget(obj, 'type'));
	else if (loc.kind === VARIABLE) cls = pick(VARIABLE_CLASSES, dget(obj, 'kind'));
	else cls = FIXED_CLASSES[loc.kind];
	if (cls === undefined) throw new PyException('AssertionError'); // e.g. an externalTask node
	return [loc.path, cls];
}

const SetProperty = params('SetProperty', [req('target', str), req('property', str), def('value', S.json, null), flag('unset')]);

op('set_property', SetProperty, { label: 'Set property', area: 'questions' }, (ctx, p): Invocation => {
	const hadSettings = has(ctx.d, 'settings');
	const [path, cls] = resolve(ctx, p.target);
	const allowed = cls.fields;
	if (reserved(cls, p.property) || !allowed.includes(p.property)) {
		const editable = allowed.filter((f) => !reserved(cls, f)).join(', ');
		const unknown = reserved(cls, p.property) || !familyFields(cls).has(p.property);
		throw new OpError(
			unknown ? 'op.not_allowed' : 'op.not_applicable',
			`${reprStr(slice(p.property, 0, 40))} is not an editable property of ${cls.name} (editable: ${editable})`,
			toPointer([...path, slice(p.property, 0, 64)])
		);
	}
	const obj = get(ctx.doc, path) as JsonObject;
	const absent = !has(obj, p.property);
	const old = absent ? null : deepCopy(obj[p.property]!);
	if (p.unset) delete obj[p.property];
	else setKey(obj, p.property, normaliseText(deepCopy(p.value)));
	if (!hadSettings && p.target === '/settings') {
		if (Object.keys(obj).length === 0) delete ctx.d.settings;
		return REVERSE_PATCH;
	}
	ctx.touch();
	if (absent) return { op: 'set_property', params: { target: p.target, property: p.property, unset: true } };
	return { op: 'set_property', params: { target: p.target, property: p.property, value: old } };
});
