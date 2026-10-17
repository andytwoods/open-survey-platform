/**
 * The simulator (task M1, review.md §7.1, §7.2): runs N simulated participants through
 * the real participant engine (@osp/engine) and counts what happened: how often each flow
 * node and page was reached, each question's state, assigned conditions, realised
 * randomiser orders, end outcomes, branch arms taken, and participants who could not go on.
 *
 * Coverage is labelled honestly. When every answer a condition can tell apart can be
 * listed (finite choices, numbers only compared with literals …) and the space is small,
 * every path is also enumerated (`exhaustive`) and coverage comes from that; otherwise it
 * is `sampled`, with the reasons. Distributions (balance of conditions and orders) always
 * come from the sample: the enumeration counts paths, not people.
 *
 * Pure: no I/O, no clock, no Math.random. Same plan + options ⇒ same result.
 */

import {
	answer,
	isQuestion,
	next,
	nodeSeed,
	randomize,
	resolve,
	result,
	start,
	view,
	type ChoiceValue,
	type Data,
	type Id,
	type Plan,
	type QuestionItem,
	type QuestionState,
	type State
} from '@osp/engine';
import { rng as makeRng, type Rng } from './prng.ts';
import {
	BLANK,
	exhaustiveDomains,
	leavesEvidence,
	numericPoints,
	representative,
	sliderCount,
	sliderPoint,
	structure,
	usage,
	type Answer,
	type Arm,
	type Structure
} from './structure.ts';

export const SIM_FORMAT = 'osp-sim/1';
export const MAX_PARTICIPANTS = 10_000;
export const DEFAULT_EXHAUSTIVE_LIMIT = 20_000;

/**
 * How simulated participants answer.
 * - `uniform`: a uniformly random valid answer; for an optional question, blank is one
 *   more option (1 in k + 1 for k choices, 1 in 10 otherwise).
 * - `skip-optional`: optional questions blank, required ones uniform.
 * - `first-choice`: always the first choice (lowest allowed number, fixed text).
 * - `{ weights }`: per question, answer → weight (`""` = blank; a multi answer is codes
 *   joined by commas). Questions without weights are answered uniformly.
 */
export type AnswerStrategy = 'uniform' | 'skip-optional' | 'first-choice' | { weights: Record<Id, Record<string, number>> };

export interface SimOptions {
	/** Simulated participants, 1 … 10,000. */
	n: number;
	/** Seed of the simulator's own choices (participant seeds, answers). */
	seed: number;
	answerStrategy?: AnswerStrategy;
	/** Probability a quota check comes back `full` (default 0.1, so onFull paths get covered). */
	quotaFull?: number;
	/** Most answer combinations to enumerate before giving up on exhaustive (default 20,000). */
	exhaustiveLimit?: number;
	/** Set false to skip the enumeration. */
	exhaustive?: boolean;
}

export type StateCounts = Record<QuestionState, number>;

export interface Stats {
	/** Participants (sample) or enumerated answer combinations (exhaustive). */
	runs: number;
	/** End outcome → count; `stuck` for runs that could not get past a page. */
	outcomes: Record<string, number>;
	/** End node id → count; `(implicit)` for running off the end of the flow. */
	ends: Record<string, number>;
	/** Page → runs that could not get past it (no valid answer found). */
	stuck: Record<Id, number>;
	/** Flow node id → runs that reached it. */
	nodes: Record<Id, number>;
	pages: Record<Id, { reached: number; shown: number }>;
	questions: Record<Id, StateCounts>;
	/** Branch id → runs that took each arm (`undetermined`: reached, arm not observable). */
	branches: Record<Id, { then: number; else: number; undetermined: number }>;
	/** Randomiser id → realised order (child ids joined by ",") → count, and positions. */
	randomisers: Record<Id, { reached: number; orders: Record<string, number>; positions: Record<Id, number[]> }>;
	/** Assigned variable id → level → count (runs whose assign node was reached). */
	assignments: Record<Id, Record<string, number>>;
	/** quotaCheck node id → results. */
	quotas: Record<Id, { open: number; full: number }>;
	/** Runtime diagnostics, `code site` → runs. */
	diagnostics: Record<string, number>;
	paths: { distinct: number; top: Array<{ pages: Id[]; end: string; count: number }> };
}

