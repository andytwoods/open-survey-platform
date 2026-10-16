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
	restart,
	restore,
	result,
	snapshot,
	start,
	toHtml,
	tryAnswer,
	view,
	isState,
	replay,
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
	server?: Server;
	/** "blocked": no IndexedDB. The engine has no storage, so this only matters to R3/R4. */
	storage?: string;
	replay?: { server?: Server };
	actions: Array<{
		expectPage?: string;
		set?: Record<string, unknown>;
		setIfShown?: Record<string, unknown>;
		do: 'next' | 'back' | 'refresh' | 'resume' | 'retry' | 'switchDevice';
		device?: string;
		restoreFrom?: 'local';
	}>;
}

interface Server {
	conditions?: Record<string, string | number>;
	quotas?: Record<string, string>;
	/** Per quotaCheck node: what happens to the 1st, 2nd … call. */
	quotaCalls?: Record<string, Array<'timeout' | 'lostReply' | 'ok'>>;
}

export interface Meta {
	fixture?: string;
	diagnostics?: unknown[];
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

/**
 * Traces name blocks (fixtures/FORMAT.md §1: one block, one page `<block>_page`): a step's
 * `page`, `orders.items` keys and randomiser children are block ids. The engine works in
 * pages and flow nodes, so translate through the plan.
 */
function blockOfPage(plan: Plan, page: string | null): string | null {
	return page === null ? null : (plan.pages[page]?.block ?? page);
}

function blockOfNode(plan: Plan, nodeId: string): string {
	const find = (ns: Plan['flow']): string | undefined => {
		for (const n of ns) {
			if (n.id === nodeId) return n.type === 'block' ? n.block : n.id;
			const sub = n.type === 'branch' ? [...n.then, ...n.else] : n.type === 'randomiser' ? n.children : [];
			const hit = find(sub);
			if (hit) return hit;
		}
		return undefined;
	};
	return find(plan.flow) ?? nodeId;
}

function renameOrders(plan: Plan, orders: ReturnType<typeof result>['orders']) {
	const blocks: Record<string, string[]> = {};
	for (const [k, v] of Object.entries(orders.blocks)) blocks[k] = v.map((id) => blockOfNode(plan, id));
	const items: Record<string, string[]> = {};
	for (const [k, v] of Object.entries(orders.items)) items[blockOfPage(plan, k) ?? k] = v;
	return { blocks, items, choices: orders.choices };
}

export function trace(state: State, index: number, device = 'A', notice: string | null = null) {
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
		page: blockOfPage(state.plan, v.page),
		visible: v.items.map((i) => i.id),
		errors,
		nav: v.nav ? { back: v.nav.back } : null,
		questions: answers(state),
		orders: renameOrders(state.plan, r.orders),
		conditions: r.conditions,
		end: r.end,
		labels,
		choiceLabels,
		effect: v.status === 'pending' && v.effect?.kind === 'quota' ? { kind: 'quota', nodeId: v.effect.nodeId } : null,
		device,
		builtins: v.status === 'ended' ? null : { trial: v.trial, position: v.position },
		notice
	};
}

export function responseOf(state: State) {
	const r = result(state);
	return { ...r, orders: renameOrders(state.plan, r.orders) };
}

