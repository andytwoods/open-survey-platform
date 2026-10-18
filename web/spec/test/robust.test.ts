/**
 * Never crash on input (AGENTS.md rule 3), including values only JavaScript has, and the
 * documented differences from Python (README.md, "Differences").
 */

import { describe, expect, it } from 'vitest';
import { validate } from '../src/index.ts';
import { compileFull } from '../src/pyregex.ts';

const SURVEY = {
	specVersion: 'osp-survey/0.1',
	id: 's',
	metadata: { title: 'T', languages: ['en'] },
	blocks: [{ id: 'b', pages: [{ id: 'p', items: [{ id: 'q1', type: 'integer', label: 'Q' }] }] }],
	flow: [{ type: 'block', id: 'n', block: 'b' }]
};

/** A seeded generator (no Math.random: reproducible failures). */
function rng(seed: number): () => number {
	let x = seed >>> 0;
	return () => {
		x = (Math.imul(x ^ (x >>> 15), 0x2c1b3c6d) + 0x9e3779b9) >>> 0;
		return x / 2 ** 32;
	};
}

const ODD: unknown[] = [undefined, NaN, Infinity, -Infinity, -0, 2 ** 60, 1e300, () => 1, Symbol('x'), new Date(0), new Map(), /x/, 10n];

function mutate(value: unknown, r: () => number, depth = 0): unknown {
	if (depth > 6 || r() < 0.08) return ODD[Math.floor(r() * ODD.length)];
	if (Array.isArray(value)) return value.map((v) => mutate(v, r, depth + 1));
	if (typeof value === 'object' && value !== null) {
		const out: Record<string, unknown> = {};
		for (const [k, v] of Object.entries(value)) out[k] = mutate(v, r, depth + 1);
		if (r() < 0.1) Object.setPrototypeOf(out, { inherited: 1 });
		return out;
	}
	return value;
}

describe('never throws', () => {
	it('on JavaScript-only values anywhere in a survey', () => {
		const r = rng(42);
		for (let i = 0; i < 2000; i++) {
			const doc = mutate(SURVEY, r);
			const out = validate(doc);
			expect(Array.isArray(out)).toBe(true);
			for (const d of out) expect(d.code).not.toBe('internal.error');
		}
	});

	it('on top-level oddities, getters that throw and cycles', () => {
		for (const v of ODD) expect(validate(v)[0]?.code).toBe('schema.type');
		const throwing = { ...SURVEY };
		Object.defineProperty(throwing, 'blocks', {
			enumerable: true,
			get() {
				throw new Error('boom');
			}
		});
		expect(validate(throwing).map((d) => d.code)).toEqual(['internal.error']);
		const cyclic: Record<string, unknown> = { ...SURVEY, metadata: { title: 'T', languages: ['en'] } };
		(cyclic.metadata as Record<string, unknown>).ddi = { self: cyclic };
		expect(() => validate(cyclic)).not.toThrow();
	});

	it('accepts the plain survey', () => {
		expect(validate(SURVEY)).toEqual([]);
	});
});

describe('documented differences from Python', () => {
	it('integral numbers are ints: JSON 1.0 cannot be told from 1', () => {
		expect(validate({ ...SURVEY, version: 1.0 })).toEqual([]);
	});

	it('patterns JavaScript cannot express are refused (Python accepts them)', () => {
		expect(compileFull('\\N{DIGIT ONE}')).toBeNull();
		expect(compileFull('(a)(?(1)a|b)')).toBeNull();
		expect(compileFull('(?x:a b)')).not.toBeNull(); // verbose mode is translated
	});

	it('variable-width look-behind is accepted (Python refuses it)', () => {
		expect(compileFull('(?<=a+)b')).not.toBeNull();
	});
});
