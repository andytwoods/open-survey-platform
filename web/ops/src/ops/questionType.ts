/**
 * `change_question_type`: turn a question into another type, in place (port of
 * `osp_ops.question_type_ops`; see that module's docstring for the conversion rules).
 * Rejected (`op.type_conflict`) when the validator reports new type, reference or
 * choice-code problems elsewhere, unless `force`.
 */

import { QUESTION, exprSites, get, locate, stringsOf, textSites } from '../doc.ts';
import { QUESTION_CLASSES } from '../models.ts';
import { toPointer } from '../patch.ts';
import { deepCopy, get as dget, has, isInt, pyLen, sorted, strip, type Json, type JsonObject } from '../py.ts';
import { OpError, diag, op, type Diagnostic, type Invocation, type OpsEnv } from '../registry.ts';
import { DEFAULT_CHOICES, DEFAULT_ROWS } from './question.ts';
import { JsonDict, QuestionType, flag, opt, params, req, str } from './params.ts';

const CHOICE_TYPES = new Set(['single', 'multi']);
const WITH_COLUMNS = new Set(['single', 'multi', 'matrix']);
const NUMBER_TYPES = new Set(['integer', 'decimal', 'slider']);
const IDENTITY_KEYS = ['help', 'showIf', 'name', 'required'];
const BREAKING_CODES = new Set(['expr.type', 'ref.no_value', 'ref.unknown', 'ref.unknown_choice_code', 'pipe.invalid']);
const SLIDER_DEFAULT: [number, number] = [0, 100];

// --- exact decimals (enough of Python's `Decimal` for bounds) ------------------------------------

interface Dec {
	n: bigint; // value = n / 10^scale
	scale: number;
}