/** Run a script. Throws on a script that cannot be played (wrong page, hidden item). */
export function play(plan: Plan, script: Script) {
	let t = 1_000;
	const clock = () => (t += 1_000);
	let state = start(plan, {
		sessionSeed: script.sessionSeed,
		assigned: script.server?.conditions,
		clock,
		language: script.language
	});
	// Simulated server and devices (FORMAT.md §2 script extensions).
	let device = 'A';
	const local: Record<string, State> = {};
	let serverCopy: State = state;
	const recorded: Record<string, string> = {};
	const calls: Record<string, number> = {};
	/** Send one quota call; returns the state after the reply (unchanged if it was lost). */
	const send = (s: State): State => {
		const effect = view(s).effect;
		if (view(s).status !== 'pending' || effect?.kind !== 'quota') return s;
		const k = (calls[effect.nodeId] = (calls[effect.nodeId] ?? 0) + 1);
		const fate = script.server?.quotaCalls?.[effect.nodeId]?.[k - 1] ?? 'ok';
		if (fate === 'timeout') return s;
		recorded[effect.nodeId] ??= script.server?.quotas?.[effect.quota] ?? 'open';
		if (fate === 'lostReply') return s;
		return resolveEffect(s, effect, recorded[effect.nodeId]);
	};
	/** Send until an effect stays pending (lost reply) or none is left. */
	const settle = (s: State): State => {
		for (let guard = 0; guard < 100 && view(s).status === 'pending'; guard++) {
			const after = send(s);
			if (after === s || view(after).status === 'pending' && after.data.pending?.effect.nodeId === s.data.pending?.effect.nodeId) {
				return after;
			}
			s = after;
		}
		return s;
	};
	const steps = [trace(state, 0, device)];
	// semantics §5 (R6-5): an end-only session whose copy is only in memory (localCopy
	// memory, or browser storage blocked) restarts on refresh or resume.
	const memoryOnly =
		plan.settings.saveMode === 'end-only' && (plan.settings.localCopy === 'memory' || script.storage === 'blocked');
	// semantics §5 (R6-6): the server revision each device last saw; a device whose save is
	// stale (another device moved on) shows the server copy instead, with a notice.
	const seen: Record<string, number> = { A: state.data.revision };
	script.actions.forEach((action, i) => {
		let notice: string | null = null;
		const v = view(state);
		const shown = blockOfPage(plan, v.page);
		if (action.expectPage !== undefined && shown !== action.expectPage) {
			throw new Error(`action ${i}: expected page ${action.expectPage}, engine shows ${shown}`);
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
				// `next` sends the first call itself; only `retry` sends again.
				const pendingBefore = view(state).status === 'pending';
				state = next(state).state;
				if (!pendingBefore) state = settle(state);
				break;
			}
			case 'retry':
				state = settle(state);
				break;
			case 'back':
				state = back(state);
				break;
			case 'refresh':
			case 'resume':
				if (memoryOnly) {
					state = restart(state, { clock });
					notice = 'restarted';
					break;
				}
				state = reload(plan, state, clock, i);
				// semantics §5 (R6-4): a reload re-sends a pending call (same idempotency key).
				if (view(state).status === 'pending') state = settle(state);
				break;
			case 'switchDevice': {
				// every-page saves on every change, so the server holds this device's answers too.
				serverCopy = state;
				local[device] = state;
				seen[device] = serverCopy.data.revision;
				device = action.device ?? (device === 'A' ? 'B' : 'A');
				const revived = local[device];
				state = action.restoreFrom === 'local' && revived ? revived : reload(plan, serverCopy, clock, i);
				if (!(action.restoreFrom === 'local' && revived)) seen[device] = serverCopy.data.revision;
				local[device] = state;
				const switched = trace(state, i + 1, device, notice);
				switched.errors = {};
				steps.push(switched);
				return;
			}
		}
		if (action.do !== 'refresh' && action.do !== 'resume' && seen[device] !== undefined && seen[device] !== serverCopy.data.revision) {
			// Stale: the save is refused (409); the server copy wins and this device shows it.
			state = reload(plan, serverCopy, clock, i);
			notice = 'conflict';
		} else {
			serverCopy = state;
		}
		seen[device] = serverCopy.data.revision;
		local[device] = state;
		const step = trace(state, i + 1, device, notice);
		// FORMAT.md §3: `errors` only ever comes from a `next` in that step's action. The
		// engine keeps the last errors in the state (restore is exact); a reloaded page shows
		// none, which is the runtime's choice (R3), so the trace reports none.
		if (action.do !== 'next') step.errors = {};
		steps.push(step);
	});
	return { state, steps, response: responseOf(state) };
}

function reload(plan: Plan, state: State, clock: () => number, i: number): State {
	const snap = JSON.parse(JSON.stringify(snapshot(state)));
	const r = restore(plan, snap, { clock });
	if (!isState(r)) throw new Error(`action ${i}: restore failed: ${r.error.code}`);
	return r;
}

/** FORMAT.md `replay`: the event log alone, through a fresh engine, gives the same response. */
export function replayResponse(plan: Plan, state: State) {
	const r = replay(plan, state.data.events);
	if (!isState(r)) return { error: r.error };
	return { response: responseOf(r) };
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
	// `builtins` names only the built-ins a script asserts (e.g. `trial` without `position`).
	const eb = expected.builtins;
	const ab = out.builtins;
	if (eb && typeof eb === 'object' && ab && typeof ab === 'object') {
		out.builtins = pick(ab as Record<string, unknown>, eb as Record<string, unknown>);
	}
	return out;
}
