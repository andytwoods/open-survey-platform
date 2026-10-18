/**
 * The TS expression syntax (src/syntax.ts) against `osp_expr.syntax` (.build/syntax.json,
 * from `make engine-fixtures`, scripts/build_syntax_vectors.py): the same AST JSON, the same
 * canonical text and the same diagnostics (code, message, start, end) on every fixture
 * expression, every case in python/osp-expr's tests and a generated corpus.
 */

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { codePointToUtf16, exprToText, parseExpr } from '../src/index.ts';
import type { Expr } from '../src/plan.ts';
import { BUILD } from './fixture-runner.ts';

interface ParseWant {
	expr: Expr | null;
	text: string | null;
	diagnostics: Array<[string, string, number | null, number | null]>;
}
interface Vectors {
	stats: Record<string, unknown>;
	print: Array<[Expr, string]>;
	parse: Array<[unknown, ParseWant]>;
}

const path = join(BUILD, 'syntax.json');
const vectors = (): Vectors => {
	expect(existsSync(path), 'run make engine-fixtures').toBe(true);
	return JSON.parse(readFileSync(path, 'utf8')) as Vectors;
};

describe('expression syntax parity with osp_expr.syntax', () => {
	const v = existsSync(path) ? vectors() : null;

	it('prints every AST to the same text', () => {
		const doc = v ?? vectors();
		expect(doc.print.length).toBeGreaterThan(2000);
		const bad = [];
		for (const [ast, want] of doc.print) {
			const got = exprToText(ast);
			if (got !== want) bad.push({ ast: JSON.stringify(ast).slice(0, 300), want, got });
		}
		expect(bad.slice(0, 5)).toEqual([]);
	});

	it('parses every source to the same AST, text and diagnostics', () => {
		const doc = v ?? vectors();
		expect(doc.parse.length).toBeGreaterThan(5000);
		let errors = 0;
		const bad = [];
		for (const [src, want] of doc.parse) {
			const res = parseExpr(src);
			const got = {
				expr: res.expr,
				text: res.expr ? exprToText(res.expr) : null,
				diagnostics: res.diagnostics.map((d) => [d.code, d.message, d.start, d.end])
			};
			if (!res.ok) errors++;
			if (res.ok !== (want.expr !== null) || JSON.stringify(got) !== JSON.stringify(want)) {
				bad.push({ src: typeof src === 'string' ? src.slice(0, 200) : src, want, got });
			}
		}
		expect(bad.slice(0, 5)).toEqual([]);
		expect(errors).toBeGreaterThan(2000); // the invalid corpus really is exercised
	});
});

describe('expression syntax', () => {
	it('round-trips the headline example', () => {
		const res = parseExpr('q3>5 and contains(q7,"b")');
		expect(res.ok).toBe(true);
		expect(exprToText(res.expr!)).toBe('q3 > 5 and contains(q7, "b")');
	});
	it('reports code point offsets, convertible to UTF-16 indexes', () => {
		const src = '"😀" == #';
		const d = parseExpr(src).diagnostics[0]!;
		expect([d.code, d.start, d.end]).toEqual(['unexpected-char', 7, 8]);
		expect(src.slice(codePointToUtf16(src, d.start!))).toBe('#');
	});
	it('never throws on non-text input', () => {
		expect(parseExpr(undefined).diagnostics[0]!.code).toBe('not-text');
		expect(parseExpr(42).ok).toBe(false);
	});
});
