/**
 * Deterministic randomness: an exact port of `python/osp-engine/src/osp_engine/random.py`
 * (semantics.md §7). Pure functions of their arguments; never `Math.random`.
 *
 * - `randomize` is ODK XForms `randomize(nodeset, seed)` as in Enketo
 *   (openrosa-xpath-evaluator 3.2.0): Park–Miller (M = 2^31 − 1, A = 16807), seed reduced
 *   with a truncating remainder, inside-out Fisher–Yates with one draw per element.
 * - `nodeSeed` derives one seed per random decision from
 *   SHA-256(ns("osp-node-seed/1") + ns(surveyVersion) + ns(str(sessionSeed)) + ns(nodeId)).
 * - `assign` picks one condition with probability proportional to its weight, with one
 *   Park–Miller draw and exact rational comparison.
 *
 * Parity with Python is tested on 10,000 seeds plus shared hash vectors (test/parity.test.ts).
 */

import { sha256, utf8, Utf8Error } from './sha256.ts';

const M = 2147483647; // 2^31 − 1
const A = 16807;

/** Largest accepted seed (Number.MAX_SAFE_INTEGER). */
export const MAX_SEED = Number.MAX_SAFE_INTEGER;
/** Largest value nodeSeed returns (2^31 − 2). */
export const NODE_SEED_MAX = M - 1;
export const NODE_SEED_TAG = 'osp-node-seed/1';

/** Bad input to a function in this module. `code` matches the Python codes. */
export class RandomInputError extends Error {
	constructor(
		readonly code: string,
		message: string
	) {
		super(message);
	}
}

export class InvalidSeedError extends RandomInputError {}

/** Return `seed` if it is a valid seed (integer, 1 … 2^53 − 1), else throw. */
export function checkSeed(seed: unknown): number {
	if (typeof seed !== 'number' || !Number.isInteger(seed)) {
		throw new InvalidSeedError('seed.not_integer', `seed must be an integer`);
	}
	if (seed < 1) throw new InvalidSeedError('seed.not_positive', `seed must be >= 1, got ${seed}`);
	if (seed > MAX_SEED) {
		throw new InvalidSeedError('seed.too_large', `seed must be <= 2**53 - 1, got ${seed}`);
	}
	return seed;
}

class ParkMiller {
	state: number;
	constructor(seed: number) {
		// JS `%` truncates toward zero (sign of the dividend), exactly Enketo's reduction.
		let s = seed % M;
		if (s <= 0) s += M - 1;
		this.state = s;
	}
	nextState(): number {
		// state < 2^31 and A < 2^15, so the product is exact in a double.
		this.state = (this.state * A) % M;
		return this.state;
	}
	nextFloat(): number {
		return (this.nextState() - 1) / (M - 1);
	}
}

/** The raw algorithm for any integer seed (Enketo semantics incl. 0 and negatives). */
export function permuteRaw<T>(items: readonly T[], seed: number): T[] {
	const rng = new ParkMiller(seed);
	const out: T[] = [];
	for (let i = 0; i < items.length; i++) {
		const x = items[i] as T;
		const j = Math.floor(rng.nextFloat() * (i + 1));
		if (j === i) out.push(x);
		else {
			out.push(out[j] as T);
			out[j] = x;
		}
	}
	return out;
}

/** ODK XForms `randomize(nodeset, seed)`: a new array, `items` untouched. */
export function randomize<T>(items: readonly T[], seed: unknown): T[] {
	return permuteRaw(items, checkSeed(seed));
}

function netstring(s: unknown, what: string): Uint8Array {
	if (typeof s !== 'string') throw new RandomInputError(`${what}.not_string`, `${what} must be a str`);
	let b: Uint8Array;
	try {
		b = utf8(s);
	} catch (e) {
		if (e instanceof Utf8Error) {
			throw new RandomInputError(`${what}.not_utf8`, `${what} is not valid UTF-8 text`);
		}
		throw e;
	}
	const head = utf8(`${b.length}:`);
	const out = new Uint8Array(head.length + b.length + 1);
	out.set(head);
	out.set(b, head.length);
	out[out.length - 1] = 0x2c; // ","
	return out;
}

/** The seed for one random decision (`nodeId`) in one session: 1 … 2^31 − 2. */
export function nodeSeed(surveyVersion: string, sessionSeed: number, nodeId: string): number {
	const session = checkSeed(sessionSeed);
	const parts = [
		netstring(NODE_SEED_TAG, 'tag'),
		netstring(surveyVersion, 'survey_version'),
		netstring(String(session), 'session_seed'),
		netstring(nodeId, 'node_id')
	];
	const msg = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
	let off = 0;
	for (const p of parts) {
		msg.set(p, off);
		off += p.length;
	}
	const h = sha256(msg);
	let x = 0n;
	for (let i = 0; i < 8; i++) x = (x << 8n) | BigInt(h[i]!);
	return Number(x % BigInt(M - 1)) + 1;
}

/**
 * Pick one condition with probability `weights[k] / sum(weights)` (equal when `weights` is
 * null). Weights are non-negative integers here (the engine only uses equal weights); the
 * Python version also takes floats, which the server uses.
 */
export function assign<T>(conditions: readonly T[], weights: readonly number[] | null, seed: unknown): T {
	const s = checkSeed(seed);
	if (conditions.length === 0) {
		throw new RandomInputError('conditions.empty', 'conditions must not be empty');
	}
	const ws = weights ?? conditions.map(() => 1);
	if (ws.length !== conditions.length) {
		throw new RandomInputError('weights.length', `${ws.length} weights for ${conditions.length} conditions`);
	}
	const big = ws.map((w, i) => {
		if (!Number.isSafeInteger(w)) {
			throw new RandomInputError('weights.not_number', `weight ${i} must be an integer here`);
		}
		if (w < 0) throw new RandomInputError('weights.negative', `weight ${i} must be >= 0`);
		return BigInt(w);
	});
	const total = big.reduce((a, b) => a + b, 0n);
	if (total === 0n) throw new RandomInputError('weights.all_zero', 'at least one weight must be > 0');
	const r = BigInt(new ParkMiller(s).nextState() - 1);
	let cumulative = 0n;
	for (let k = 0; k < conditions.length; k++) {
		const w = big[k]!;
		cumulative += w;
		if (w > 0n && r * total < cumulative * BigInt(M - 1)) return conditions[k] as T;
	}
	throw new Error('unreachable: r < M - 1 and cumulative reaches total');
}
