/**
 * A small emulation of pydantic-core for the `osp-survey` model: the validators the model
 * uses (strict and lax scalars, literals, lists, tuples, dicts, models with aliases and
 * `extra="forbid"`, smart unions, tagged unions, nullable), each producing the errors
 * pydantic produces, with the same `type`, `loc`, `msg` and order. A successful run returns
 * the parsed value (defaults filled, field names as in Python, dicts as `Map`).
 *
 * Numbers: a JavaScript number that is an integer is a Python `int`, anything else a
 * `float` (JSON text `1.0` is therefore an int here; README, "Differences").
 */

import { parseDecimal } from './decimal.ts';
import { DIGIT_CLASS, hasOwn, isObject, pyLen, pyRepr, pyStr } from './py.ts';

export type LocElem = string | number;

export interface PErr {
	type: string;
	loc: LocElem[];
	msg: string;
	discriminator?: string;
}

export type Result = { ok: true; value: unknown } | { ok: false; errors: PErr[] };

export interface Validator {
	label: string;
	run(input: unknown): Result;
}

const ok = (value: unknown): Result => ({ ok: true, value });
const fail = (type: string, msg: string, loc: LocElem[] = []): Result => ({
	ok: false,
	errors: [{ type, loc, msg }]
});

function prefix(errors: PErr[], ...head: LocElem[]): PErr[] {
	return errors.map((e) => ({ ...e, loc: [...head, ...e.loc] }));
}

const LONE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/g;

/** pydantic-core works on Rust strings: a lone surrogate cannot be converted. */
export function hasLoneSurrogate(s: string): boolean {
	return new RegExp(LONE.source).test(s);
}

/** A string as pydantic-core prints it in a location or message: each lone surrogate is
 * three U+FFFD (its surrogatepass UTF-8 bytes, decoded lossily). */
export function lossy(s: string): string {
	return s.replace(LONE, '\ufffd\ufffd\ufffd');
}

const UNICODE_MSG = 'Input should be a valid string, unable to parse raw data as a unicode string';

export const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v);

function plural(n: number, word: string): string {
	return `${n} ${word}${n === 1 ? '' : 's'}`;
}

// --- Strings ------------------------------------------------------------------------------

export interface StrOpts {
	pattern?: string;
	min?: number;
	max?: number;
}

/** A pydantic pattern (Rust `regex` syntax, `\d` Unicode) as a JavaScript RegExp. */
function rustRegex(pattern: string): RegExp {
	return new RegExp(pattern.replaceAll('\\d', `[${DIGIT_CLASS}]`), 'u');
}

export function str(opts: StrOpts = {}): Validator {
	const re = opts.pattern === undefined ? null : rustRegex(opts.pattern);
	const constrained = opts.pattern !== undefined || opts.min !== undefined || opts.max !== undefined;
	return {
		label: constrained ? 'constrained-str' : 'str',
		run(input) {
			if (typeof input !== 'string') return fail('string_type', 'Input should be a valid string');
			if (constrained && hasLoneSurrogate(input)) return fail('string_unicode', UNICODE_MSG);
			if (opts.min !== undefined || opts.max !== undefined) {
				const n = pyLen(input);
				if (opts.min !== undefined && n < opts.min) {
					return fail('string_too_short', `String should have at least ${plural(opts.min, 'character')}`);
				}
				if (opts.max !== undefined && n > opts.max) {
					return fail('string_too_long', `String should have at most ${plural(opts.max, 'character')}`);
				}
			}
			if (re !== null && !re.test(input)) {
				return fail('string_pattern_mismatch', `String should match pattern '${opts.pattern}'`);
			}
			return ok(input);
		}
	};
}

// --- Numbers and booleans -------------------------------------------------------------------

export interface NumOpts {
	ge?: number;
	le?: number;
}

function bounds(v: number, opts: NumOpts): Result {
	if (opts.ge !== undefined && !(v >= opts.ge)) {
		return fail('greater_than_equal', `Input should be greater than or equal to ${opts.ge}`);
	}
	if (opts.le !== undefined && !(v <= opts.le)) {
		return fail('less_than_equal', `Input should be less than or equal to ${opts.le}`);
	}
	return ok(v);
}

/** `StrictInt` (also `int` under a strict model config). */
export function int(opts: NumOpts = {}): Validator {
	const constrained = opts.ge !== undefined || opts.le !== undefined;
	return {
		label: constrained ? 'constrained-int' : 'int',
		run(input) {
			if (!isInt(input)) return fail('int_type', 'Input should be a valid integer');
			return bounds(input, opts);
		}
	};
}

