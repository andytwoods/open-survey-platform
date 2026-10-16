/**
 * Canonical JSON and the plan checksum, matching `osp_runtime.plan.canonical_json`
 * (`json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`).
 */

import type { Plan } from './plan.ts';
import { sha256, toHex, utf8 } from './sha256.ts';

/** Python sorts keys by code point; JS `sort()` compares UTF-16 units. */
function byCodePoint(a: string, b: string): number {
	const x = Array.from(a);
	const y = Array.from(b);
	for (let i = 0; i < Math.min(x.length, y.length); i++) {
		const d = x[i]!.codePointAt(0)! - y[i]!.codePointAt(0)!;
		if (d !== 0) return d;
	}
	return x.length - y.length;
}

export function canonicalJson(value: unknown): string {
	if (value === null || typeof value !== 'object') {
		if (typeof value === 'number' && !Number.isFinite(value)) {
			throw new TypeError('non-finite number');
		}
		return JSON.stringify(value);
	}
	if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
	const obj = value as Record<string, unknown>;
	const keys = Object.keys(obj)
		.filter((k) => obj[k] !== undefined)
		.sort(byCodePoint);
	return `{${keys.map((k) => `${JSON.stringify(k)}:${canonicalJson(obj[k])}`).join(',')}}`;
}

/** `sha256:<hex>` over the canonical JSON of `plan` without its `checksum`. */
export function planChecksum(plan: Plan | Record<string, unknown>): string {
	const body: Record<string, unknown> = { ...(plan as Record<string, unknown>) };
	delete body.checksum;
	return `sha256:${toHex(sha256(utf8(canonicalJson(body))))}`;
}