const DEC_RE = /^([+-])?(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/;

function parseDec(v: Json | undefined): Dec | null {
	if (typeof v === 'boolean') return null;
	if (isInt(v)) return { n: BigInt(v), scale: 0 };
	if (typeof v !== 'string') return null;
	const m = DEC_RE.exec(strip(v).replaceAll('_', ''));
	if (!m) return null;
	const intPart = m[2] ?? '';
	const frac = m[3] ?? m[4] ?? '';
	const exp = m[5] ? Number(m[5]) : 0;
	let n = BigInt((intPart + frac).replace(/^0+(?=\d)/, '') || '0');
	if (m[1] === '-') n = -n;
	let scale = frac.length - exp;
	if (scale < 0) {
		n *= 10n ** BigInt(-scale);
		scale = 0;
	}
	return { n, scale };
}

function align(a: Dec, b: Dec): [bigint, bigint, number] {
	const s = Math.max(a.scale, b.scale);
	return [a.n * 10n ** BigInt(s - a.scale), b.n * 10n ** BigInt(s - b.scale), s];
}

function isWhole(d: Dec): boolean {
	return d.n % 10n ** BigInt(d.scale) === 0n;
}

function asInt(v: Json | undefined): number | null {
	if (isInt(v)) return v;
	const d = parseDec(v);
	if (d === null || !isWhole(d)) return null;
	const i = d.n / 10n ** BigInt(d.scale);
	const max = 2n ** 53n - 1n;
	if (i > max || -i > max) return null;
	return Number(i);
}

// --- conversion --------------------------------------------------------------------------------

export function convert(old: JsonObject, newType: string): JsonObject {
	const oldType = dget(old, 'type') as string;
	const fields = new Set(QUESTION_CLASSES[newType]!.fields);
	const q: JsonObject = { id: old.id!, type: newType, label: deepCopy(old.label!) };
	for (const key of IDENTITY_KEYS) if (has(old, key) && fields.has(key)) q[key] = deepCopy(old[key]!);
	if (NUMBER_TYPES.has(oldType) && NUMBER_TYPES.has(newType)) {
		for (const key of ['constraint', 'constraintMessage']) if (has(old, key)) q[key] = deepCopy(old[key]!);
	}
	if (WITH_COLUMNS.has(newType)) {
		if (WITH_COLUMNS.has(oldType)) {
			for (const key of ['choiceList', 'choices']) if (has(old, key)) q[key] = deepCopy(old[key]!);
			if (CHOICE_TYPES.has(newType) && CHOICE_TYPES.has(oldType) && has(old, 'choiceOrder')) q.choiceOrder = old.choiceOrder!;
		}
		if (!has(q, 'choiceList') && !has(q, 'choices')) q.choices = deepCopy(DEFAULT_CHOICES);
	}
	if (newType === 'matrix') q.rows = deepCopy(oldType === 'matrix' ? (old.rows as Json) : DEFAULT_ROWS);

	if (newType === 'integer' && NUMBER_TYPES.has(oldType)) {
		for (const key of ['min', 'max']) {
			const v = asInt(dget(old, key));
			if (v !== null) q[key] = v;
		}
	} else if (newType === 'decimal' && NUMBER_TYPES.has(oldType)) {
		for (const key of ['min', 'max']) if (has(old, key) && parseDec(old[key]) !== null) q[key] = old[key]!;
	} else if (newType === 'slider') {
		Object.assign(q, sliderTrack(old));
	}
	return q;
}

function sliderTrack(old: JsonObject): JsonObject {
	const t = dget(old, 'type');
	if (t !== 'integer' && t !== 'decimal') return {};
	const valueType = t === 'decimal' ? 'decimal' : 'integer';
	const lo = parseDec(dget(old, 'min'));
	const hi = parseDec(dget(old, 'max'));
	const track: JsonObject = { valueType };
	let usable = false;
	if (lo !== null && hi !== null) {
		const [a, b, s] = align(lo, hi);
		usable =
			a < b &&
			isWhole({ n: b - a, scale: s }) &&
			(valueType === 'decimal' || (isWhole(lo) && isWhole(hi)));
	}
	if (usable) {
		track.min = old.min!;
		track.max = old.max!;
	} else {
		track.min = SLIDER_DEFAULT[0];
		track.max = SLIDER_DEFAULT[1];
	}
	return track;
}

function breaking(before: Diagnostic[], after: Diagnostic[]): Diagnostic[] {
	const key = (d: Diagnostic): string => JSON.stringify([d.code, d.pointer, d.message]);
	const seen = new Map<string, number>();
	for (const d of before) if (BREAKING_CODES.has(d.code)) seen.set(key(d), (seen.get(key(d)) ?? 0) + 1);
	const out: Diagnostic[] = [];
	for (const d of after) {
		if (!BREAKING_CODES.has(d.code)) continue;
		const n = seen.get(key(d)) ?? 0;
		if (n > 0) seen.set(key(d), n - 1);
		else out.push(d);
	}
	return out;
}

function siteOf(pointer: string, sites: string[]): string {
	let best: string | null = null;
	for (const s of sites) {
		if (pointer === s || pointer.startsWith(s + '/')) if (best === null || pyLen(s) > pyLen(best)) best = s;
	}
	return best ?? pointer;
}

function sitesOf(doc: Json): string[] {
	const out: string[] = [];
	for (const [path] of exprSites(doc)) out.push(toPointer(path));
	for (const [path, text] of textSites(doc)) for (const [sp] of stringsOf(text, path)) out.push(toPointer(sp));
	return out;
}

export function validateWith(env: OpsEnv, doc: Json): Diagnostic[] {
	const v = env.validator;
	return v.validate ? v.validate(doc) : v.parse(doc).diagnostics;
}

const ChangeQuestionType = params('ChangeQuestionType', [
	req('id', str),
	req('type', QuestionType),
	flag('force'),
	opt('question', JsonDict)
]);

op('change_question_type', ChangeQuestionType, { label: 'Change question type', area: 'questions' }, (ctx, p): Invocation => {
	const loc = locate(ctx, p.id, QUESTION);
	const old = get(ctx.doc, loc.path) as JsonObject;
	let nu: JsonObject;
	if (p.question !== null) {
		nu = deepCopy(p.question as JsonObject);
		if (dget(nu, 'id') !== p.id || dget(nu, 'type') !== p.type) {
			throw new OpError('op.params', 'question must have the same id and the given type', '/question');
		}
	} else if (dget(old, 'type') === p.type) {
		throw new OpError('op.not_allowed', `'${p.id}' is already a ${p.type} question`, loc.pointer);
	} else nu = convert(old, p.type);

	const previous = deepCopy(old);
	(get(ctx.doc, loc.container) as Json[])[loc.index] = nu;
	ctx.touch();
	ctx.checkDangling = !p.force;

	if (!p.force) {
		const broken = breaking(validateWith(ctx.env, ctx.before), validateWith(ctx.env, ctx.doc));
		if (broken.length) {
			const sites = sitesOf(ctx.doc);
			const bySite = new Map<string, string[]>();
			for (const d of broken) {
				const s = siteOf(d.pointer, sites);
				if (!bySite.has(s)) bySite.set(s, []);
				bySite.get(s)!.push(d.message);
			}
			const places = sorted(bySite.keys());
			const n = places.length;
			throw new OpError(
				'op.type_conflict',
				`changing '${p.id}' to ${p.type} would break ${n} ${n === 1 ? 'reference' : 'references'} to its answer ` +
					`(conditions or piping): ${places.slice(0, 10).join(', ')}${n > 10 ? ` (+${n - 10} more)` : ''}; ` +
					'fix them first, or pass force: true',
				loc.pointer,
				...places.map((s) => diag('op.type_conflict', bySite.get(s)!.join('; '), s))
			);
		}
	}
	return { op: 'change_question_type', params: { id: p.id, type: previous.type!, question: previous, force: true } };
});