/** Strict `float` (ints accepted, as in pydantic). */
export function float(opts: NumOpts = {}): Validator {
	const constrained = opts.ge !== undefined || opts.le !== undefined;
	return {
		label: constrained ? 'constrained-float' : 'float',
		run(input) {
			if (typeof input !== 'number') return fail('float_type', 'Input should be a valid number');
			if (!Number.isFinite(input)) return fail('finite_number', 'Input should be a finite number');
			return bounds(input, opts);
		}
	};
}

export const bool: Validator = {
	label: 'bool',
	run(input) {
		return typeof input === 'boolean' ? ok(input) : fail('bool_type', 'Input should be a valid boolean');
	}
};

/** Lax `Decimal` with `allow_inf_nan=False` (expression decimal literals). The parsed
 * value is the input (kept for the zero test). */
export const decimalLax: Validator = {
	label: 'decimal',
	run(input) {
		if (typeof input === 'number') return ok(input);
		if (typeof input !== 'string') {
			return fail('decimal_type', 'Decimal input should be an integer, float, string or Decimal object');
		}
		const p = parseDecimal(input);
		if (p === null) return fail('decimal_parsing', 'Input should be a valid decimal');
		if (p.kind !== 'finite') return fail('finite_number', 'Input should be a finite number');
		return ok(input);
	}
};

/** `JsonValue`: any JSON value. */
export const jsonValue: Validator = { label: 'json', run: (input) => ok(input) };

// --- Literals -------------------------------------------------------------------------------

function joinOr(parts: string[]): string {
	if (parts.length <= 1) return parts.join('');
	return parts.slice(0, -1).join(', ') + ' or ' + parts[parts.length - 1];
}

export function literal(...values: Array<string | true>): Validator {
	const expected = joinOr(values.map((v) => pyRepr(v)));
	return {
		label: `literal[${values.map((v) => pyRepr(v)).join(',')}]`,
		run(input) {
			if (typeof input === 'string' && hasLoneSurrogate(input)) return fail('string_unicode', UNICODE_MSG);
			for (const v of values) {
				if (v === true ? input === true || input === 1 : input === v) return ok(v);
			}
			return fail('literal_error', `Input should be ${expected}`);
		}
	};
}

// --- Containers -----------------------------------------------------------------------------

export function list(item: Validator, opts: { min?: number } = {}): Validator {
	return {
		label: `list[${item.label}]`,
		run(input) {
			if (!Array.isArray(input)) return fail('list_type', 'Input should be a valid list');
			const out: unknown[] = [];
			const errors: PErr[] = [];
			input.forEach((x, i) => {
				const r = item.run(x);
				if (r.ok) out.push(r.value);
				else errors.push(...prefix(r.errors, i));
			});
			if (errors.length) return { ok: false, errors };
			if (opts.min !== undefined && out.length < opts.min) {
				return fail(
					'too_short',
					`List should have at least ${plural(opts.min, 'item')} after validation, not ${out.length}`
				);
			}
			return ok(out);
		}
	};
}

/** Lax variadic `tuple[X, ...]` (the expression `and`/`or` operands). */
export function tuple(item: Validator, opts: { min?: number } = {}): Validator {
	return {
		label: `tuple[${item.label}, ...]`,
		run(input) {
			if (!Array.isArray(input)) return fail('tuple_type', 'Input should be a valid tuple');
			const out: unknown[] = [];
			const errors: PErr[] = [];
			input.forEach((x, i) => {
				const r = item.run(x);
				if (r.ok) out.push(r.value);
				else errors.push(...prefix(r.errors, i));
			});
			if (opts.min !== undefined && out.length < opts.min) {
				errors.push({
					type: 'too_short',
					loc: [],
					msg: `Tuple should have at least ${plural(opts.min, 'item')} after validation, not ${out.length}`
				});
			}
			return errors.length ? { ok: false, errors } : ok(out);
		}
	};
}

export function dict(key: Validator, value: Validator, opts: { max?: number } = {}): Validator {
	return {
		label: `dict[${key.label},${value.label}]`,
		run(input) {
			if (!isObject(input)) return fail('dict_type', 'Input should be a valid dictionary');
			const out = new Map<string, unknown>();
			const errors: PErr[] = [];
			for (const k of Object.keys(input)) {
				const kr = key.run(k);
				if (!kr.ok) errors.push(...prefix(kr.errors, lossy(k), '[key]'));
				const vr = value.run(input[k]);
				if (!vr.ok) errors.push(...prefix(vr.errors, lossy(k)));
				if (kr.ok && vr.ok) out.set(k, vr.value);
			}
			if (errors.length) return { ok: false, errors };
			if (opts.max !== undefined && out.size > opts.max) {
				return fail(
					'too_long',
					`Dictionary should have at most ${plural(opts.max, 'item')} after validation, not ${out.size}`
				);
			}
			return ok(out);
		}
	};
}

// --- Models ---------------------------------------------------------------------------------

