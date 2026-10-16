/**
 * The TS evaluator against `osp_expr.evaluate` on random ASTs and environments
 * (.build/expr.json, from `make engine-fixtures`): null rules, provisional ill-typed rules,
 * exact decimals with 28-digit ROUND_HALF_EVEN, Python whitespace trimming.
 */

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { evaluate, pyStrip, type Value } from '../src/index.ts';
import type { Expr } from '../src/plan.ts';
import * as dec from '../src/decimal.ts';
import { BUILD } from './fixture-runner.ts';

type EnvJson = null | { t: 'int' | 'dec' | 'text' | 'date' | 'multi'; v: string | Array<number | string> };
type ResultJson =
	| null
	| { k: 'bool'; v: boolean }
	| { k: 'num'; int: boolean; v: string }
	| { k: 'text' | 'date'; v: string }
	| { k: 'multi'; v: Array<number | string> };

function toValue(e: EnvJson): Value {
	if (e === null) return null;
	switch (e.t) {
		case 'int':
			return { k: 'num', v: dec.parseDecimal(e.v as string)!, int: true };
		case 'dec':
			return { k: 'num', v: dec.parseDecimal(e.v as string)!, int: false };
		case 'text': {
			const t = pyStrip(e.v as string);
			return t === '' ? null : { k: 'text', v: t };
		}
		case 'date':
			return { k: 'date', v: e.v as string };
		case 'multi': {
			const v = e.v as Array<number | string>;
			return v.length ? { k: 'multi', v } : null;
		}
	}
}

function same(actual: Value, want: ResultJson): boolean {
	if (want === null || actual === null) return want === actual;
	if (actual.k !== want.k) return false;
	if (want.k === 'num' && actual.k === 'num') {
		return actual.int === want.int && actual.v.eq(dec.parseDecimal(want.v)!);
	}
	if (want.k === 'multi' && actual.k === 'multi') {
		return JSON.stringify([...actual.v].map(String).sort()) === JSON.stringify(want.v.map(String).sort());
	}
	return (actual as { v: unknown }).v === (want as { v: unknown }).v;
}

describe('expression parity with osp_expr.evaluate', () => {
	it('gives the same value on every generated case', () => {
		const path = join(BUILD, 'expr.json');
		expect(existsSync(path), 'run make engine-fixtures').toBe(true);
		const rows = (JSON.parse(readFileSync(path, 'utf8')) as { rows: Array<[Expr, Record<string, EnvJson>, ResultJson]> })
			.rows;
		expect(rows.length).toBeGreaterThanOrEqual(5000);
		const bad: unknown[] = [];
		let numeric = 0;
		for (const [expr, env, want] of rows) {
			const got = evaluate(expr, (id) => toValue(env[id] ?? null));
			if (want?.k === 'num') numeric++;
			if (!same(got, want)) {
				bad.push({ expr, env, want, got: got && got.k === 'num' ? { ...got, v: got.v.toString() } : got });
			}
		}
		expect(bad.slice(0, 5)).toEqual([]);
		expect(numeric).toBeGreaterThan(500); // the vectors really exercise arithmetic
	});
});

describe('decimals', () => {
	const d = (s: string) => dec.parseDecimal(s)!;
	it('0.1 * 3 == 0.3 exactly, and 10 / 4 == 2.5', () => {
		expect(dec.mul(d('0.1'), d('3'), false).eq(d('0.3'))).toBe(true);
		expect(dec.div(d('10'), d('4'))!.eq(d('2.5'))).toBe(true);
	});
	it('rounds to 28 significant digits, half-even', () => {
		expect(dec.div(d('1'), d('3'))!.toFixed()).toBe('0.3333333333333333333333333333');
		expect(dec.div(d('2'), d('3'))!.toFixed()).toBe('0.6666666666666666666666666667');
		// A tie at the 29th digit rounds to even.
		expect(dec.add(d('1000000000000000000000000000'), d('0.5'), false).toFixed()).toBe('1000000000000000000000000000');
		expect(dec.add(d('1000000000000000000000000001'), d('0.5'), false).toFixed()).toBe('1000000000000000000000000002');
	});
	it('division by zero is null (provisional)', () => {
		expect(dec.div(d('1'), d('0'))).toBeNull();
	});
	it('trims like Python str.strip()', () => {
		expect(pyStrip('\u001c a \u0085')).toBe('a');
		expect(pyStrip('﻿a')).toBe('﻿a');
	});
});