export interface PathSpace {
	exhaustive: boolean;
	/** Distinct paths (shown pages + end) when enumerated, else null. */
	paths: number | null;
	/** Answer combinations enumerated, else null. */
	combinations: number | null;
	randomiserOrders: number;
	assignmentCombinations: number;
	reasons: string[];
}

export interface SimResult {
	format: typeof SIM_FORMAT;
	planChecksum: string;
	engineVersion: string;
	options: Required<Omit<SimOptions, 'answerStrategy'>> & { answerStrategy: AnswerStrategy };
	coverage: 'exhaustive' | 'sampled';
	pathSpace: PathSpace;
	sample: Stats;
	exhaustive: Stats | null;
}

export class SimError extends Error {
	readonly code: string;
	constructor(code: string, message: string) {
		super(message);
		this.code = code;
	}
}

// --- Accumulating runs ----------------------------------------------------------------------

const STATES: QuestionState[] = ['not-reached', 'irrelevant', 'unanswered', 'answered'];
const TOP_PATHS = 20;

class Collector {
	readonly stats: Stats;
	private readonly pathCounts = new Map<string, { pages: Id[]; end: string; count: number }>();

	constructor(
		private readonly plan: Plan,
		private readonly s: Structure
	) {
		const zero = <T>(ids: Iterable<Id>, f: () => T) => Object.fromEntries([...ids].map((id) => [id, f()]));
		const nodes = [...s.nodes.values()];
		this.stats = {
			runs: 0,
			outcomes: {},
			ends: zero(
				nodes.filter((n) => n.node.type === 'end').map((n) => n.node.id),
				() => 0
			),
			stuck: {},
			nodes: zero(s.nodes.keys(), () => 0),
			pages: zero(Object.keys(plan.pages), () => ({ reached: 0, shown: 0 })),
			questions: zero(plan.questions, () => Object.fromEntries(STATES.map((k) => [k, 0])) as StateCounts),
			branches: zero(
				nodes.filter((n) => n.node.type === 'branch').map((n) => n.node.id),
				() => ({ then: 0, else: 0, undetermined: 0 })
			),
			randomisers: Object.fromEntries(
				nodes
					.filter((n) => n.node.type === 'randomiser')
					.map((n) => {
						const kids = n.node.type === 'randomiser' ? n.node.children.map((c) => c.id) : [];
						return [n.node.id, { reached: 0, orders: {}, positions: Object.fromEntries(kids.map((k) => [k, kids.map(() => 0)])) }];
					})
			),
			assignments: Object.fromEntries(
				Object.values(plan.variables)
					.filter((v) => v.kind === 'assigned')
					.map((v) => [v.id, Object.fromEntries((v.kind === 'assigned' ? v.levels : []).map((l) => [String(l), 0]))])
			),
			quotas: zero(
				nodes.filter((n) => n.node.type === 'quotaCheck').map((n) => n.node.id),
				() => ({ open: 0, full: 0 })
			),
			diagnostics: {},
			paths: { distinct: 0, top: [] }
		};
	}

