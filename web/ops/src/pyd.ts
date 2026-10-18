/**
 * A small validator with pydantic v2's behaviour for the shapes `osp-ops` validates itself:
 * op params, `Ending`, `RedirectTemplate`, `Source`, the hook manifest, the theme and the
 * expression AST. Same error types, locations (union member tags included) and messages
 * as `pydantic-core` for JSON input, so diagnostics match the Python ops exactly; and the
 * same dumps (`model_dump` with `exclude_unset` / `exclude_none`, fields in model order).
 *
 * Only what those models use is here: strict str/int/float/bool, a lax decimal, None,
 * literals, lists, dicts, `JsonValue`, smart unions (first member that validates),
 * discriminated unions and models with `extra="forbid"`, aliases and validators.
 */

import { deepCopy, has, isInt, isObj, pyLen, repr, reprFloat, setProp, str as pyStr, strip, type Json, type JsonObject } from './py.ts';

export type Loc = (string | number)[];

export interface PydError {
	type: string;
	loc: Loc;
	msg: string;
}

export class ModelVal {
	constructor(
		readonly schema: ModelSchema,
		readonly values: Map<string, Val>,
		readonly fieldsSet: Set<string>
	) {}

	get(name: string): Val {
		return this.values.get(name) ?? null;
	}
}

export type Val = Json | ModelVal | Val[] | { [k: string]: Val };

type Res = { ok: true; v: Val } | { ok: false; errs: PydError[] };

export interface Field {
	name: string;
	alias?: string;
	schema: Schema;
	/** Absent: required. A function: `default_factory`. */
	default?: Json | (() => Val);
	/** A field validator (`mode="after"`): an error message (`Value error, ...`) or null. */
	after?: (v: Val) => string | null;
}

export interface ModelSchema {
	t: 'model';
	name: string;
	fields: Field[];
	/** A model validator (`mode="after"`): an error message or null. */
	after?: (v: ModelVal) => string | null;
}

export type Schema =
	| { t: 'str'; min?: number; max?: number; pattern?: string; re?: RegExp; after?: (v: string) => string | null }
	| { t: 'int'; ge?: number; le?: number }
	| { t: 'float'; ge?: number; le?: number; finite?: boolean }
	| { t: 'bool' }
	| { t: 'none' }
	| { t: 'decimal' }
	| { t: 'json' }
	| { t: 'nullable'; inner: Schema }
	| { t: 'literal'; values: Json[] }
	| { t: 'list'; item: Schema; min?: number; max?: number; tuple?: boolean }
	| { t: 'dict'; key: Schema; value: Schema; max?: number }
	| { t: 'union'; members: [string, Schema][] }
	| { t: 'tagged'; disc: string; choices: [string, Schema][] }
	| ModelSchema
	| { t: 'lazy'; get: () => Schema };

// --- constructors ---------------------------------------------------------------------------

/** A pydantic pattern (Rust `regex`): `\d` is any Unicode decimal digit. */
function compile(pattern: string): RegExp {
	return new RegExp(pattern.replaceAll('\\d', '\\p{Nd}'), 'u');
}

export const S = {
	str(o: { min?: number; max?: number; pattern?: string; after?: (v: string) => string | null } = {}): Schema {
		return { t: 'str', ...o, ...(o.pattern !== undefined ? { re: compile(o.pattern) } : {}) };
	},
	int(o: { ge?: number; le?: number } = {}): Schema {
		return { t: 'int', ...o };
	},
	float(o: { ge?: number; le?: number; finite?: boolean } = {}): Schema {
		return { t: 'float', ...o };
	},
	bool: { t: 'bool' } as Schema,
	none: { t: 'none' } as Schema,
	decimal: { t: 'decimal' } as Schema,
	json: { t: 'json' } as Schema,
	nullable(inner: Schema): Schema {
		return { t: 'nullable', inner };
	},
	literal(...values: Json[]): Schema {
		return { t: 'literal', values };
	},
	list(item: Schema, o: { min?: number; max?: number; tuple?: boolean } = {}): Schema {
		return { t: 'list', item, ...o };
	},
	dict(key: Schema, value: Schema, o: { max?: number } = {}): Schema {
		return { t: 'dict', key, value, ...o };
	},
	union(...members: [string, Schema][]): Schema {
		return { t: 'union', members };
	},
	tagged(disc: string, choices: [string, Schema][]): Schema {
		return { t: 'tagged', disc, choices };
	},
	model(name: string, fields: Field[], after?: (v: ModelVal) => string | null): ModelSchema {
		return { t: 'model', name, fields, ...(after ? { after } : {}) };
	},
	lazy(get: () => Schema): Schema {
		return { t: 'lazy', get };
	}
};

