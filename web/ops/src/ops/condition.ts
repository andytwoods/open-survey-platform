/** `set_condition`: set, replace or clear a condition from an AST or from text (port of `osp_ops.condition_ops`). */

import { NODE, QUESTION, QUOTA, VARIABLE, get, locate, setKey } from '../doc.ts';
import { ExprAdapter, QUESTION_CLASSES } from '../models.ts';
import { S, dump, validate } from '../pyd.ts';
import { deepCopy, get as dget, has, pyLen, slice, strip, type Json, type JsonObject } from '../py.ts';
import { OpError, diag, op, type Ctx, type Invocation } from '../registry.ts';
import { JsonDict, JSON_DICT_TAG, opt, params, req, str } from './params.ts';

const FIELDS: Record<string, string[]> = {
	question: ['showIf', 'constraint'],
	branch: ['if'],
	quota: ['when'],
	computed: ['expr']
};
const REQUIRED = new Set(['if', 'when', 'expr']);
const MAX_TEXT = 20_000;

/** Condition text or AST -> canonical AST JSON. Throws OpError with diagnostics. */
export function toAst(ctx: Ctx, condition: Json): Json {
	let expr: Json;
	if (typeof condition === 'string') {
		if (pyLen(condition) > MAX_TEXT) throw new OpError('op.params', `condition text is over ${MAX_TEXT} characters`);
		const parse = ctx.env.validator.parseExpression;
		if (!parse) {
			throw new OpError('op.expr_syntax', 'condition text needs an expression parser here; send the AST instead', '/condition');
		}
		const res = parse(condition);
		if (res.expr === null) {
			const errs = 'diagnostics' in res ? res.diagnostics : [];
			const ds = errs.map((d) => diag('op.expr_syntax', `${d.message} [${d.code}] at ${d.start}-${d.end}`, '/condition'));
			if (!ds.length) ds.push(diag('op.expr_syntax', 'condition does not parse', '/condition'));
			throw new OpError(ds[0]!.code, ds[0]!.message, ds[0]!.pointer, ...ds.slice(1));
		}
		expr = res.expr;
	} else expr = condition;
	const r = validate(ExprAdapter, expr);
	if (!r.ok) throw new OpError('op.params', `not an expression AST: ${slice(r.errs[0]!.msg, 0, 300)}`, '/condition');
	return dump(r.v);
}

const SetCondition = params('SetCondition', [
	req('target', str),
	req('condition', S.nullable(S.union(['str', S.str()], [JSON_DICT_TAG, JsonDict]))),
	opt('field', S.literal('showIf', 'constraint', 'if', 'when', 'expr'))
]);

op('set_condition', SetCondition, { label: 'Set condition', area: 'conditions' }, (ctx, p): Invocation => {
	const loc = locate(ctx, p.target, QUESTION, NODE, QUOTA, VARIABLE);
	const obj = get(ctx.doc, loc.path) as JsonObject;
	let kind: string;
	if (loc.kind === QUESTION) kind = 'question';
	else if (loc.kind === QUOTA) kind = 'quota';
	else kind = pyStrOf(loc.kind === NODE ? dget(obj, 'type') : dget(obj, 'kind'));
	let fields: string[] | undefined = has(FIELDS, kind) ? FIELDS[kind] : undefined;
	if (fields !== undefined && loc.kind === QUESTION) {
		kind = pyStrOf(dget(obj, 'type'));
		const cls = has(QUESTION_CLASSES, kind) ? QUESTION_CLASSES[kind] : undefined;
		fields = fields.filter((f) => cls !== undefined && cls.fields.includes(f));
	}
	if (!fields || !fields.length) throw new OpError('op.not_applicable', `'${p.target}' (${kind}) has no condition`, loc.pointer);
	const field: string = p.field ?? fields[0]!;
	if (!fields.includes(field)) {
		throw new OpError('op.not_applicable', `'${p.target}' (${kind}) has no '${field}'; it has ${fields.join(', ')}`, loc.pointer);
	}
	let cond: Json = p.condition;
	if (typeof cond === 'string' && !strip(cond)) cond = null;
	const absent = !has(obj, field);
	const old = absent ? null : deepCopy(obj[field]!);
	if (cond === null) {
		if (REQUIRED.has(field)) throw new OpError('op.not_allowed', `'${field}' is required and cannot be cleared`);
		delete obj[field];
	} else setKey(obj, field, toAst(ctx, cond));
	const out: JsonObject = { target: p.target, property: field };
	if (absent) out.unset = true;
	else out.value = old;
	return { op: 'set_property', params: out };
});

function pyStrOf(v: Json | undefined): string {
	if (v === undefined || v === null) return 'None';
	return typeof v === 'string' ? v : String(v);
}