	add(state: State): void {
		const st = this.stats;
		const d = state.data;
		st.runs++;
		const stuckPage = d.ended ? null : (d.history[d.history.length - 1]?.page ?? '(none)');
		const outcome = d.ended ? d.ended.outcome : 'stuck';
		st.outcomes[outcome] = (st.outcomes[outcome] ?? 0) + 1;
		if (d.ended) {
			const end = d.ended.nodeId ?? '(implicit)';
			st.ends[end] = (st.ends[end] ?? 0) + 1;
		} else st.stuck[stuckPage!] = (st.stuck[stuckPage!] ?? 0) + 1;

		const { nodes, arms } = reachedNodes(this.plan, this.s, d);
		for (const id of nodes) if (id in st.nodes) st.nodes[id]!++;
		for (const id of nodes) {
			const b = st.branches[id];
			if (b) b[arms.get(id) ?? 'undetermined']++;
		}
		const shown = new Set(d.history.map((h) => h.page));
		for (const p of Object.keys(d.reachedPages)) {
			const c = st.pages[p];
			if (!c) continue;
			c.reached++;
			if (shown.has(p)) c.shown++;
		}
		const rec = result(state);
		for (const [id, a] of Object.entries(rec.answers)) {
			const c = st.questions[id];
			if (c) c[a.state]++;
		}
		for (const [rid, order] of Object.entries(d.orders.blocks)) {
			const r = st.randomisers[rid];
			if (!r) continue;
			r.reached++;
			const key = order.join(',');
			r.orders[key] = (r.orders[key] ?? 0) + 1;
			order.forEach((child, i) => {
				const pos = r.positions[child];
				if (pos && i < pos.length) pos[i]!++;
			});
		}
		for (const v of Object.keys(d.assignReached)) {
			const counts = st.assignments[v];
			const level = d.conditions[v];
			if (counts && level !== undefined) counts[String(level)] = (counts[String(level)] ?? 0) + 1;
		}
		for (const [node, r] of Object.entries(d.quotas)) {
			const q = st.quotas[node];
			if (q) q[r]++;
		}
		for (const diag of new Set(d.diagnostics.map((x) => `${x.code} ${x.site}`))) {
			st.diagnostics[diag] = (st.diagnostics[diag] ?? 0) + 1;
		}
		const pages = d.history.map((h) => h.page);
		const end = d.ended ? `${d.ended.outcome}@${d.ended.nodeId ?? '(implicit)'}` : `stuck@${stuckPage}`;
		const key = `${pages.join('>')}|${end}`;
		const p = this.pathCounts.get(key);
		if (p) p.count++;
		else this.pathCounts.set(key, { pages, end, count: 1 });
	}

	finish(): Stats {
		const all = [...this.pathCounts.values()];
		all.sort((a, b) => b.count - a.count || a.pages.join('>').localeCompare(b.pages.join('>')));
		this.stats.paths = { distinct: all.length, top: all.slice(0, TOP_PATHS) };
		return this.stats;
	}
}

/**
 * Flow nodes a run reached, from what it left behind: reached pages (→ their block or
 * quotaCheck node), realised randomiser orders, reached assign nodes, recorded quota
 * results and the end node. A reached node implies its enclosing nodes and every node
 * before it in its list. A branch arm is the one with evidence; with none, it is the arm
 * that would have left no trace, if the other always would.
 */
