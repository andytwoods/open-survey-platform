/**
 * A small seeded PRNG (mulberry32) for the simulator's own choices: which answer a
 * simulated participant gives and which session seed it gets. Never Math.random, so a run
 * is a pure function of its seed. Not the engine's randomisation (that is node_seed).
 */

export interface Rng {
	/** Uniform in [0, 1). */
	(): number;
	int(lo: number, hi: number): number;
	pick<T>(xs: readonly T[]): T;
	/** A session seed: an integer in 1 … 2^53 − 1. */
	seed(): number;
}

export function rng(seed: number): Rng {
	let a = (Math.floor(Math.abs(seed)) ^ 0x9e3779b9) >>> 0;
	const u32 = () => {
		a = (a + 0x6d2b79f5) >>> 0;
		let t = a;
		t = Math.imul(t ^ (t >>> 15), t | 1);
		t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
		return (t ^ (t >>> 14)) >>> 0;
	};
	// Mix the high bits of large seeds in too.
	for (let i = 0, hi = Math.floor(Math.abs(seed) / 2 ** 32); i < 2; i++) {
		a = (a ^ (hi >>> 0)) >>> 0;
		u32();
	}
	const r = (() => u32() / 2 ** 32) as Rng;
	r.int = (lo, hi) => lo + Math.floor(r() * (hi - lo + 1));
	r.pick = (xs) => xs[Math.floor(r() * xs.length)]!;
	r.seed = () => {
		const s = (u32() & 0x1fffff) * 2 ** 32 + u32();
		return s === 0 ? 1 : s;
	};
	return r;
}
