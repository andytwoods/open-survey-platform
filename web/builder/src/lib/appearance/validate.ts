/**
 * Theme JSON import: parse untrusted text and validate it against the committed theme JSON
 * Schema (generated/theme.schema.json, a copy of osp_spec.theme's export). Never throws.
 *
 * A small interpreter for the JSON Schema keywords that schema uses (type, enum, const,
 * pattern, minimum/maximum, required, properties, additionalProperties, propertyNames,
 * anyOf, $ref), so the schema, not hand-written checks, decides. guard.test.ts proves it
 * accepts and rejects exactly what pydantic does on the golden cases.
 */
import type { Theme } from '@osp/ui-components';
import schemaJson from './generated/theme.schema.json';

type Schema = {
	$ref?: string;
	$defs?: Record<string, Schema>;
	type?: 'object' | 'string' | 'integer' | 'number' | 'null' | 'boolean' | 'array';
	enum?: unknown[];
	const?: unknown;
	pattern?: string;
	minimum?: number;
	maximum?: number;
	required?: string[];
	properties?: Record<string, Schema>;
	additionalProperties?: boolean | Schema;
	propertyNames?: Schema;
	anyOf?: Schema[];
};

const ROOT = schemaJson as unknown as Schema;

export interface ImportProblem {
	/** RFC 6901 pointer into the imported document. */
	pointer: string;
	message: string;
}

const esc = (k: string) => k.replace(/~/g, '~0').replace(/\//g, '~1');

function resolve(s: Schema): Schema {
	if (!s.$ref) return s;
	const name = s.$ref.replace('#/$defs/', '');
	const target = ROOT.$defs?.[name];
	if (!target) throw new Error(`Unknown $ref ${s.$ref}`);
	return resolve(target);
}

function typeOk(type: Schema['type'], v: unknown): boolean {
	switch (type) {
		case 'object':
			return typeof v === 'object' && v !== null && !Array.isArray(v);
		case 'array':
			return Array.isArray(v);
		case 'string':
			return typeof v === 'string';
		case 'integer':
			return typeof v === 'number' && Number.isInteger(v);
		case 'number':
			return typeof v === 'number' && Number.isFinite(v);
		case 'boolean':
			return typeof v === 'boolean';
		case 'null':
			return v === null;
		default:
			return true;
	}
}

function check(schema: Schema, v: unknown, ptr: string, out: ImportProblem[]): void {
	const s = resolve(schema);
	if (s.anyOf) {
		const branches = s.anyOf.map((b) => {
			const errs: ImportProblem[] = [];
			check(b, v, ptr, errs);
			return errs;
		});
		if (branches.some((e) => e.length === 0)) return;
		// Report the branch that got furthest (fewest problems), else a generic one.
		const best = branches.reduce((a, b) => (b.length < a.length ? b : a));
		out.push(...(best.length ? best : [{ pointer: ptr || '/', message: 'Value is not allowed.' }]));
		return;
	}
	const at = ptr || '/';
	if (s.type && !typeOk(s.type, v)) {
		out.push({ pointer: at, message: `Expected ${s.type === 'integer' ? 'a whole number' : `a ${s.type}`}.` });
		return;
	}
	if (s.const !== undefined && v !== s.const) {
		out.push({ pointer: at, message: `Must be ${JSON.stringify(s.const)}.` });
	}
	if (s.enum && !s.enum.includes(v)) {
		out.push({ pointer: at, message: `Must be one of ${s.enum.map((e) => JSON.stringify(e)).join(', ')}.` });
	}
	if (typeof v === 'string' && s.pattern && !new RegExp(s.pattern, 'u').test(v)) {
		out.push({ pointer: at, message: `${JSON.stringify(v)} does not have the expected format.` });
	}
	if (typeof v === 'number') {
		if (s.minimum !== undefined && v < s.minimum) out.push({ pointer: at, message: `Must be at least ${s.minimum}.` });
		if (s.maximum !== undefined && v > s.maximum) out.push({ pointer: at, message: `Must be at most ${s.maximum}.` });
	}
	if (s.type === 'object' && typeOk('object', v)) {
		const obj = v as Record<string, unknown>;
		for (const key of s.required ?? []) {
			if (!(key in obj)) out.push({ pointer: `${ptr}/${esc(key)}`, message: 'Required.' });
		}
		for (const [key, value] of Object.entries(obj)) {
			const child = `${ptr}/${esc(key)}`;
			if (s.propertyNames) {
				const errs: ImportProblem[] = [];
				check(s.propertyNames, key, child, errs);
				if (errs.length) out.push({ pointer: child, message: `${JSON.stringify(key)} is not an allowed key.` });
			}
			const prop = s.properties?.[key];
			if (prop) check(prop, value, child, out);
			else if (s.additionalProperties === false)
				out.push({ pointer: child, message: `Unknown field ${JSON.stringify(key)}.` });
			else if (typeof s.additionalProperties === 'object') check(s.additionalProperties, value, child, out);
		}
	}
}

/** Validate an already-parsed value against the theme schema. */
export function validateThemeValue(data: unknown): { theme: Theme | null; problems: ImportProblem[] } {
	const problems: ImportProblem[] = [];
	try {
		check(ROOT, data, '', problems);
	} catch (e) {
		problems.push({ pointer: '/', message: `Could not validate: ${(e as Error).message}` });
	}
	return problems.length ? { theme: null, problems } : { theme: data as Theme, problems };
}

/** Parse and validate theme JSON text (e.g. an imported file). */
export function parseThemeJson(text: string): { theme: Theme | null; problems: ImportProblem[] } {
	let data: unknown;
	try {
		data = JSON.parse(text);
	} catch (e) {
		return { theme: null, problems: [{ pointer: '/', message: `Not valid JSON: ${(e as Error).message}` }] };
	}
	return validateThemeValue(data);
}