export function reachedNodes(plan: Plan, s: Structure, d: Data): { nodes: Set<Id>; arms: Map<Id, Arm> } {
	const nodes = new Set<Id>();
	const arms = new Map<Id, Arm>();
	/** Nodes the walk went all the way through (everything inside them on the path was reached). */
	const completed = new Set<Id>();
	const expanded = new Set<Id>();
	const expand = (id: Id): void => {
		const n = s.nodes.get(id)?.node;
		if (!n || expanded.has(id)) return;
		if (n.type === 'branch') {
			const arm = arms.get(id);
			if (!arm) return; // retried once the arm is known
			expanded.add(id);
			for (const c of n[arm]) complete(c.id);
		} else if (n.type === 'randomiser') {
			expanded.add(id);
			for (const c of d.orders.blocks[id] ?? []) complete(c);
		}
	};
	const complete = (id: Id): void => {
		mark(id);
		completed.add(id);
		expand(id);
	};
	const mark = (id: Id): void => {
		if (nodes.has(id)) return;
		const info = s.nodes.get(id);
		if (!info) return;
		nodes.add(id);
		const colon = info.list.indexOf(':');
		if (colon >= 0) {
			const tag = info.list.slice(0, colon);
			const parent = info.list.slice(colon + 1);
			if (tag === 'then' || tag === 'else') arms.set(parent, tag);
			mark(parent);
			if (tag === 'rand') {
				const order = d.orders.blocks[parent] ?? [];
				for (const sib of order.slice(0, Math.max(0, order.indexOf(id)))) complete(sib);
				return;
			}
		}
		for (const sib of (s.lists.get(info.list) ?? []).slice(0, info.index)) complete(sib);
	};
	// Ran off the end of the flow: every top-level node was gone through.
	if (d.ended && d.ended.nodeId === null) for (const id of s.lists.get('root') ?? []) complete(id);
	for (const p of Object.keys(d.reachedPages)) {
		const owner = s.pageOwner.get(p);
		if (owner) mark(owner);
	}
	for (const r of Object.keys(d.orders.blocks)) mark(r);
	for (const v of Object.keys(d.assignReached)) {
		const owner = s.assignOwner.get(v);
		if (owner) mark(owner);
	}
	for (const q of Object.keys(d.quotas)) mark(q);
	if (d.ended?.nodeId) mark(d.ended.nodeId);
	for (let changed = true; changed; ) {
		changed = false;
		for (const id of [...nodes]) {
			const n = s.nodes.get(id)!.node;
			if (n.type !== 'branch') continue;
			if (!arms.has(id)) {
				if (leavesEvidence(s, plan, n.then)) arms.set(id, 'else');
				else if (leavesEvidence(s, plan, n.else)) arms.set(id, 'then');
			}
			if (arms.has(id) && completed.has(id) && !expanded.has(id)) {
				expand(id);
				changed = true;
			}
		}
	}
	return { nodes, arms };
}

// --- Answering ----------------------------------------------------------------------------------

function displayOrder(state: State, page: Id): Id[] {
	return state.data.orders.items[page] ?? state.plan.pages[page]?.items ?? [];
}

function currentPage(state: State): Id | null {
	const d = state.data;
	return d.ended || d.pending ? null : (d.history[d.history.length - 1]?.page ?? null);
}

/** Relevant questions on the current page, in display order (live show-if included). */
function relevantQuestions(state: State): Set<Id> {
	return new Set(
		view(state)
			.items.filter((i) => i.state !== null)
			.map((i) => i.id)
	);
}

function pageHasLiveShowIf(plan: Plan, page: Id): boolean {
	return (plan.pages[page]?.items ?? []).some((id) => plan.items[id]?.showIf);
}

interface Drawer {
	(q: QuestionItem): Answer;
}

function parseWeighted(q: QuestionItem, key: string): Answer {
	if (key === '') return BLANK;
	const code = (k: string): ChoiceValue => q.choices?.find((c) => String(c.value) === k)?.value ?? k;
	if (q.type === 'single') return code(key);
	if (q.type === 'multi') return key.split(',').map((k) => code(k.trim()));
	return key;
}