// --- validation -----------------------------------------------------------------------------

function err(type: string, msg: string, loc: Loc = []): Res {
	return { ok: false, errs: [{ type, loc, msg }] };
}

function prefix(errs: PydError[], ...parts: Loc): PydError[] {
	return errs.map((e) => ({ ...e, loc: [...parts, ...e.loc] }));
}

function plural(n: number, word: string): string {
	return `${n} ${word}${n === 1 ? '' : 's'}`;
}

function num(n: number): string {
	return Number.isInteger(n) ? String(n) : reprFloat(n);
}

function literalExpected(values: Json[]): string {
	const r = values.map((v) => repr(v));
	if (r.length === 1) return r[0]!;
	return `${r.slice(0, -1).join(', ')} or ${r[r.length - 1]}`;
}

export function validate(schema: Schema, input: Json): Res {
	switch (schema.t) {
		case 'lazy':
			return validate(schema.get(), input);
		case 'json':
			return { ok: true, v: copyJson(input) };
		case 'none':
			return input === null ? { ok: true, v: null } : err('none_required', 'Input should be None');
		case 'nullable':
			return input === null ? { ok: true, v: null } : validate(schema.inner, input);
		case 'bool':
			return typeof input === 'boolean' ? { ok: true, v: input } : err('bool_type', 'Input should be a valid boolean');
		case 'int':
			if (!isInt(input)) return err('int_type', 'Input should be a valid integer');
			return bounds(schema, input);
		case 'float':
			if (typeof input !== 'number') return err('float_type', 'Input should be a valid number');
			if (schema.finite && !Number.isFinite(input)) return err('finite_number', 'Input should be a finite number');
			return bounds(schema, input, reprFloat);
		case 'str':
			return validateStr(schema, input);
		case 'decimal':
			return validateDecimal(input);
		case 'literal': {
			for (const v of schema.values) if (v === input) return { ok: true, v };
			return err('literal_error', `Input should be ${literalExpected(schema.values)}`);
		}
		case 'list':
			return validateList(schema, input);
		case 'dict':
			return validateDict(schema, input);
		case 'union': {
			const errs: PydError[] = [];
			for (const [tag, member] of schema.members) {
				const r = validate(member, input);
				if (r.ok) return r;
				errs.push(...prefix(r.errs, tag));
			}
			return { ok: false, errs };
		}
		case 'tagged': {
			if (!isObj(input)) {
				return err('model_attributes_type', 'Input should be a valid dictionary or object to extract fields from');
			}
			if (!has(input, schema.disc)) {
				return err('union_tag_not_found', `Unable to extract tag using discriminator '${schema.disc}'`);
			}
			const tag = input[schema.disc]!;
			const hit = typeof tag === 'string' ? schema.choices.find(([k]) => k === tag) : undefined;
			if (!hit) {
				const expected = schema.choices.map(([k]) => `'${k}'`).join(', ');
				return err(
					'union_tag_invalid',
					`Input tag '${pyStr(tag)}' found using '${schema.disc}' does not match any of the expected tags: ${expected}`
				);
			}
			const r = validate(hit[1], input);
			return r.ok ? r : { ok: false, errs: prefix(r.errs, hit[0]) };
		}
		case 'model':
			return validateModel(schema, input);
	}
}

function bounds(schema: { ge?: number; le?: number }, v: number, fmt: (n: number) => string = num): Res {
	if (schema.ge !== undefined && !(v >= schema.ge)) {
		return err('greater_than_equal', `Input should be greater than or equal to ${fmt(schema.ge)}`);
	}
	if (schema.le !== undefined && !(v <= schema.le)) {
		return err('less_than_equal', `Input should be less than or equal to ${fmt(schema.le)}`);
	}
	return { ok: true, v };
}

