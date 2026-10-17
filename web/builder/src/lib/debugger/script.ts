/**
 * Fixture-style answer scripts in the debugger (fixtures/FORMAT.md §2, `osp-fixture-script/0`):
 * play one through the TS engine step by step, describe each step as a trace step
 * (FORMAT.md §3), compare it with an expected file, and turn a run back into a script.
 *
 * No survey logic here: every decision is the engine's (`@osp/engine`). This file only
 * feeds it a script's actions and reads the results, as `web/engine/test/fixture-runner.ts`
 * does for the fixture tests. The runtime-layer extensions (`switchDevice`, `retry`,
 * quota call fates, storage) are played the simple way: a device switch or a reload
 * restores the engine snapshot, and a pending quota check is answered at once.
 */
import {
	answers,
	back,
	isState,
	next,
	resolve,
	restore,
	result,
	snapshot,
	start,
	toHtml,
	tryAnswer,
	tryConsent,
	view,
	type EngineEvent,
	type Plan,
	type State
} from '@osp/engine';

export type ScriptAction = {
	expectPage?: string;
	set?: Record<string, unknown>;
	setIfShown?: Record<string, unknown>;
	do: 'next' | 'back' | 'refresh' | 'resume' | 'retry' | 'switchDevice' | 'agree' | 'decline' | 'withdraw';
	device?: string;
};

export interface Script {
	format?: string;
	id?: string;
	description?: string;
	sessionSeed: number;
	language?: string;
	server?: {
		conditions?: Record<string, string | number>;
		quotas?: Record<string, 'open' | 'full'>;
	};
	actions: ScriptAction[];
}

export const SCRIPT_FORMAT = 'osp-fixture-script/0';

/** Parse script JSON text. Returns a message instead of throwing (AGENTS.md rule 3). */
export function parseScript(text: string): { script: Script } | { error: string } {
	let raw: unknown;
	try {
		raw = JSON.parse(text);
	} catch (e) {
		return { error: `Not JSON: ${(e as Error).message}` };
	}
	if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { error: 'A script is a JSON object.' };
	const s = raw as Record<string, unknown>;
	if (s.format !== undefined && s.format !== SCRIPT_FORMAT) return { error: `Unknown format ${String(s.format)}.` };
	const seed = s.sessionSeed;
	if (typeof seed !== 'number' || !Number.isSafeInteger(seed) || seed < 1) {
		return { error: 'sessionSeed must be a positive whole number.' };
	}
	if (!Array.isArray(s.actions)) return { error: 'actions must be a list.' };
	const DOS = new Set(['next', 'back', 'refresh', 'resume', 'retry', 'switchDevice', 'agree', 'decline', 'withdraw']);
	for (const [i, a] of s.actions.entries()) {
		if (!a || typeof a !== 'object' || !DOS.has((a as { do?: unknown }).do as string)) {
			return { error: `Action ${i + 1}: "do" must be one of ${[...DOS].join(', ')}.` };
		}
	}
	return { script: raw as Script };
}