function uniformDrawer(plan: Plan, r: Rng): Drawer {
	const u = usage(plan);
	const points = new Map<Id, Array<number | string>>();
	return (q) => {
		const choices = q.choices ?? [];
		if (!q.required) {
			const pBlank = q.type === 'single' || q.type === 'multi' ? 1 / (choices.length + 1) : 0.1;
			if (r() < pBlank) return BLANK;
		}
		switch (q.type) {
			case 'single':
				return choices.length ? r.pick(choices).value : BLANK;
			case 'multi': {
				if (!choices.length) return BLANK;
				const picked = choices.filter(() => r() < 0.5).map((c) => c.value);
				return picked.length ? picked : [r.pick(choices).value];
			}
			case 'integer':
			case 'decimal': {
				if (!points.has(q.id)) points.set(q.id, numericPoints(q, u.literals.get(q.id) ?? []) ?? []);
				const pts = points.get(q.id)!;
				if (pts.length && r() < 0.5) return r.pick(pts);
				const nums = pts.map(Number);
				const lo = q.min !== undefined ? Math.ceil(Number(q.min)) : Math.min(0, ...nums) - 10;
				const hi = q.max !== undefined ? Math.floor(Number(q.max)) : Math.max(lo, ...nums) + 100;
				if (!(Number.isFinite(lo) && Number.isFinite(hi)) || hi < lo) return representative(q);
				return r.int(lo, hi);
			}
			case 'text': {
				const lits = (u.literals.get(q.id) ?? []).filter((l) => l.kind === 'text' && l.value.trim());
				if (lits.length && r() < 0.5) return r.pick(lits).value;
				return `sim-${r.int(1, 1000)}`;
			}
			case 'date': {
				const y = r.int(1950, 2025);
				const m = r.int(1, 12);
				const day = r.int(1, 28);
				return `${y}-${String(m).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
			}
			case 'slider':
				return sliderPoint(q, r.int(0, sliderCount(q) - 1));
		}
	};
}

function drawer(plan: Plan, strategy: AnswerStrategy, r: Rng): Drawer {
	const uniform = uniformDrawer(plan, r);
	if (strategy === 'uniform') return uniform;
	if (strategy === 'skip-optional') return (q) => (q.required ? uniform(q) : BLANK);
	if (strategy === 'first-choice') return (q) => representative(q);
	const weights = strategy.weights;
	return (q) => {
		const w = weights[q.id];
		if (!w) return uniform(q);
		const entries = Object.entries(w).filter(([, x]) => Number.isFinite(x) && x > 0);
		const total = entries.reduce((a, [, x]) => a + x, 0);
		if (!total) return uniform(q);
		let roll = r() * total;
		for (const [k, x] of entries) {
			roll -= x;
			if (roll < 0) return parseWeighted(q, k);
		}
		return parseWeighted(q, entries[entries.length - 1]![0]);
	};
}

function put(state: State, id: Id, a: Answer): State {
	return answer(state, id, a === BLANK ? null : a);
}

function fillPage(state: State, page: Id, draw: Drawer, only?: Set<Id>): State {
	const live = pageHasLiveShowIf(state.plan, page);
	let relevant = relevantQuestions(state);
	for (const id of displayOrder(state, page)) {
		if (only && !only.has(id)) continue;
		const item = state.plan.items[id];
		if (!item || !isQuestion(item)) continue;
		if (live) relevant = relevantQuestions(state);
		if (!relevant.has(id)) continue;
		state = put(state, id, draw(item));
	}
	return state;
}

const MAX_RETRIES = 30;

/** One simulated participant, from start to an end (or stuck on a page). */
function participant(plan: Plan, sessionSeed: number, draw: Drawer, r: Rng, quotaFull: number): State {
	let t = 0;
	let state = start(plan, { sessionSeed, clock: () => t++ });
	const maxSteps = 4 * Object.keys(plan.pages).length + 16;
	for (let step = 0; step < maxSteps; step++) {
		const d = state.data;
		if (d.ended) return state;
		if (d.pending) {
			state = resolve(state, d.pending.effect, r() < quotaFull ? 'full' : 'open');
			continue;
		}
		const page = currentPage(state);
		if (page === null) return state;
		state = fillPage(state, page, draw);
		let out = next(state);
		for (let tries = 0; out.result.outcome === 'invalid' && tries < MAX_RETRIES; tries++) {
			const bad = new Set(Object.keys(out.state.data.errors));
			const last = tries === MAX_RETRIES - 1;
			// Re-draw the questions in error; on the last try, leave optional ones blank.
			const redraw: Drawer = (q) => (last && !q.required ? BLANK : draw(q));
			state = fillPage(out.state, page, redraw, bad);
			out = next(state);
		}
		if (out.result.outcome === 'invalid') return out.state; // stuck on this page
		state = out.state;
	}
	return state;
}

// --- Exhaustive enumeration -------------------------------------------------------------------

class Budget extends Error {}

function randomiserNodes(s: Structure) {
	return [...s.nodes.values()].map((n) => n.node).filter((n) => n.type === 'randomiser');
}

/** One session seed per distinct combination of randomiser orders, or null if not all found. */
function seedsPerOrderCombination(plan: Plan, s: Structure, total: number): number[] | null {
	const rands = randomiserNodes(s);
	if (!rands.length) return [1];
	const found = new Map<string, number>();
	const tries = Math.max(20_000, total * 60);
	for (let seed = 1; seed <= tries && found.size < total; seed++) {
		const sig = rands
			.map((n) => {
				const order = randomize(
					n.children.map((c) => c.id),
					nodeSeed(plan.survey.seedVersion, seed, n.id)
				);
				return (n.pick ? order.slice(0, n.pick) : order).join(',');
			})
			.join('|');
		if (!found.has(sig)) found.set(sig, seed);
	}
	return found.size === total ? [...found.values()] : null;
}

function assignmentCombinations(plan: Plan): Array<Record<Id, ChoiceValue>> {
	let out: Array<Record<Id, ChoiceValue>> = [{}];
	for (const v of Object.values(plan.variables)) {
		if (v.kind !== 'assigned') continue;
		out = out.flatMap((combo) => v.levels.map((l) => ({ ...combo, [v.id]: l })));
	}
	return out;
}

const MAX_ORDER_COMBINATIONS = 5040;
const MAX_ASSIGN_COMBINATIONS = 1000;

function enumerate(plan: Plan, s: Structure, limit: number, collector: Collector): { space: PathSpace; ok: boolean } {
	const { domains, reasons } = exhaustiveDomains(plan);
	const orders = [...s.possibleOrders.values()].reduce((a, b) => a * b, 1);
	const combos = assignmentCombinations(plan);
	const space: PathSpace = {
		exhaustive: false,
		paths: null,
		combinations: null,
		randomiserOrders: orders,
		assignmentCombinations: combos.length,
		reasons: [...reasons]
	};
	if (orders > MAX_ORDER_COMBINATIONS) space.reasons.push(`${orders} randomiser order combinations (more than ${MAX_ORDER_COMBINATIONS})`);
	if (combos.length > MAX_ASSIGN_COMBINATIONS) {
		space.reasons.push(`${combos.length} assignment combinations (more than ${MAX_ASSIGN_COMBINATIONS})`);
	}
	if (space.reasons.length) return { space, ok: false };
	const seeds = seedsPerOrderCombination(plan, s, orders);
	if (!seeds) {
		space.reasons.push('not every combination of randomiser orders could be realised');
		return { space, ok: false };
	}
	let leaves = 0;
	let work = 0;
	const leaf = (state: State) => {
		if (++leaves > limit) throw new Budget();
		collector.add(state);
	};
	const tick = () => {
		if (++work > limit * 200) throw new Budget();
	};
	const explore = (state: State): void => {
		tick();
		const d = state.data;
		if (d.ended) return leaf(state);
		if (d.pending) {
			const effect = d.pending.effect;
			explore(resolve(state, effect, 'open'));
			explore(resolve(state, effect, 'full'));
			return;
		}
		const page = currentPage(state);
		if (page === null) return leaf(state);
		const order = displayOrder(state, page).filter((id) => {
			const it = plan.items[id];
			return it && isQuestion(it);
		});
		if (!fill(state, order, 0)) leaf(state); // no valid answers: stuck here
	};
	/** Every combination of answers on the page; true if any of them was valid. */
	const fill = (state: State, order: Id[], i: number): boolean => {
		tick();
		if (i >= order.length) {
			const out = next(state);
			if (out.result.outcome === 'invalid') return false;
			explore(out.state);
			return true;
		}
		const id = order[i]!;
		if (!relevantQuestions(state).has(id)) return fill(state, order, i + 1);
		let any = false;
		for (const a of domains.get(id) ?? [BLANK]) {
			if (fill(put(state, id, a), order, i + 1)) any = true;
		}
		return any;
	};
	try {
		for (const seed of seeds) {
			for (const assigned of combos) {
				let t = 0;
				explore(start(plan, { sessionSeed: seed, assigned, clock: () => t++ }));
			}
		}
	} catch (e) {
		if (!(e instanceof Budget)) throw e;
		space.reasons.push(`more than ${limit} answer combinations`);
		return { space, ok: false };
	}
	const stats = collector.finish();
	space.exhaustive = true;
	space.paths = stats.paths.distinct;
	space.combinations = stats.runs;
	return { space, ok: true };
}

// --- Entry point ------------------------------------------------------------------------------

function checkOptions(o: SimOptions): Required<Omit<SimOptions, 'answerStrategy'>> & { answerStrategy: AnswerStrategy } {
	if (!o || typeof o !== 'object') throw new SimError('options.invalid', 'options must be an object');
	const { n, seed } = o;
	if (!Number.isSafeInteger(n) || n < 1 || n > MAX_PARTICIPANTS) {
		throw new SimError('options.n', `n must be an integer from 1 to ${MAX_PARTICIPANTS}`);
	}
	if (!Number.isSafeInteger(seed) || seed < 0) throw new SimError('options.seed', 'seed must be a non-negative integer');
	const strategy = o.answerStrategy ?? 'uniform';
	const named = ['uniform', 'skip-optional', 'first-choice'];
	const okStrategy =
		(typeof strategy === 'string' && named.includes(strategy)) ||
		(typeof strategy === 'object' &&
			strategy !== null &&
			typeof strategy.weights === 'object' &&
			strategy.weights !== null &&
			Object.values(strategy.weights).every(
				(w) => typeof w === 'object' && w !== null && Object.values(w).every((x) => typeof x === 'number' && Number.isFinite(x) && x >= 0)
			));
	if (!okStrategy) throw new SimError('options.answerStrategy', `answerStrategy must be one of ${named.join(', ')} or { weights }`);
	const quotaFull = o.quotaFull ?? 0.1;
	if (typeof quotaFull !== 'number' || !(quotaFull >= 0 && quotaFull <= 1)) {
		throw new SimError('options.quotaFull', 'quotaFull must be a probability from 0 to 1');
	}
	const exhaustiveLimit = o.exhaustiveLimit ?? DEFAULT_EXHAUSTIVE_LIMIT;
	if (!Number.isSafeInteger(exhaustiveLimit) || exhaustiveLimit < 0 || exhaustiveLimit > 200_000) {
		throw new SimError('options.exhaustiveLimit', 'exhaustiveLimit must be an integer from 0 to 200,000');
	}
	return { n, seed, answerStrategy: strategy, quotaFull, exhaustiveLimit, exhaustive: o.exhaustive ?? true };
}

/**
 * Run `n` simulated participants through `plan` (and, when the path space is small enough
 * and fully listable, enumerate every path). Throws SimError for bad options and the
 * engine's EngineError for a plan it can't run.
 */
export function simulate(plan: Plan, options: SimOptions): SimResult {
	const opts = checkOptions(options);
	start(plan, { sessionSeed: 1, clock: () => 0 }); // validates the plan (checksum, versions)
	const s = structure(plan);
	const r = makeRng(opts.seed);
	const draw = drawer(plan, opts.answerStrategy, r);
	const sample = new Collector(plan, s);
	for (let i = 0; i < opts.n; i++) sample.add(participant(plan, r.seed(), draw, r, opts.quotaFull));

	let space: PathSpace;
	let exhaustive: Stats | null = null;
	if (opts.exhaustive) {
		const collector = new Collector(plan, s);
		const out = enumerate(plan, s, opts.exhaustiveLimit, collector);
		space = out.space;
		if (out.ok) exhaustive = collector.stats;
	} else {
		space = {
			exhaustive: false,
			paths: null,
			combinations: null,
			randomiserOrders: [...s.possibleOrders.values()].reduce((a, b) => a * b, 1),
			assignmentCombinations: assignmentCombinations(plan).length,
			reasons: ['enumeration was switched off']
		};
	}
	return {
		format: SIM_FORMAT,
		planChecksum: plan.checksum,
		engineVersion: plan.engineVersion,
		options: opts,
		coverage: exhaustive ? 'exhaustive' : 'sampled',
		pathSpace: space,
		sample: sample.finish(),
		exhaustive
	};
}
