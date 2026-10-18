/**
 * Python ⇄ TypeScript parity for the ops (planning/client-edits.md, decision 2). Vectors are
 * written by web/ops/scripts/build_vectors.py (`make ops-parity`) into .build/:
 *
 * - every op on every fixture (and the guard's EXAMPLES on the ops tests' base survey),
 *   hostile params and hostile surveys, each with its undo;
 * - seeded random sequences of runs and transactions with undo and redo;
 * - pydantic vectors for every params model and the models the ops validate;
 * - Python string/number helpers.
 *
 * Every result must be byte-identical canonical JSON: the document (by SHA-256), the patch,
 * the inverse, the diagnostics and, for transactions, status, revision and failed index.
 * The survey validator is an oracle answering from what Python's validator said about the
 * same documents (oracle.json); a document Python never validated is a failure.
 */

import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
	REGISTRY,
	applyTransaction,
	invoke,
	run,
	type Diagnostic,
	type Invocation,
	type Json,
	type OpResult,
	type OpsEnv,
	type TransactionResult
} from '../src/index.ts';
import { ExprAdapter, Ending, FIXED_CLASSES, Hooks, METADATA, NODE_CLASSES, QUESTION_CLASSES, RedirectTemplate, SETTINGS, Source, Theme, VARIABLE_CLASSES } from '../src/models.ts';
import { attrs, decimalStr, dump, validate, type DumpOptions, type Schema } from '../src/pyd.ts';
import { reprFloat, reprStr, splitlines, strip } from '../src/py.ts';

const BUILD = join(import.meta.dirname, '..', '.build');

function load<T>(name: string): T {
	const path = join(BUILD, name);
	if (!existsSync(path)) throw new Error(`${path} is missing: run make ops-parity (or uv run python web/ops/scripts/build_vectors.py)`);
	return JSON.parse(readFileSync(path, 'utf8')) as T;
}

// Key order matters (it is what patches, diagnostics and exports follow): documents are
// hashed, and results compared, as JSON in their own key order.
const hash = (v: Json): string => createHash('sha256').update(JSON.stringify(v)).digest('hex');
const canon = (v: unknown): string => JSON.stringify(v);

interface Oracle {
	parse: Record<string, { valid: boolean; diagnostics: Diagnostic[] }>;
	fragment: Record<string, Diagnostic[]>;
	expr: Record<string, { expr: Json } | { expr: null; diagnostics: { code: string; message: string; start: number; end: number }[] }>;
}

const oracle = load<Oracle>('oracle.json');
const misses: string[] = [];

function miss(what: string): Diagnostic[] {
	misses.push(what);
	return [{ severity: 'error', code: 'oracle.miss', message: what, pointer: '' }];
}

const env: OpsEnv = {
	validator: {
		parse(doc) {
			const r = oracle.parse[hash(doc)];
			return r ?? { valid: false, diagnostics: miss(`parse ${hash(doc)}`) };
		},
		checkFragment(fragment) {
			return oracle.fragment[hash(fragment)] ?? miss(`fragment ${hash(fragment)}`);
		},
		parseExpression(text) {
			return oracle.expr[text] ?? { expr: null, diagnostics: miss(`expr ${text}`).map(() => ({ code: 'oracle.miss', message: text, start: 0, end: 0 })) };
		}
	}
};

function opView(res: OpResult): unknown {
	return { ok: res.ok, survey: hash(res.survey), inverse: res.inverse, patch: res.patch, diagnostics: res.diagnostics };
}

function txView(res: TransactionResult): unknown {
	return {
		status: res.status,
		survey: hash(res.draft.survey),
		revision: res.draft.revision,
		inverse: res.inverse,
		patch: res.patch,
		diagnostics: res.diagnostics,
		failedIndex: res.failedIndex
	};
}

interface Failure {
	where: string;
	expected: unknown;
	actual: unknown;
}

function report(failures: Failure[]): string {
	return failures
		.slice(0, 5)
		.map((f) => `${f.where}\n  expected ${canon(f.expected).slice(0, 1500)}\n  actual   ${canon(f.actual).slice(0, 1500)}`)
		.join('\n');
}

// --- fields and catalogue ------------------------------------------------------------------------