/** The block a page belongs to (fixture traces name blocks: FORMAT.md §1). */
export function blockOfPage(plan: Plan, page: string | null): string | null {
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

/** Realised orders with fixture names: randomiser children and page orders by block. */
export function traceOrders(state: State) {
	const plan = state.plan;
	const o = result(state).orders;
	const blocks: Record<string, string[]> = {};
	for (const [k, v] of Object.entries(o.blocks)) blocks[k] = v.map((id) => blockOfNode(plan, id));
	const items: Record<string, string[]> = {};
	for (const [k, v] of Object.entries(o.items)) items[blockOfPage(plan, k) ?? k] = v;
	return { blocks, items, choices: o.choices };
}

export type TraceStep = ReturnType<typeof traceStep>;

/** One trace step (FORMAT.md §3) for the state now. */
export function traceStep(state: State, index: number, afterNext = true) {
	const v = view(state);
	const r = result(state);
	const errors: Record<string, unknown> = {};
	if (afterNext) {
		for (const [id, e] of Object.entries(v.errors)) {
			if (e.kind === 'constraint') errors[id] = { kind: 'constraint', message: e.message ? toHtml(e.message) : null };
			else if (e.kind === 'invalid') errors[id] = { kind: 'invalid', code: e.code };
			else errors[id] = { kind: e.kind };
		}
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
		orders: traceOrders(state),
		conditions: r.conditions,
		end: r.end,
		labels,
		choiceLabels,
		effect: v.status === 'pending' && v.effect?.kind === 'quota' ? { kind: 'quota', nodeId: v.effect.nodeId } : null,
		builtins: v.status === 'ended' ? null : { trial: v.trial, position: v.position }
	};
}

/** Clock for debugger runs: deterministic, so a replayed script gives the same event log. */
export function stepClock(): () => number {
	let t = 1_000;
	return () => (t += 1_000);
}

export function startState(plan: Plan, script: Pick<Script, 'sessionSeed' | 'language' | 'server'>, clock = stepClock()) {
	return start(plan, {
		sessionSeed: script.sessionSeed,
		assigned: script.server?.conditions,
		clock,
		language: script.language
	});
}

/** Answer a pending quota check the way `quotas` says (default open), until none is left. */
export function settle(state: State, quotas: Record<string, 'open' | 'full'> = {}): State {
	for (let guard = 0; guard < 100; guard++) {
		const v = view(state);
		if (v.status !== 'pending' || v.effect?.kind !== 'quota') return state;
		state = resolve(state, v.effect, quotas[v.effect.quota] ?? 'open');
	}
	return state;
}

export interface Played {
	state: State;
	steps: TraceStep[];
	/** Set when the script could not be played to the end (wrong page, hidden item). */
	error: { action: number; message: string } | null;
}

/** Apply one script action. Throws with a readable message when it cannot be applied. */
export function applyAction(state: State, action: ScriptAction, script: Script, i: number): State {
	const v = view(state);
	const shown = blockOfPage(state.plan, v.page);
	if (action.expectPage !== undefined && shown !== action.expectPage) {
		throw new Error(`Action ${i + 1} expects page ${action.expectPage}, but the engine shows ${shown ?? 'the end'}.`);
	}
	const visible = new Set(v.items.map((it) => it.id));
	for (const [id, value] of Object.entries(action.set ?? {})) {
		const r = tryAnswer(state, id, value);
		if (r.rejected) throw new Error(`Action ${i + 1}: answering ${id} was refused (${r.rejected}).`);
		state = r.state;
	}
	for (const [id, value] of Object.entries(action.setIfShown ?? {})) {
		if (visible.has(id)) state = tryAnswer(state, id, value).state;
	}
	const quotas = script.server?.quotas ?? {};
	switch (action.do) {
		case 'next':
			return settle(next(state).state, quotas);
		case 'retry':
			return settle(state, quotas);
		case 'back':
			return back(state);
		case 'agree':
		case 'decline': {
			const r = tryConsent(state, action.do);
			if (r.rejected) throw new Error(`Action ${i + 1}: ${action.do} was refused (${r.rejected}).`);
			return r.state;
		}
		case 'withdraw':
			return state; // the server deletes the response (semantics §11); the engine keeps its state
		case 'refresh':
		case 'resume':
		case 'switchDevice': {
			const r = restore(state.plan, JSON.parse(JSON.stringify(snapshot(state))), { clock: state.clock });
			if (!isState(r)) throw new Error(`Action ${i + 1}: restore failed (${r.error.code}).`);
			return settle(r, quotas);
		}
	}
	return state;
}

/** Play the first `upTo` actions (all by default), keeping a trace step after each. */
export function playScript(plan: Plan, script: Script, upTo = script.actions.length): Played {
	let state = startState(plan, script);
	const steps = [traceStep(state, 0)];
	const n = Math.min(upTo, script.actions.length);
	for (let i = 0; i < n; i++) {
		const action = script.actions[i]!;
		try {
			state = applyAction(state, action, script, i);
		} catch (e) {
			return { state, steps, error: { action: i, message: (e as Error).message } };
		}
		steps.push(traceStep(state, i + 1, action.do === 'next'));
	}
	return { state, steps, error: null };
}

/**
 * The run so far as a script: the start event's seed, conditions and language, then one
 * action per `next` or `back`, carrying the answers given since the previous one.
 */
export function exportScript(state: State, id = 'debugger-run'): Script {
	const events: EngineEvent[] = state.data.events;
	const startEv = events.find((e) => e.type === 'start');
	const actions: ScriptAction[] = [];
	let set: Record<string, unknown> = {};
	const quotas: Record<string, 'open' | 'full'> = {};
	for (const e of events) {
		if (e.rejected) continue;
		if (e.type === 'answer') set[e.item] = e.value;
		else if (e.type === 'consent') actions.push({ expectPage: '$consent', do: e.decision });
		else if (e.type === 'next' || e.type === 'back') {
			const a: ScriptAction = { do: e.type };
			const page = blockOfPage(state.plan, e.from);
			if (page) a.expectPage = page;
			if (Object.keys(set).length) a.set = set;
			actions.push(a);
			set = {};
		} else if (e.type === 'resolve' && e.effect.kind === 'quota' && e.effect.nodeId) {
			const quota = findQuota(state.plan, e.effect.nodeId);
			if (quota && (e.value === 'open' || e.value === 'full')) quotas[quota] = e.value;
		}
	}
	const server: Script['server'] = {};
	const assigned = startEv?.type === 'start' ? startEv.assigned : {};
	if (Object.keys(assigned).length) server.conditions = assigned;
	if (Object.keys(quotas).length) server.quotas = quotas;
	return {
		format: SCRIPT_FORMAT,
		id,
		description: 'Exported from the builder debugger.',
		sessionSeed: state.data.sessionSeed,
		language: state.data.language,
		...(Object.keys(server).length ? { server } : {}),
		actions
	};
}

function findQuota(plan: Plan, nodeId: string): string | null {
	const walk = (ns: Plan['flow']): string | null => {
		for (const n of ns) {
			if (n.id === nodeId && n.type === 'quotaCheck') return n.quota;
			const sub = n.type === 'branch' ? [...n.then, ...n.else] : n.type === 'randomiser' ? n.children : [];
			const hit = walk(sub);
			if (hit) return hit;
		}
		return null;
	};
	return walk(plan.flow);
}

// --- Comparison with an expected file (FORMAT.md §3) -------------------------------------

export interface Diff {
	path: string;
	expected: unknown;
	actual: unknown;
}

function isPlaceholder(x: unknown): boolean {
	return typeof x === 'string' && (x === '<engine>' || x.startsWith('<pending:'));
}

/** Differences between an expected step and an actual one, on the keys the expected step has. */
export function compareStep(expected: Record<string, unknown>, actual: TraceStep): Diff[] {
	const diffs: Diff[] = [];
	const a = actual as unknown as Record<string, unknown>;
	for (const k of Object.keys(expected)) {
		if (k === 'device' || k === 'notice') continue; // runtime-layer fields (R4)
		let want = expected[k];
		let got = a[k];
		if (k === 'builtins' && want && typeof want === 'object' && got && typeof got === 'object') {
			const g = got as Record<string, unknown>;
			got = Object.fromEntries(Object.keys(want).map((x) => [x, g[x]]));
		}
		if (k === 'questions' && want && typeof want === 'object') want = sortMulti(want);
		if (k === 'questions' && got && typeof got === 'object') got = sortMulti(got);
		cmp(want, got, k, diffs);
	}
	return diffs;
}

function sortMulti(qs: unknown): unknown {
	const out: Record<string, unknown> = {};
	for (const [id, q] of Object.entries(qs as Record<string, { value?: unknown }>)) {
		out[id] = q && Array.isArray(q.value) ? { ...q, value: [...q.value].map(String).sort() } : q;
	}
	return out;
}

function cmp(e: unknown, a: unknown, path: string, diffs: Diff[]) {
	if (isPlaceholder(e)) return;
	if (Array.isArray(e)) {
		if (!Array.isArray(a) || a.length !== e.length) diffs.push({ path, expected: e, actual: a });
		else e.forEach((x, i) => cmp(x, a[i], `${path}[${i}]`, diffs));
		return;
	}
	if (e !== null && typeof e === 'object') {
		if (a === null || typeof a !== 'object' || Array.isArray(a)) {
			diffs.push({ path, expected: e, actual: a });
			return;
		}
		const ea = e as Record<string, unknown>;
		const aa = a as Record<string, unknown>;
		for (const k of new Set([...Object.keys(ea), ...Object.keys(aa)])) cmp(ea[k], aa[k], `${path}.${k}`, diffs);
		return;
	}
	if (e !== a) diffs.push({ path, expected: e, actual: a });
}