function validateStr(schema: Extract<Schema, { t: 'str' }>, input: Json): Res {
	if (typeof input !== 'string') return err('string_type', 'Input should be a valid string');
	if (schema.min !== undefined || schema.max !== undefined) {
		const n = pyLen(input);
		if (schema.min !== undefined && n < schema.min) {
			return err('string_too_short', `String should have at least ${plural(schema.min, 'character')}`);
		}
		if (schema.max !== undefined && n > schema.max) {
			return err('string_too_long', `String should have at most ${plural(schema.max, 'character')}`);
		}
	}
	if (schema.re && !schema.re.test(input)) {
		return err('string_pattern_mismatch', `String should match pattern '${schema.pattern}'`);
	}
	if (schema.after) {
		const why = schema.after(input);
		if (why !== null) return err('value_error', `Value error, ${why}`);
	}
	return { ok: true, v: input };
}

function validateList(schema: Extract<Schema, { t: 'list' }>, input: Json): Res {
	const what = schema.tuple ? 'Tuple' : 'List';
	if (!Array.isArray(input)) {
		return schema.tuple
			? err('tuple_type', 'Input should be a valid tuple')
			: err('list_type', 'Input should be a valid list');
	}
	if (schema.max !== undefined && input.length > schema.max) {
		return err('too_long', `${what} should have at most ${plural(schema.max, 'item')} after validation, not ${input.length}`);
	}
	const errs: PydError[] = [];
	const out: Val[] = [];
	input.forEach((item, i) => {
		const r = validate(schema.item, item);
		if (r.ok) out.push(r.v);
		else errs.push(...prefix(r.errs, i));
	});
	if (errs.length) return { ok: false, errs };
	if (schema.min !== undefined && out.length < schema.min) {
		return err('too_short', `${what} should have at least ${plural(schema.min, 'item')} after validation, not ${out.length}`);
	}
	return { ok: true, v: out };
}

function validateDict(schema: Extract<Schema, { t: 'dict' }>, input: Json): Res {
	if (!isObj(input)) return err('dict_type', 'Input should be a valid dictionary');
	const errs: PydError[] = [];
	const out: { [k: string]: Val } = {};
	for (const k of Object.keys(input)) {
		const kr = validate(schema.key, k);
		if (!kr.ok) errs.push(...prefix(kr.errs, k, '[key]'));
		const vr = validate(schema.value, input[k]!);
		if (!vr.ok) errs.push(...prefix(vr.errs, k));
		if (kr.ok && vr.ok) setProp(out as JsonObject, kr.v as string, vr.v as Json);
	}
	if (errs.length) return { ok: false, errs };
	const n = Object.keys(out).length;
	if (schema.max !== undefined && n > schema.max) {
		return err('too_long', `Dictionary should have at most ${plural(schema.max, 'item')} after validation, not ${n}`);
	}
	return { ok: true, v: out };
}

function validateModel(schema: ModelSchema, input: Json): Res {
	if (!isObj(input)) return err('model_type', `Input should be a valid dictionary or instance of ${schema.name}`);
	const errs: PydError[] = [];
	const values = new Map<string, Val>();
	const set = new Set<string>();
	const used = new Set<string>();
	for (const f of schema.fields) {
		const key = f.alias !== undefined && has(input, f.alias) ? f.alias : has(input, f.name) ? f.name : undefined;
		const locKey = key ?? f.alias ?? f.name;
		if (key === undefined) {
			if (!('default' in f)) errs.push({ type: 'missing', loc: [locKey], msg: 'Field required' });
			else values.set(f.name, typeof f.default === 'function' ? f.default() : copyJson(f.default as Json));
			continue;
		}
		used.add(key);
		const r = validate(f.schema, input[key]!);
		if (!r.ok) {
			errs.push(...prefix(r.errs, locKey));
			continue;
		}
		if (f.after) {
			const why = f.after(r.v);
			if (why !== null) {
				errs.push({ type: 'value_error', loc: [locKey], msg: `Value error, ${why}` });
				continue;
			}
		}
		values.set(f.name, r.v);
		set.add(f.name);
	}
	for (const k of Object.keys(input)) {
		if (!used.has(k)) errs.push({ type: 'extra_forbidden', loc: [k], msg: 'Extra inputs are not permitted' });
	}
	if (errs.length) return { ok: false, errs };
	const v = new ModelVal(schema, values, set);
	if (schema.after) {
		const why = schema.after(v);
		if (why !== null) return err('value_error', `Value error, ${why}`);
	}
	return { ok: true, v };
}

