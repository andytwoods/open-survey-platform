/**
 * Plays a fixture script (fixtures/FORMAT.md §2) through the engine and builds the trace
 * (FORMAT.md §3) the expected file is compared with.
 */

import { readFileSync, existsSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import {
	answers,
	back,
	next,
	resolve as resolveEffect,
	restore,
	result,
	snapshot,
	start,
	toHtml,
	tryAnswer,
	view,
	isState,
	type Plan,
	type State
} from '../src/index.ts';

export const REPO = resolve(import.meta.dirname, '../../..');
export const FIXTURES = join(REPO, 'fixtures');
export const BUILD = join(REPO, 'web/engine/.build');

export interface Script {
	id: string;
	sessionSeed: number;
	language: string;
	server?: { conditions?: Record<string, string | number>; quotas?: Record<string, string> };
	actions: Array<{
		expectPage?: string;
		set?: Record<string, unknown>;
		setIfShown?: Record<string, unknown>;
		do: 'next' | 'back' | 'refresh' | 'resume';
	}>;
}

export interface Meta {
	idmap?: { nodes: Record<string, string> };
}

export function loadJson<T>(path: string): T {
	return JSON.parse(readFileSync(path, 'utf8')) as T;
}

export function fixtureNames(): string[] {
	return readdirSync(FIXTURES)
		.filter((n) => existsSync(join(FIXTURES, n, 'survey.json')))
		.sort();
}

export function loadPlan(name: string): { plan: Plan | null; error?: string; meta: Meta } {
	const path = join(BUILD, 'fixtures', `${name}.plan.json`);
	if (!existsSync(path)) {
		throw new Error(`${path} is missing: run \`make engine-test\` (it builds the plans first)`);
	}
	const raw = loadJson<Plan & { error?: string }>(path);
	const meta = loadJson<Meta>(join(BUILD, 'fixtures', `${name}.meta.json`));
	if (raw.error) return { plan: null, error: raw.error, meta };
	return { plan: raw, meta };
}

function renameOrders(orders: ReturnType<typeof result>['orders'], meta: Meta) {
	const nodes = meta.idmap?.nodes ?? {};
	const blocks: Record<string, string[]> = {};
	for (const [k, v] of Object.entries(orders.blocks)) blocks[k] = v.map((id) => nodes[id] ?? id);
	return { blocks, items: orders.items, choices: orders.choices };
}

export function trace(state: State, index: number, meta: Meta) {
	const v = view(state);
	const r = result(state);
	const errors: Record<string, unknown> = {};
	for (const [id, e] of Object.entries(v.errors)) {
		if (e.kind === 'constraint') errors[id] = { kind: 'constraint', message: e.message ? toHtml(e.message) : null };
		else if (e.kind === 'invalid') errors[id] = { kind: 'invalid', code: e.code };
		else errors[id] = { kind: e.kind };
	}
	const labels: Record<string, string> = {};
	const choiceLabels: Record<string, Array<[unknown, string]>> = {};
	for (const it of v.items) {
		labels[it.id] = toHtml(it.label);
		if (it.choices) choiceLabels[it.id] = it.choices.map((c) => [c.value, toHtml(c.label)]);
	}
	return {
		index,
		page: v.page,
		visible: v.items.map((i) => i.id),
		errors,
		nav: v.nav ? { back: v.nav.back } : null,
		questions: answers(state),
		orders: renameOrders(r.orders, meta),
		conditions: r.conditions,
		end: r.end,
		labels,
		choiceLabels
	};
}

export function responseOf(state: State, meta: Meta) {
	const r = result(state);
	return { ...r, orders: renameOrders(r.orders, meta) };
}

/** Run a script. Throws on a script that cannot be played (wrong page, hidden item). */
export function play(plan: Plan, script: Script, meta: Meta) {
	let t = 1_000;
	const clock = () => (t += 1_000);
	let state = start(plan, {
		sessionSeed: script.sessionSeed,
		assigned: script.server?.conditions,
		clock,
		language: script.language
	});
	const steps = [trace(state, 0, meta)];
	script.actions.forEach((action, i) => {
		const v = view(state);
		if (action.expectPage !== undefined && v.page !== action.expectPage) {
			throw new Error(`action ${i}: expected page ${action.expectPage}, engine shows ${v.page}`);
		}
		const visible = new Set(v.items.map((it) => it.id));
		for (const [id, value] of Object.entries(action.set ?? {})) {
			const r = tryAnswer(state, id, value);
			if (r.rejected) throw new Error(`action ${i}: set ${id} refused (${r.rejected})`);
			state = r.state;
		}
		for (const [id, value] of Object.entries(action.setIfShown ?? {})) {
			if (visible.has(id)) state = tryAnswer(state, id, value).state;
		}
		switch (action.do) {
			case 'next': {
				let out = next(state);
				state = out.state;
				for (let guard = 0; out.effect?.kind === 'quota' && guard < 100; guard++) {
					const quota = out.effect.quota;
					const res = script.server?.quotas?.[quota] ?? 'open';
					state = resolveEffect(state, out.effect, res);
					out = next(state);
					state = out.state;
				}
				break;
			}
			case 'back':
				state = back(state);
				break;
			case 'refresh':
			case 'resume': {
				const snap = JSON.parse(JSON.stringify(snapshot(state)));
				const r = restore(plan, snap, { clock });
				if (!isState(r)) throw new Error(`action ${i}: restore failed: ${r.error.code}`);
				state = r;
				break;
			}
		}
		steps.push(trace(state, i + 1, meta));
	});
	return { state, steps, response: responseOf(state, meta) };
}

// --- Comparison with "<engine>" and "<pending:…>" placeholders ---------------------------

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

function isPlaceholder(x: unknown): x is string {
	return typeof x === 'string' && (x === '<engine>' || x.startsWith('<pending:'));
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
	return out;
}