describe('registry and model fields', () => {
	const fields = load<{
		ops: { id: string; label: string; area: string; wholeDocument: boolean }[];
		question: Record<string, { name: string; fields: string[] }>;
		node: Record<string, { name: string; fields: string[] }>;
		variable: Record<string, { name: string; fields: string[] }>;
		fixed: Record<string, { name: string; fields: string[] }>;
		singletons: Record<string, { name: string; fields: string[] }>;
	}>('fields.json');

	it(`registers the same ${fields.ops.length} ops`, () => {
		const ours = [...REGISTRY.values()]
			.map((s) => ({ id: s.id, label: s.label, area: s.area, wholeDocument: s.wholeDocument }))
			.sort((a, b) => (a.id < b.id ? -1 : 1));
		expect(ours).toEqual(fields.ops);
	});

	it('has the same model_fields for set_property', () => {
		expect(QUESTION_CLASSES).toEqual(fields.question);
		expect(NODE_CLASSES).toEqual(fields.node);
		expect(VARIABLE_CLASSES).toEqual(fields.variable);
		expect(FIXED_CLASSES).toEqual(fields.fixed);
		expect({ '/metadata': METADATA, '/settings': SETTINGS }).toEqual(fields.singletons);
	});
});

// --- helpers --------------------------------------------------------------------------------------

describe('Python helpers', () => {
	const py = load<{
		repr: [string, string][];
		strip: [string, string][];
		splitlines: [string, string[]][];
		decimal: [string, string | null][];
		float: [number, string][];
	}>('py.json');

	it('repr, strip, splitlines', () => {
		expect(py.repr.filter(([s, want]) => reprStr(s) !== want)).toEqual([]);
		expect(py.strip.filter(([s, want]) => strip(s) !== want)).toEqual([]);
		expect(py.splitlines.filter(([s, want]) => canon(splitlines(s)) !== canon(want))).toEqual([]);
	});

	it('Decimal and float text', () => {
		expect(py.decimal.filter(([s, want]) => decimalStr(s) !== want)).toEqual([]);
		expect(py.float.filter(([f, want]) => reprFloat(f) !== want)).toEqual([]);
	});
});

// --- pydantic models --------------------------------------------------------------------------------

describe('models (pydantic parity)', () => {
	const models = load<Record<string, { input: Json; dump?: Json; errors?: { type: string; loc: (string | number)[]; msg: string }[] }[]>>(
		'models.json'
	);
	const table: Record<string, [Schema, ((v: never) => Json) | DumpOptions]> = {
		Ending: [Ending, { excludeUnset: true }],
		RedirectTemplate: [RedirectTemplate, { excludeNone: true }],
		Source: [Source, { excludeNone: true }],
		Hooks: [Hooks, { excludeNone: true }],
		Theme: [Theme, {}],
		Expr: [ExprAdapter, {}]
	};

	for (const [name, rows] of Object.entries(models)) {
		it(`${name}: ${rows.length} inputs`, () => {
			let schema: Schema;
			let out: (v: never) => Json;
			if (name.startsWith('params:')) {
				schema = REGISTRY.get(name.slice(7))!.params;
				out = (v) => attrs(v);
			} else {
				const [s, o] = table[name]!;
				schema = s;
				out = typeof o === 'function' ? o : (v) => dump(v, o);
			}
			const failures: Failure[] = [];
			rows.forEach((row, i) => {
				const r = validate(schema, row.input);
				const actual = r.ok ? { dump: out(r.v as never) } : { errors: r.errs };
				const expected = row.errors ? { errors: row.errors } : { dump: row.dump };
				if (canon(actual) !== canon(expected)) failures.push({ where: `${name}[${i}] ${canon(row.input).slice(0, 300)}`, expected, actual });
			});
			expect(failures.length, report(failures)).toBe(0);
		});
	}
});

// --- op x fixture -------------------------------------------------------------------------------------

interface SingleCase {
	doc?: string;
	fixture?: string;
	op?: Json;
	params?: Json;
	chain?: number;
	result: unknown;
}

describe('op x fixture', () => {
	const single = load<{ docs: Record<string, Json>; cases: SingleCase[] }>('single.json');
	const byOp = new Map<string, number[]>();
	single.cases.forEach((c, i) => {
		let root = c;
		while (root.chain !== undefined) root = single.cases[root.chain]!;
		const key = String(root.op);
		if (!byOp.has(key)) byOp.set(key, []);
		byOp.get(key)!.push(i);
	});
	const results = new Map<number, OpResult>();

	for (const [opId, indices] of [...byOp.entries()].sort()) {
		it(`${opId}: ${indices.length} cases`, () => {
			const failures: Failure[] = [];
			for (const i of indices) {
				const c = single.cases[i]!;
				let res: OpResult;
				if (c.chain !== undefined) {
					const parent = results.get(c.chain);
					if (!parent || !parent.ok || !parent.inverse) {
						failures.push({ where: `case ${i}: undo of case ${c.chain} (which did not succeed in TS)`, expected: c.result, actual: null });
						continue;
					}
					res = invoke(parent.inverse, parent.survey, env);
				} else res = run(c.op, single.docs[c.doc!]!, c.params, env);
				results.set(i, res);
				const actual = opView(res);
				if (canon(actual) !== canon(c.result)) {
					const what = c.chain !== undefined ? `undo of case ${c.chain}` : `${c.fixture} ${canon(c.params as Json).slice(0, 400)}`;
					failures.push({ where: `case ${i}: ${what}`, expected: c.result, actual });
				}
			}
			expect(failures.length, report(failures)).toBe(0);
		});
	}
});