const copyJson = deepCopy;

// --- decimals (Python `decimal.Decimal`, lax) -----------------------------------------------

const DECIMAL_RE = /^([+-])?(?:(\d(?:_?\d)*)(?:\.(\d(?:_?\d)*)?)?|\.(\d(?:_?\d)*))(?:[eE]([+-]?\d(?:_?\d)*))?$/;
const SPECIAL_RE = /^[+-]?(?:inf|infinity|s?nan\d*)$/i;

/** `str(Decimal(text))`, or null when Python would reject it. Throws 'inf' for infinities/NaN. */
export function decimalStr(text: string): string | null | 'special' {
	const s = strip(text);
	if (SPECIAL_RE.test(s)) return 'special';
	const m = DECIMAL_RE.exec(s);
	if (!m) return null;
	const sign = m[1] === '-' ? '-' : '';
	const intPart = (m[2] ?? '').replaceAll('_', '');
	const fracPart = (m[3] ?? m[4] ?? '').replaceAll('_', '');
	let exp = m[5] !== undefined ? Number(m[5].replaceAll('_', '')) : 0;
	exp -= fracPart.length;
	let coeff = (intPart + fracPart).replace(/^0+/, '');
	if (coeff === '') coeff = '0';
	return sciString(sign, coeff, exp);
}

function sciString(sign: string, digits: string, exp: number): string {
	const left = exp + digits.length;
	const dot = exp <= 0 && left > -6 ? left : 1;
	let intpart: string;
	let fracpart: string;
	if (dot <= 0) {
		intpart = '0';
		fracpart = '.' + '0'.repeat(-dot) + digits;
	} else if (dot >= digits.length) {
		intpart = digits + '0'.repeat(dot - digits.length);
		fracpart = '';
	} else {
		intpart = digits.slice(0, dot);
		fracpart = '.' + digits.slice(dot);
	}
	const e = left === dot ? '' : `E${left - dot >= 0 ? '+' : ''}${left - dot}`;
	return sign + intpart + fracpart + e;
}

function validateDecimal(input: Json): Res {
	const decimalType = (): Res =>
		err('decimal_type', 'Decimal input should be an integer, float, string or Decimal object');
	let text: string;
	if (typeof input === 'number') text = Number.isInteger(input) ? BigInt(input).toString() : reprFloat(input);
	else if (typeof input === 'string') text = input;
	else return decimalType();
	const out = decimalStr(text);
	if (out === 'special') return err('finite_number', 'Input should be a finite number');
	if (out === null) return err('decimal_parsing', 'Input should be a valid decimal');
	return { ok: true, v: out };
}

// --- dumps ------------------------------------------------------------------------------------

export interface DumpOptions {
	excludeUnset?: boolean;
	excludeNone?: boolean;
}

/** `model_dump(mode="json", by_alias=True, ...)`. */
export function dump(v: Val, o: DumpOptions = {}): Json {
	if (v instanceof ModelVal) {
		const out: JsonObject = {};
		for (const f of v.schema.fields) {
			if (o.excludeUnset && !v.fieldsSet.has(f.name)) continue;
			const x = v.get(f.name);
			if (o.excludeNone && x === null) continue;
			setProp(out, f.alias ?? f.name, dump(x, o));
		}
		return out;
	}
	if (Array.isArray(v)) return v.map((x) => dump(x, o));
	if (v !== null && typeof v === 'object') {
		const out: JsonObject = {};
		for (const k of Object.keys(v)) setProp(out, k, dump((v as { [k: string]: Val })[k]!, o));
		return out;
	}
	return v;
}

/** The validated params as plain values by attribute name (defaults filled in). */
export function attrs(v: Val): Json {
	if (v instanceof ModelVal) {
		const out: JsonObject = {};
		for (const f of v.schema.fields) setProp(out, f.name, attrs(v.get(f.name)));
		return out;
	}
	if (Array.isArray(v)) return v.map(attrs);
	if (v !== null && typeof v === 'object') {
		const out: JsonObject = {};
		for (const k of Object.keys(v)) setProp(out, k, attrs((v as { [k: string]: Val })[k]!));
		return out;
	}
	return v;
}
