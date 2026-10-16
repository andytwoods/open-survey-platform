/**
 * Python ⇄ TS parity for the randomness port (runtime-design.md §8 gate 4):
 * - shared vectors (committed, test/vectors/shared.json): SHA-256, node_seed, randomize,
 *   assign and error codes at the edges;
 * - 10,000 seeds (.build/parity.json, from osp_engine.random by `make engine-fixtures`);
 * - the Enketo spike evidence (python/osp-engine/tests/data, 900 integer seeds × 4 sizes).
 */

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { assign, nodeSeed, permuteRaw, randomize, RandomInputError, sha256, toHex, utf8 } from '../src/index.ts';
import { BUILD, REPO } from './fixture-runner.ts';

interface Shared {
	sha256: Array<[string, string]>;
	nodeSeed: Array<[string, number, string, number]>;
	randomize: Array<[number, number, number[]]>;
	assign: Array<[number, number, number[] | null, number]>;
	badSeeds: Array<[string, { error: string }]>;
	badNodeSeed: Array<{ error: string }>;
}

const SHARED_PATH = join(import.meta.dirname, 'vectors', 'shared.json');
const shared = JSON.parse(readFileSync(SHARED_PATH, 'utf8')) as Shared;

function code(fn: () => unknown): string | undefined {
	try {
		fn();
		return undefined;
	} catch (e) {
		return e instanceof RandomInputError ? e.code : `other: ${String(e)}`;
	}
}

describe('shared vectors', () => {
	it('are current with the Python implementation', () => {
		const fresh = join(BUILD, 'shared.json');
		expect(existsSync(fresh), 'run make engine-fixtures').toBe(true);
		expect(JSON.parse(readFileSync(fresh, 'utf8'))).toEqual(shared);
	});

	it('SHA-256 matches hashlib', () => {
		for (const [text, hex] of shared.sha256) expect(toHex(sha256(utf8(text)))).toBe(hex);
		// FIPS 180-4 examples, including a two-block message.
		expect(toHex(sha256(utf8('abc')))).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
		expect(toHex(sha256(utf8('abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq')))).toBe(
			'248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1'
		);
		expect(toHex(sha256(utf8('a'.repeat(1_000_000))))).toBe(
			'cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0'
		);
	});

	it(`node_seed matches on ${shared.nodeSeed.length} cases`, () => {
		const bad = shared.nodeSeed.filter(([v, s, n, want]) => nodeSeed(v, s, n) !== want);
		expect(bad).toEqual([]);
	});

	it(`randomize matches on ${shared.randomize.length} cases, incl. 0 and negative seeds`, () => {
		const range = (n: number) => Array.from({ length: n }, (_, i) => i);
		const bad = shared.randomize.filter(([s, n, want]) => JSON.stringify(permuteRaw(range(n), s)) !== JSON.stringify(want));
		expect(bad).toEqual([]);
	});

	it('assign matches', () => {
		const bad = shared.assign.filter(([s, k, w, want]) => assign(Array.from({ length: k }, (_, i) => i), w, s) !== want);
		expect(bad).toEqual([]);
	});

	it('rejects the same seeds and node ids with the same codes', () => {
		const seeds: Record<string, unknown> = { '0': 0, '-1': -1, '9007199254740992': 2 ** 53, '1.5': 1.5 };
		for (const [s, want] of shared.badSeeds) expect(code(() => randomize([1], seeds[s]))).toBe(want.error);
		expect(code(() => nodeSeed('1', 1, '\udfff'))).toBe(shared.badNodeSeed[0]!.error);
		expect(code(() => nodeSeed('\ud800', 1, 'q'))).toBe(shared.badNodeSeed[1]!.error);
	});
});

describe('10,000 seeds', () => {
	const path = join(BUILD, 'parity.json');
	it('node_seed and randomize equal Python for every seed', () => {
		expect(existsSync(path), 'run make engine-fixtures').toBe(true);
		const rows = (JSON.parse(readFileSync(path, 'utf8')) as {
			rows: Array<[number, string, string, number, number[], number[]]>;
		}).rows;
		expect(rows.length).toBe(10_000);
		let mismatches = 0;
		for (const [seed, version, node, ns, permSeed, permNs] of rows) {
			const range = Array.from({ length: permSeed.length }, (_, i) => i);
			if (nodeSeed(version, seed, node) !== ns) mismatches++;
			else if (JSON.stringify(randomize(range, seed)) !== JSON.stringify(permSeed)) mismatches++;
			else if (JSON.stringify(randomize(range, ns)) !== JSON.stringify(permNs)) mismatches++;
		}
		expect(mismatches).toBe(0);
	});
});

describe('Enketo evidence (spike E5)', () => {
	it('permuteRaw equals Enketo randomize() on all 3,600 integer-seed rows', () => {
		const data = JSON.parse(
			readFileSync(join(REPO, 'python/osp-engine/tests/data/e5_enketo_integer_seeds.json'), 'utf8')
		) as { rows: Array<[string, number, number, number[]]> };
		expect(data.rows.length).toBe(3600);
		const bad = data.rows.filter(
			([, seed, n, order]) => JSON.stringify(permuteRaw(Array.from({ length: n }, (_, i) => i), seed)) !== JSON.stringify(order)
		);
		expect(bad).toEqual([]);
	});
});