export interface Field {
	name: string; // the Python attribute name (the parsed object's key)
	alias?: string;
	v: Validator | (() => Validator);
	/** Absent field: the default (a function for a fresh value). No default: required. */
	default?: unknown;
	/** `field_validator(mode="after")`: an error message raises a ValueError. */
	after?: (value: unknown) => string | null;
}

export interface ModelOpts {
	/** `model_validator(mode="after")` on the parsed object: a ValueError message or null. */
	after?: (value: Record<string, unknown>) => string | null;
}

const thunks = new WeakMap<() => Validator, Validator>();

/** A validator, or a thunk for one (recursive models), evaluated once. */
function resolve(v: Validator | (() => Validator)): Validator {
	if (typeof v !== 'function') return v;
	let hit = thunks.get(v);
	if (hit === undefined) {
		hit = v();
		thunks.set(v, hit);
	}
	return hit;
}

export function model(name: string, fields: Field[], opts: ModelOpts = {}): Validator {
	return {
		label: name,
		run(input) {
			if (!isObject(input)) {
				return fail('model_type', `Input should be a valid dictionary or instance of ${name}`);
			}
			if (Object.keys(input).some(hasLoneSurrogate)) return fail('string_unicode', UNICODE_MSG);
			const used = new Set<string>();
			const out: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
			const errors: PErr[] = [];
			for (const f of fields) {
				let key: string | null = null;
				if (f.alias !== undefined && hasOwn(input, f.alias)) key = f.alias;
				else if (hasOwn(input, f.name)) key = f.name;
				if (key === null) {
					if ('default' in f) {
						out[f.name] = typeof f.default === 'function' ? (f.default as () => unknown)() : f.default;
					} else errors.push({ type: 'missing', loc: [f.alias ?? f.name], msg: 'Field required' });
					continue;
				}
				used.add(key);
				const r = resolve(f.v).run(input[key]);
				if (!r.ok) {
					errors.push(...prefix(r.errors, key));
					continue;
				}
				const why = f.after ? f.after(r.value) : null;
				if (why !== null) {
					errors.push({ type: 'value_error', loc: [key], msg: `Value error, ${why}` });
					continue;
				}
				out[f.name] = r.value;
			}
			for (const k of Object.keys(input)) {
				if (!used.has(k)) errors.push({ type: 'extra_forbidden', loc: [k], msg: 'Extra inputs are not permitted' });
			}
			if (errors.length) return { ok: false, errors };
			const why = opts.after ? opts.after(out) : null;
			if (why !== null) return fail('value_error', `Value error, ${why}`);
			return ok(out);
		}
	};
}

// --- Unions ---------------------------------------------------------------------------------

/** A smart (non-discriminated) union: the first member that succeeds; if none does, every
 * member's errors, each under the member's label. */
export function union(...members: Array<Validator | (() => Validator)>): Validator {
	return {
		get label() {
			return `union[${members.map((m) => resolve(m).label).join(',')}]`;
		},
		run(input) {
			const errors: PErr[] = [];
			for (const m of members) {
				const v = resolve(m);
				const r = v.run(input);
				if (r.ok) return r;
				errors.push(...prefix(r.errors, v.label));
			}
			return { ok: false, errors };
		}
	};
}

/** `Field(discriminator=key)`: members by tag value, in declaration order. */
export function tagged(key: string, members: Array<[string, Validator | (() => Validator)]>): Validator {
	const byTag = new Map(members);
	const expected = members.map(([t]) => `'${t}'`).join(', ');
	return {
		label: `tagged-union[${members.map(([t]) => t).join(',')}]`,
		run(input) {
			if (!isObject(input)) {
				return fail('model_attributes_type', 'Input should be a valid dictionary or object to extract fields from');
			}
			if (!hasOwn(input, key)) {
				return {
					ok: false,
					errors: [
						{
							type: 'union_tag_not_found',
							loc: [],
							msg: `Unable to extract tag using discriminator '${key}'`,
							discriminator: `'${key}'`
						}
					]
				};
			}
			const tag = input[key];
			const member = typeof tag === 'string' ? byTag.get(tag) : undefined;
			if (member === undefined) {
				return {
					ok: false,
					errors: [
						{
							type: 'union_tag_invalid',
							loc: [],
							msg: `Input tag '${lossy(pyStr(tag))}' found using '${key}' does not match any of the expected tags: ${expected}`,
							discriminator: `'${key}'`
						}
					]
				};
			}
			const r = resolve(member).run(input);
			return r.ok ? r : { ok: false, errors: prefix(r.errors, tag as string) };
		}
	};
}

/** `X | None`. */
export function nullable(inner: Validator | (() => Validator)): Validator {
	return {
		get label() {
			return `nullable[${resolve(inner).label}]`;
		},
		run(input) {
			return input === null ? ok(null) : resolve(inner).run(input);
		}
	};
}
