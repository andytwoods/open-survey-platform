/**
 * Python ⇄ TS validator parity (task CE4): every document in .build/vectors.json (written by
 * `make spec-vectors` from osp_spec.validate) gets exactly Python's diagnostics: same codes,
 * severities, messages and pointers, in the same order.
 */

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { CODES, type Diagnostic, validate } from '../src/index.ts';

interface Vector {
	name: string;
	doc: unknown;
	diagnostics: Diagnostic[];
}

const PATH = join(import.meta.dirname, '..', '.build', 'vectors.json');

describe('validator parity with osp_spec.validate', () => {
	it('has vectors (make spec-vectors)', () => {
		expect(existsSync(PATH), 'run make spec-vectors').toBe(true);
	});
	const vectors: Vector[] = existsSync(PATH) ? (JSON.parse(readFileSync(PATH, 'utf8')) as Vector[]) : [];

	it('covers fixtures, test cases, mutations and random JSON', () => {
		const kinds = new Set(vectors.map((v) => v.name.split('/')[0]));
		for (const k of ['fixture', 'case', 'spec-test', 'mutant', 'random']) expect(kinds.has(k), k).toBe(true);
		expect(vectors.length).toBeGreaterThan(3000);
	});

	it('gives identical diagnostics for every vector', () => {
		const failures: string[] = [];
		for (const v of vectors) {
			let got: Diagnostic[];
			try {
				got = validate(v.doc);
			} catch (e) {
				failures.push(`${v.name}: threw ${String(e)}`);
				continue;
			}
			const a = JSON.stringify(got.map((d) => [d.code, d.severity, d.pointer, d.message]));
			const b = JSON.stringify(v.diagnostics.map((d) => [d.code, d.severity, d.pointer, d.message]));
			if (a !== b) failures.push(`${v.name}:\n  ts: ${a}\n  py: ${b}`);
		}
		expect(failures.length, failures.slice(0, 8).join('\n')).toBe(0);
	});

	it('emits only known codes with their severities', () => {
		for (const v of vectors.slice(0, 200)) {
			for (const d of validate(v.doc)) expect(CODES[d.code]).toBe(d.severity);
		}
	});
});
