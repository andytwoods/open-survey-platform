/**
 * Expected-trace comparison (fixtures/FORMAT.md §3), the same rules as the engine runner
 * (web/engine/test/fixture-runner.ts): `"<engine>"` and `"<pending:…>"` placeholders match
 * anything and are recorded; invariants are checked on the expected file with the
 * placeholders filled from what the app did.
 */

export interface Diff {
	path: string;
	expected: unknown;
	actual: unknown;
}

export interface Realised {
	path: string;
	placeholder: string;
	actual: unknown;
}

export function isPlaceholder(x: unknown): x is string {
	return typeof x === 'string' && (x === '<engine>' || x.startsWith('<pending:'));
}

/** `multi` values compare as sets (FORMAT.md §3 Values). */
function sameSet(a: unknown[], b: unknown[]): boolean {
	if (a.length !== b.length) return false;
	const key = (x: unknown) => JSON.stringify(x);
	const sa = a.map(key).sort();
	const sb = b.map(key).sort();
	return sa.every((x, i) => x === sb[i]);
}

/** Compare; placeholders match anything and are recorded. Returns `expected` with them filled. */
export function compare(expected: unknown, actual: unknown, path: string, diffs: Diff[], realised: Realised[]): unknown {
	if (isPlaceholder(expected)) {
		realised.push({ path, placeholder: expected, actual });
		return actual;
	}
	if (Array.isArray(expected)) {
		if (!Array.isArray(actual) || actual.length !== expected.length) {
			diffs.push({ path, expected, actual });
			return expected;
		}
		// A question's multi value: same codes in any order.
		if (/\.(questions|answers)\.[^.]+\.value$/.test(path) && !expected.some(isPlaceholder)) {
			if (!sameSet(expected, actual)) diffs.push({ path, expected, actual });
			return expected;
		}
		return expected.map((e, i) => compare(e, actual[i], `${path}[${i}]`, diffs, realised));
	}
	if (expected !== null && typeof expected === 'object') {
		if (actual === null || typeof actual !== 'object' || Array.isArray(actual)) {
			diffs.push({ path, expected, actual });
			return expected;
		}
		const a = actual as Record<string, unknown>;
		const e = expected as Record<string, unknown>;
		const out: Record<string, unknown> = {};
		for (const k of new Set([...Object.keys(e), ...Object.keys(a)])) {
			if (!(k in e)) {
				diffs.push({ path: `${path}.${k}`, expected: undefined, actual: a[k] });
				continue;
			}
			if (!(k in a)) {
				diffs.push({ path: `${path}.${k}`, expected: e[k], actual: undefined });
				continue;
			}
			out[k] = compare(e[k], a[k], `${path}.${k}`, diffs, realised);
		}
		return out;
	}
	if (expected !== actual) diffs.push({ path, expected, actual });
	return expected;
}

export function getPath(root: unknown, path: string): unknown {
	const parts = path.match(/[^.[\]]+/g) ?? [];
	let cur: unknown = root;
	for (const p of parts) {
		if (cur === null || typeof cur !== 'object') return undefined;
		cur = /^\d+$/.test(p) && Array.isArray(cur) ? cur[Number(p)] : (cur as Record<string, unknown>)[p];
	}
	return cur;
}

export type Invariant = { kind: 'permutation'; of: unknown[]; paths: string[] } | { kind: 'equal'; paths: string[] };

export function checkInvariant(inv: Invariant, root: unknown): string | null {
	const vals = inv.paths.map((p) => getPath(root, p));
	if (inv.kind === 'permutation') {
		const want = JSON.stringify([...inv.of].map(String).sort());
		for (let i = 0; i < vals.length; i++) {
			const v = vals[i];
			if (!Array.isArray(v) || JSON.stringify(v.map(String).sort()) !== want) {
				return `${inv.paths[i]} = ${JSON.stringify(v)} is not a permutation of ${JSON.stringify(inv.of)}`;
			}
		}
		return null;
	}
	const first = JSON.stringify(vals[0]);
	for (let i = 1; i < vals.length; i++) {
		if (JSON.stringify(vals[i]) !== first) {
			return `${inv.paths[i]} = ${JSON.stringify(vals[i])} differs from ${inv.paths[0]} = ${first}`;
		}
	}
	return vals[0] === undefined ? `${inv.paths[0]} is undefined` : null;
}

/** Restrict `actual` to the keys an expected object uses at the top level (step/response). */
export function pick(actual: Record<string, unknown>, expected: Record<string, unknown>) {
	const out: Record<string, unknown> = {};
	for (const k of Object.keys(expected)) out[k] = actual[k];
	// `builtins` names only the built-ins a script asserts (e.g. `trial` without `position`).
	const eb = expected.builtins;
	const ab = out.builtins;
	if (eb && typeof eb === 'object' && ab && typeof ab === 'object') {
		out.builtins = pick(ab as Record<string, unknown>, eb as Record<string, unknown>);
	}
	return out;
}