// --- calls from the osp-ops test suite ------------------------------------------------------------------

describe('calls harvested from python/osp-ops/tests', () => {
	const data = load<{
		docs: Record<string, Json>;
		calls: { kind: 'run' | 'invoke' | 'tx'; doc: string; op?: Json; params?: Json; inv?: Json; revision?: number; ops?: Json; base?: Json; result: unknown }[];
	}>('tests.json');

	it(`${data.calls.length} run / invoke / apply_transaction calls give the same results`, () => {
		const failures: Failure[] = [];
		data.calls.forEach((c, i) => {
			const doc = data.docs[c.doc] as Json;
			let actual: unknown;
			if (c.kind === 'run') actual = opView(run(c.op, doc, c.params, env));
			else if (c.kind === 'invoke') actual = opView(invoke(c.inv, doc, env));
			else actual = txView(applyTransaction({ survey: doc, revision: c.revision! }, c.ops, c.base, env));
			if (canon(actual) !== canon(c.result)) {
				failures.push({ where: `call ${i} ${c.kind} ${canon((c.op ?? c.inv ?? c.ops) as Json).slice(0, 200)} ${canon((c.params ?? '') as Json).slice(0, 400)}`, expected: c.result, actual });
			}
		});
		expect(failures.length, report(failures)).toBe(0);
	});
});

// --- random sequences -----------------------------------------------------------------------------------

interface Step {
	kind: 'run' | 'tx' | 'undo' | 'redo';
	op?: string;
	params?: Json;
	ops?: Json;
	base?: Json;
	result: unknown;
}

describe('seeded random sequences', () => {
	const data = load<{ docs: Record<string, Json>; sequences: { seed: number; start: { fixture: string; doc: string; revision: number }; steps: Step[]; final: string }[] }>(
		'sequences.json'
	);
	const nSteps = data.sequences.reduce((n, s) => n + s.steps.length, 0);

	it(`${data.sequences.length} sequences, ${nSteps} steps: same documents, patches, inverses, diagnostics`, () => {
		const failures: Failure[] = [];
		for (const seq of data.sequences) {
			let doc: Json = data.docs[seq.start.doc] as Json;
			let rev = seq.start.revision;
			const undo: Invocation[][] = [];
			const redo: Invocation[][] = [];
			let failed = false;
			for (let i = 0; i < seq.steps.length && !failed; i++) {
				const step = seq.steps[i]!;
				const where = `seed ${seq.seed} (${seq.start.fixture}) step ${i} ${step.kind} ${canon((step.op ?? step.ops ?? '') as Json).slice(0, 300)} ${canon((step.params ?? '') as Json).slice(0, 300)}`;
				let actual: unknown;
				if (step.kind === 'run') {
					const res = run(step.op, doc, step.params, env);
					actual = opView(res);
					if (res.ok) {
						doc = res.survey;
						rev += res.patch.length ? 1 : 0;
						undo.push([res.inverse!]);
						redo.length = 0;
					}
				} else if (step.kind === 'tx') {
					const res = applyTransaction({ survey: doc, revision: rev }, step.ops, step.base, env);
					actual = txView(res);
					if (res.status === 'ok') {
						doc = res.draft.survey;
						rev = res.draft.revision;
						if (res.patch.length) {
							undo.push(res.inverse);
							redo.length = 0;
						}
					}
				} else {
					const from = step.kind === 'undo' ? undo : redo;
					const to = step.kind === 'undo' ? redo : undo;
					const inv = from.pop();
					if (inv === undefined) {
						failures.push({ where, expected: step.result, actual: 'nothing to ' + step.kind });
						break;
					}
					const res = applyTransaction({ survey: doc, revision: rev }, inv, rev, env);
					actual = txView(res);
					if (res.status === 'ok') {
						doc = res.draft.survey;
						rev = res.draft.revision;
						to.push(res.inverse);
					}
				}
				if (canon(actual) !== canon(step.result)) {
					failures.push({ where, expected: step.result, actual });
					failed = true;
				}
			}
			if (!failed && hash(doc) !== seq.final) failures.push({ where: `seed ${seq.seed}: final document`, expected: seq.final, actual: hash(doc) });
		}
		expect(failures.length, report(failures)).toBe(0);
	});

	it('asked the validator only about documents Python validated', () => {
		expect(misses.slice(0, 10)).toEqual([]);
	});
});
