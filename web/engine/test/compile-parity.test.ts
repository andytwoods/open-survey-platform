/**
 * Python ⇄ TS parity for the plan compiler (task CE3, planning/client-edits.md decision 7):
 * every survey in .build/plan-vectors.json (fixtures, osp-spec cases, other committed
 * surveys, edge cases and seeded mutations; written by scripts/build_plan_vectors.py from
 * `osp_runtime.plan.compile_survey`) compiles in TS to the same canonical JSON, the same
 * checksum and the same runtime config. Refusals come from the validator (CE4); here the
 * validator is an oracle that returns Python's diagnostics, so the test checks that the TS
 * passes them through exactly as Python does and never crashes without one.
 */

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
	canonicalJson,
	compilePlan,
	compileSurvey,
	consentVersion,
	embedTheme,
	PlanError,
	runtimeConfig,
	segments,
	type PlanDiagnostic
} from '../src/index.ts';
import { BUILD } from './fixture-runner.ts';

interface Row {
	name: string;
	survey: unknown;
	hooks?: unknown;
	diagnostics: PlanDiagnostic[];
	plan: Record<string, unknown> | null;
	canonical?: string;
	checksum?: string;
	runtimeConfig?: unknown;
	runtimeConfigEndOnly?: unknown;
}
interface Vectors {
	rows: Row[];
	segments: Array<[string, unknown]>;
	consentVersion: Array<[unknown, unknown, unknown, string]>;
	embedTheme: Array<[string, unknown, Record<string, unknown>]>;
}

const PATH = join(BUILD, 'plan-vectors.json');
const vectors: Vectors | null = existsSync(PATH) ? (JSON.parse(readFileSync(PATH, 'utf8')) as Vectors) : null;

describe('plan compile parity', () => {
	it('has vectors (run make engine-fixtures)', () => {
		expect(vectors, 'run make engine-fixtures').not.toBeNull();
		const rows = vectors!.rows;
		expect(rows.length).toBeGreaterThan(400);
		expect(rows.filter((r) => r.name.startsWith('fixture/')).length).toBeGreaterThanOrEqual(41);
		expect(rows.filter((r) => r.plan !== null).length).toBeGreaterThan(350);
	});

	it('compiles every accepted survey byte-identically', () => {
		const mismatches: string[] = [];
		for (const row of vectors?.rows ?? []) {
			if (row.plan === null) continue;
			const oracle = () => row.diagnostics;
			const { plan, diagnostics } = compileSurvey(row.survey, { hooks: row.hooks, validate: oracle });
			const bare = compileSurvey(row.survey, { hooks: row.hooks });
			if (plan === null || bare.plan === null) {
				mismatches.push(`${row.name}: refused ${JSON.stringify(diagnostics.concat(bare.diagnostics))}`);
				continue;
			}
			if (canonicalJson(plan) !== row.canonical) mismatches.push(`${row.name}: canonical JSON`);
			if (plan.checksum !== row.checksum) mismatches.push(`${row.name}: checksum`);
			if (canonicalJson(bare.plan) !== row.canonical) mismatches.push(`${row.name}: canonical JSON (no validator)`);
			if (canonicalJson(diagnostics) !== canonicalJson(row.diagnostics)) mismatches.push(`${row.name}: diagnostics`);
			if (canonicalJson(runtimeConfig(plan)) !== canonicalJson(row.runtimeConfig)) {
				mismatches.push(`${row.name}: runtime config`);
			}
			if (canonicalJson(runtimeConfig(plan, { saveMode: 'end-only' })) !== canonicalJson(row.runtimeConfigEndOnly)) {
				mismatches.push(`${row.name}: runtime config (end-only)`);
			}
			expect(compilePlan(row.survey, { hooks: row.hooks, validate: oracle })).toEqual(plan);
		}
		expect(mismatches).toEqual([]);
	});

	it('refuses what Python refuses (validator diagnostics passed through), never crashing without one', () => {
		const refused = (vectors?.rows ?? []).filter((r) => r.plan === null);
		expect(refused.length).toBeGreaterThan(30);
		for (const row of refused) {
			const errors = row.diagnostics.filter((d) => d.severity === 'error');
			expect(errors.length, row.name).toBeGreaterThan(0);
			const validate = () => row.diagnostics;
			const out = compileSurvey(row.survey, { hooks: row.hooks, validate });
			expect(out.plan, row.name).toBeNull();
			expect(out.diagnostics, row.name).toEqual(row.diagnostics);
			let thrown: unknown = null;
			try {
				compilePlan(row.survey, { hooks: row.hooks, validate });
			} catch (e) {
				thrown = e;
			}
			expect(thrown, row.name).toBeInstanceOf(PlanError);
			expect((thrown as PlanError).diagnostics).toEqual(errors);
			expect(() => compileSurvey(row.survey, { hooks: row.hooks })).not.toThrow();
		}
	});

	it('splits text into segments as Python does', () => {
		for (const [text, expected] of vectors?.segments ?? []) {
			expect(segments(text), JSON.stringify(text)).toEqual(expected);
		}
	});

	it('computes consent versions and embeds themes as Python does', () => {
		for (const [t, a, d, v] of vectors?.consentVersion ?? []) expect(consentVersion(t, a, d)).toBe(v);
		for (const [name, theme, expected] of vectors?.embedTheme ?? []) {
			const row = vectors!.rows.find((r) => r.name === name)!;
			const plan = compilePlan(row.survey, { hooks: row.hooks });
			expect(canonicalJson(embedTheme(plan, theme))).toBe(canonicalJson(expected));
		}
	});

	it('gives internal.error, not an exception, for documents it cannot compile', () => {
		const bad = [null, 1, 'x', [], {}, { metadata: {} }, { metadata: { languages: ['en'] }, flow: [{ type: 'zzz' }] }];
		for (const doc of bad) {
			const out = compileSurvey(doc);
			expect(out.plan).toBeNull();
			expect(out.diagnostics.map((d) => d.code)).toEqual(['internal.error']);
		}
	});
});
