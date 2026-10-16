/**
 * The participant engine: a pure state machine over a runtime plan (runtime-design.md §3,
 * semantics.md). No DOM, no I/O, no Math.random, no Date.now: time comes from the
 * injected clock and randomness from `nodeSeed`.
 *
 * Every call that changes the state appends one event to the log and applies it with
 * `apply`; `replay` re-applies a log, so a state is exactly its events. `restore` replays
 * a snapshot's log and refuses the snapshot unless the result is identical.
 *
 * Rules implemented, with semantics.md sections (PROVISIONAL marks an open question):
 * - §1 states: not-reached (page never reached), irrelevant (reached, hidden), unanswered,
 *   answered. Once reached, a page stays reached (fixtures/FORMAT.md §4.2; C3a-6 open).
 * - §3 a value that is irrelevant at a page submit is cleared then; until then a hidden
 *   value is kept (live show-if within a page). Clearing is a fixpoint: an irrelevant
 *   question is null to every expression, so dependants follow in the same submit.
 * - §4 required only while relevant; constraints only on answered values; validation on
 *   page submit (`next`).
 * - §5 back keeps values and re-evaluates later pages when they are reached again.
 * - §6 a page with no relevant item is skipped and its questions become irrelevant
 *   (PROVISIONAL C3a-1: notes count as content, so a notes-only page is shown). Running off
 *   the end of the flow is `end: complete`.
 * - §7 realised orders are computed at first reach and stored before the page renders.
 */

import { planChecksum, canonicalJson } from './canonical.ts';
import { evaluate, evaluateCondition, type Lookup, type Value } from './expr.ts';
import * as dec from './decimal.ts';
import {
	ENGINE_VERSION,
	PLAN_VERSION,
	isQuestion,
	type BlockNode,
	type ChoiceValue,
	type FlowNode,
	type Id,
	type Item,
	type Plan,
	type QuestionItem,
	type Segment,
	type Text
} from './plan.ts';
import { assign as drawCondition, checkSeed, nodeSeed, randomize, InvalidSeedError } from './random.ts';
import {
	EngineError,
	type AnswerRecord,
	type Clock,
	type Ctx,
	type Data,
	type Effect,
	type EngineEvent,
	type Frame,
	type PageError,
	type PageView,
	type Position,
	type QuestionState,
	type QuotaResult,
	type RenderedText,
	type ResponseRecord,
	type Snapshot,
	type StartOptions,
	type State,
	type StepResult,
	type ViewItem
} from './types.ts';
import { checkAnswer, codeValue, matchChoice, pyStrip, toValue, type Stored } from './values.ts';

const MAX_WALK = 1_000_000;

// --- Plan index ------------------------------------------------------------------------

interface Index {
	nodes: Map<Id, FlowNode>;
	pageCount: number;
}
const indexes = new WeakMap<Plan, Index>();

function index(plan: Plan): Index {
	let ix = indexes.get(plan);
	if (ix) return ix;
	const nodes = new Map<Id, FlowNode>();
	const walk = (ns: FlowNode[]) => {
		for (const n of ns) {
			nodes.set(n.id, n);
			if (n.type === 'branch') {
				walk(n.then);
				walk(n.else);
			} else if (n.type === 'randomiser') walk(n.children);
		}
	};
	walk(plan.flow);
	ix = { nodes, pageCount: Object.keys(plan.pages).length };
	indexes.set(plan, ix);
	return ix;
}

type List = { kind: 'nodes'; nodes: FlowNode[] } | { kind: 'pages'; pages: Id[]; end?: Id };

/** The node or page list a frame iterates. Unknown keys give an empty list. */
function listFor(plan: Plan, data: Data, key: string): List {
	const ix = index(plan);
	const colon = key.indexOf(':');
	const tag = colon < 0 ? key : key.slice(0, colon);
	const id = colon < 0 ? '' : key.slice(colon + 1);
	const node = ix.nodes.get(id);
	switch (tag) {
		case 'root':
			return { kind: 'nodes', nodes: plan.flow };
		case 'then':
			return { kind: 'nodes', nodes: node?.type === 'branch' ? node.then : [] };
		case 'else':
			return { kind: 'nodes', nodes: node?.type === 'branch' ? node.else : [] };
		case 'rand': {
			const order = data.orders.blocks[id] ?? [];
			const nodes = order.map((c) => ix.nodes.get(c)).filter((n): n is FlowNode => !!n);
			return { kind: 'nodes', nodes };
		}
		case 'pages':
			return { kind: 'pages', pages: node?.type === 'block' ? (node as BlockNode).pages : [] };
		case 'full': {
			if (node?.type !== 'quotaCheck') return { kind: 'pages', pages: [] };
			const q = plan.quotas[node.quota];
			return { kind: 'pages', pages: q?.onFull.pages ?? [], end: q?.onFull.outcome ?? 'complete' };
		}
	}
	return { kind: 'nodes', nodes: [] };
}

// --- Evaluation environment ------------------------------------------------------------

const INT_TEXT = /^[+-]?\d+$/;

function embeddedRaw(plan: Plan, data: Data, id: Id): string | number | null {
	const v = plan.variables[id];
	if (!v || v.kind !== 'embedded') return null;
	// PROVISIONAL (C3a-5): the URL parameter if present, else the declared default.
	const raw: string | number | null = Object.prototype.hasOwnProperty.call(data.urlParams, v.param)
		? (data.urlParams[v.param] ?? null)
		: v.default;
	if (raw === null || raw === undefined) return null;
	const text = typeof raw === 'number' ? String(raw) : pyStrip(raw);
	if (text === '') return null;
	if (v.valueType === 'integer') {
		if (!INT_TEXT.test(text)) return null;
		const n = Number(text);
		return Number.isSafeInteger(n) ? n : null;
	}
	if (v.valueType === 'decimal') return dec.parseDecimal(text) === null ? null : text.replace(/^\+/, '');
	return text;
}

class Env {
	private rel = new Map<Id, boolean>();
	private comp = new Map<Id, Value>();
	private busy = new Set<string>();
	constructor(
		readonly plan: Plan,
		readonly data: Data,
		readonly cursor: Frame[] | null = null
	) {}

	relevant(id: Id): boolean {
		const memo = this.rel.get(id);
		if (memo !== undefined) return memo;
		const item = this.plan.items[id];
		let r = false;
		if (item && this.data.reachedPages[item.page]) {
			if (!item.showIf) r = true;
			else if (this.busy.has(`r:${id}`)) return false; // a cycle: never in a valid plan
			else {
				this.busy.add(`r:${id}`);
				r = evaluateCondition(item.showIf, this.lookup);
				this.busy.delete(`r:${id}`);
			}
		}
		this.rel.set(id, r);
		return r;
	}

	state(id: Id): QuestionState {
		const item = this.plan.items[id];
		if (!item || !this.data.reachedPages[item.page]) return 'not-reached';
		if (!this.relevant(id)) return 'irrelevant';
		return this.value(id) === null ? 'unanswered' : 'answered';
	}

	/** The stored value if the question is relevant, else null. */
	value(id: Id): Stored {
		if (!this.relevant(id)) return null;
		const v = this.data.values[id];
		return v === undefined ? null : v;
	}

	lookup: Lookup = (id: string): Value => {
		if (id.startsWith('$')) return this.builtin(id);
		const item = this.plan.items[id];
		if (item) return isQuestion(item) ? toValue(item.type, this.value(id)) : null;
		const v = this.plan.variables[id];
		if (!v) return null;
		switch (v.kind) {
			case 'embedded': {
				const raw = embeddedRaw(this.plan, this.data, id);
				if (raw === null) return null;
				if (v.valueType === 'text') return { k: 'text', v: String(raw) };
				return toValue(v.valueType, raw);
			}
			case 'assigned':
				// PROVISIONAL (C3a-7): null until the assign node is reached (osp-spec forbids
				// referring to it earlier, C2-1), although the value is fixed at start.
				return this.data.assignReached[id] && id in this.data.conditions
					? codeValue(this.data.conditions[id])
					: null;
			case 'computed': {
				// PROVISIONAL (C2-6): recomputed from current values whenever read.
				const memo = this.comp.get(id);
				if (memo !== undefined) return memo;
				if (this.busy.has(`c:${id}`)) return null;
				this.busy.add(`c:${id}`);
				const r = evaluate(v.expr, this.lookup);
				this.busy.delete(`c:${id}`);
				this.comp.set(id, r);
				return r;
			}
		}
		return null;
	};

	builtin(id: string): Value {
		const d = this.data;
		const text = (s: string | null): Value => (s ? { k: 'text', v: s } : null);
		const int = (n: number | null): Value =>
			n === null ? null : { k: 'num', v: dec.fromInteger(n), int: true };
		switch (id) {
			case '$trial':
				return int(d.history.length || null);
			case '$pagesDone':
				return int(pagesDone(d));
			case '$language':
				return text(d.language);
			case '$device':
				return text(d.device);
			case '$position.index':
				return int(position(this.plan, d, this.cursor ?? currentCursor(d))?.index ?? null);
			case '$position.of':
				return int(position(this.plan, d, this.cursor ?? currentCursor(d))?.of ?? null);
		}
		return null;
	}
}

function currentCursor(d: Data): Frame[] {
	return d.history[d.history.length - 1]?.cursor ?? [];
}

function pagesDone(d: Data): number {
	return d.ended ? d.history.length : Math.max(0, d.history.length - 1);
}

function position(plan: Plan, d: Data, cursor: Frame[]): Position | null {
	for (let i = cursor.length - 1; i >= 0; i--) {
		const f = cursor[i]!;
		if (f.k.startsWith('rand:')) {
			const id = f.k.slice(5);
			return { randomiserId: id, index: f.i + 1, of: (d.orders.blocks[id] ?? []).length };
		}
	}
	void plan;
	return null;
}

// --- Data helpers ----------------------------------------------------------------------

function clone<T>(x: T): T {
	return JSON.parse(JSON.stringify(x)) as T;
}

function now(clock: Clock): number {
	try {
		const t = Number(clock());
		return Number.isFinite(t) ? t : 0;
	} catch {
		return 0;
	}
}

function currentPage(d: Data): Id | null {
	if (d.ended) return null;
	return d.history[d.history.length - 1]?.page ?? null;
}

function seedVersion(plan: Plan): string {
	return plan.survey.seedVersion;
}

// --- Walking the flow ------------------------------------------------------------------

type WalkOutcome = { kind: 'page'; page: Id; cursor: Frame[] } | { kind: 'effect' } | { kind: 'end' };

/** Realise orders for a page at first reach and mark it reached. */
function enterPage(plan: Plan, d: Data, pageId: Id): void {
	const page = plan.pages[pageId];
	d.reachedPages[pageId] = true;
	if (!page) return;
	if (page.itemOrder === 'shuffle' && !d.orders.items[pageId]) {
		d.orders.items[pageId] = randomize(page.items, nodeSeed(seedVersion(plan), d.sessionSeed, pageId));
	}
	for (const id of page.items) {
		const item = plan.items[id];
		if (item && isQuestion(item) && item.choiceOrder === 'shuffle' && !d.orders.choices[id]) {
			const codes = (item.choices ?? []).map((c) => c.value);
			d.orders.choices[id] = randomize(codes, nodeSeed(seedVersion(plan), d.sessionSeed, id));
		}
	}
}

function pageHasContent(plan: Plan, d: Data, pageId: Id, cursor: Frame[]): boolean {
	const env = new Env(plan, d, cursor);
	return (plan.pages[pageId]?.items ?? []).some((id) => env.relevant(id));
}

function popFrame(cursor: Frame[]): void {
	cursor.pop();
	const parent = cursor[cursor.length - 1];
	if (parent) parent.i++;
}

/**
 * Walk forward from `cursor` (pointing at the next thing to do) to the next page to show,
 * an effect, or the end. Mutates `d` (orders, reached pages, assignment, pending, ended).
 */
function walk(plan: Plan, d: Data, cursor: Frame[], t: number): WalkOutcome {
	for (let steps = 0; steps < MAX_WALK; steps++) {
		const top = cursor[cursor.length - 1];
		if (!top) {
			d.ended = { outcome: 'complete', nodeId: null, at: t }; // §6 implicit end
			return { kind: 'end' };
		}
		const list = listFor(plan, d, top.k);
		if (list.kind === 'pages') {
			if (top.i >= list.pages.length) {
				if (list.end !== undefined) {
					d.ended = { outcome: list.end, nodeId: top.k.slice(5), at: t };
					return { kind: 'end' };
				}
				popFrame(cursor);
				continue;
			}
			const pageId = list.pages[top.i]!;
			enterPage(plan, d, pageId);
			if (pageHasContent(plan, d, pageId, cursor)) return { kind: 'page', page: pageId, cursor };
			top.i++; // §6: skipped silently
			continue;
		}
		if (top.i >= list.nodes.length) {
			popFrame(cursor);
			continue;
		}
		const node = list.nodes[top.i]!;
		switch (node.type) {
			case 'block':
				cursor.push({ k: `pages:${node.id}`, i: 0 });
				break;
			case 'branch': {
				const yes = evaluateCondition(node.if, new Env(plan, d, cursor).lookup);
				cursor.push({ k: `${yes ? 'then' : 'else'}:${node.id}`, i: 0 });
				break;
			}
			case 'randomiser': {
				if (!d.orders.blocks[node.id]) {
					// PROVISIONAL (R1-2, C2-4): `pick` takes the first `pick` children of the
					// seeded shuffle (a uniform draw without replacement).
					const ids = node.children.map((c) => c.id);
					const order = randomize(ids, nodeSeed(seedVersion(plan), d.sessionSeed, node.id));
					d.orders.blocks[node.id] = node.pick ? order.slice(0, node.pick) : order;
				}
				cursor.push({ k: `rand:${node.id}`, i: 0 });
				break;
			}
			case 'assign':
				for (const v of node.variables) d.assignReached[v] = true;
				top.i++;
				break;
			case 'quotaCheck': {
				const quota = plan.quotas[node.quota];
				// PROVISIONAL (C3a-3, C2-7): the check applies only while `when` is true;
				// the server result is asked once per node and then reused (idempotent);
				// `full` shows the onFull block's pages, then ends with its outcome.
				const applies = quota ? evaluateCondition(quota.when, new Env(plan, d, cursor).lookup) : false;
				if (!applies) {
					top.i++;
					break;
				}
				const recorded = d.quotas[node.id];
				if (recorded === 'full') {
					cursor.push({ k: `full:${node.id}`, i: 0 });
				} else if (recorded === 'open') {
					top.i++;
				} else {
					d.pending = {
						effect: { kind: 'quota', nodeId: node.id, quota: node.quota },
						cursor: clone(cursor)
					};
					return { kind: 'effect' };
				}
				break;
			}
			case 'end':
				d.ended = { outcome: node.outcome, nodeId: node.id, at: t };
				return { kind: 'end' };
			default:
				top.i++;
		}
	}
	d.ended = { outcome: 'complete', nodeId: null, at: t };
	return { kind: 'end' };
}

function finishWalk(d: Data, out: WalkOutcome, t: number): StepResult {
	if (out.kind === 'page') {
		d.history.push({ page: out.page, cursor: clone(out.cursor), shownAt: t });
		return { outcome: 'advanced', to: out.page };
	}
	if (out.kind === 'effect') return { outcome: 'effect', effect: d.pending!.effect };
	return { outcome: 'ended', to: null, effect: endEffect(d)! };
}

function endEffect(d: Data): Effect | null {
	return d.ended ? { kind: 'end', outcome: d.ended.outcome, nodeId: d.ended.nodeId } : null;
}

// --- Validation and clearing -----------------------------------------------------------

function displayOrder(plan: Plan, d: Data, pageId: Id): Id[] {
	return d.orders.items[pageId] ?? plan.pages[pageId]?.items ?? [];
}

function validate(plan: Plan, d: Data, pageId: Id): Record<Id, PageError> {
	const env = new Env(plan, d);
	const errors: Record<Id, PageError> = {};
	for (const id of displayOrder(plan, d, pageId)) {
		const item = plan.items[id];
		if (!item || !isQuestion(item) || !env.relevant(id)) continue;
		const bad = d.invalid[id];
		if (bad !== undefined) errors[id] = { kind: 'invalid', code: bad };
		else if (env.value(id) === null) {
			if (item.required) errors[id] = { kind: 'required' };
		} else if (item.constraint && !evaluateCondition(item.constraint, env.lookup)) {
			errors[id] = { kind: 'constraint' };
		}
	}
	return errors;
}

/** §3: on page submit, clear the value of every reached question that is irrelevant. */
function clearIrrelevant(plan: Plan, d: Data): void {
	const env = new Env(plan, d);
	const hidden = plan.questions.filter((id) => d.reachedPages[plan.items[id]?.page ?? ''] && !env.relevant(id));
	for (const id of hidden) {
		delete d.values[id];
		delete d.invalid[id];
	}
}

// --- Applying events -------------------------------------------------------------------

function initialData(plan: Plan, ev: Extract<EngineEvent, { type: 'start' }>): Data {
	const d: Data = {
		format: 'osp-engine-state/1',
		planChecksum: plan.checksum,
		sessionSeed: ev.sessionSeed,
		sessionId: ev.sessionId,
		language: ev.language,
		device: ev.device,
		urlParams: { ...ev.urlParams },
		startedAt: ev.t,
		revision: 0,
		values: {},
		invalid: {},
		reachedPages: {},
		conditions: {},
		conditionSource: {},
		assignReached: {},
		orders: { blocks: {}, items: {}, choices: {} },
		quotas: {},
		history: [],
		pending: null,
		errors: {},
		ended: null,
		events: []
	};
	for (const v of Object.values(plan.variables)) {
		if (v.kind !== 'assigned') continue;
		if (Object.prototype.hasOwnProperty.call(ev.assigned, v.id)) {
			d.conditions[v.id] = ev.assigned[v.id]!;
			d.conditionSource[v.id] = 'server';
		} else {
			// PROVISIONAL (C2-5): an independent uniform seeded draw per variable, on the stream
			// `seedNode` (R1-2), exactly as the server's simple assignment. Drawn at start, so
			// it never re-rolls. Normally the server sends every level and this is not used.
			const seed = nodeSeed(seedVersion(plan), ev.sessionSeed, v.seedNode || v.id);
			d.conditions[v.id] = drawCondition(v.levels, null, seed);
			d.conditionSource[v.id] = 'seeded';
		}
	}
	return d;
}

/** Apply one (non-rejected) event to `d` in place. Returns the step result, if any. */
function apply(plan: Plan, d: Data, ev: EngineEvent): StepResult | undefined {
	switch (ev.type) {
		case 'start': {
			const out = walk(plan, d, [{ k: 'root', i: 0 }], ev.t);
			return finishWalk(d, out, ev.t);
		}
		case 'answer':
			if (ev.invalid !== undefined) {
				delete d.values[ev.item];
				d.invalid[ev.item] = ev.invalid;
			} else {
				if (ev.value === null) delete d.values[ev.item];
				else d.values[ev.item] = ev.value;
				delete d.invalid[ev.item];
			}
			delete d.errors[ev.item];
			return undefined;
		case 'next': {
			const page = currentPage(d);
			if (page === null) return undefined;
			const errors = validate(plan, d, page);
			if (Object.keys(errors).length) {
				d.errors = errors;
				return { outcome: 'invalid', to: page, errors };
			}
			d.errors = {};
			clearIrrelevant(plan, d);
			const cursor = clone(currentCursor(d));
			const top = cursor[cursor.length - 1];
			if (top) top.i++;
			return finishWalk(d, walk(plan, d, cursor, ev.t), ev.t);
		}
		case 'back':
			d.pending = null;
			d.errors = {};
			d.history.pop();
			return undefined;
		case 'resolve': {
			const p = d.pending;
			if (!p || ev.effect.kind !== 'quota') return undefined;
			d.quotas[p.effect.nodeId] = ev.value as QuotaResult;
			d.pending = null;
			return finishWalk(d, walk(plan, d, clone(p.cursor), ev.t), ev.t);
		}
		case 'language':
			d.language = ev.language;
			return undefined;
	}
}

type NewEvent = EngineEvent extends infer E ? (E extends EngineEvent ? Omit<E, 'seq' | 'rev'> : never) : never;

function commit(state: State, partial: NewEvent): { state: State; result?: StepResult } {
	const d = clone(state.data);
	const ev = { ...partial, seq: d.events.length + 1, rev: d.revision + 1 } as EngineEvent;
	let result: StepResult | undefined;
	if (ev.rejected === undefined) result = apply(state.plan, d, ev);
	if (result !== undefined && (ev.type === 'next' || ev.type === 'resolve')) ev.result = result;
	if (ev.type === 'back' && ev.rejected === undefined) ev.to = currentPage(d);
	d.revision += 1;
	d.events.push(ev);
	return { state: { plan: state.plan, clock: state.clock, data: d }, result };
}

// --- Public API ------------------------------------------------------------------------

/** Throws EngineError if the plan is not one this engine runs. */
export function checkPlan(plan: Plan): void {
	if (!plan || typeof plan !== 'object') throw new EngineError('plan.invalid', 'plan is not an object');
	if (plan.planVersion !== PLAN_VERSION) {
		throw new EngineError('plan.version', `unsupported plan version ${String(plan.planVersion)}`);
	}
	if (plan.engineVersion !== ENGINE_VERSION) {
		throw new EngineError('plan.engine_version', `plan targets engine ${String(plan.engineVersion)}`);
	}
	if (planChecksum(plan) !== plan.checksum) throw new EngineError('plan.checksum', 'plan checksum mismatch');
}

/** Return a copy of `plan` with its checksum recomputed (for hand-built plans in tests). */
export function withChecksum(plan: Omit<Plan, 'checksum'> & { checksum?: string }): Plan {
	return { ...plan, checksum: planChecksum(plan) } as Plan;
}

/**
 * Start a session. Throws EngineError for a plan this engine can't run, a bad seed, or a
 * server-assigned level that is not one of the variable's levels.
 */
export function start(plan: Plan, opts: StartOptions): State {
	checkPlan(plan);
	let seed: number;
	try {
		seed = checkSeed(opts.sessionSeed);
	} catch (e) {
		if (e instanceof InvalidSeedError) throw new EngineError(e.code, e.message);
		throw e;
	}
	const assigned: Record<Id, ChoiceValue> = {};
	for (const [id, raw] of Object.entries(opts.assigned ?? {})) {
		const v = plan.variables[id];
		if (!v || v.kind !== 'assigned') throw new EngineError('assigned.unknown', `no assigned variable ${id}`);
		const level = v.levels.find((l) => String(l) === String(raw));
		if (level === undefined) throw new EngineError('assigned.invalid_level', `${String(raw)} is not a level of ${id}`);
		assigned[id] = level;
	}
	const language = opts.language && plan.languages.includes(opts.language) ? opts.language : plan.defaultLanguage;
	const urlParams: Record<string, string> = {};
	for (const [k, v] of Object.entries(opts.urlParams ?? {})) if (typeof v === 'string') urlParams[k] = v;
	const clock = opts.clock;
	const ev: EngineEvent = {
		type: 'start',
		seq: 1,
		rev: 1,
		t: now(clock),
		sessionSeed: seed,
		assigned,
		language,
		device: opts.device ?? null,
		urlParams,
		sessionId: opts.sessionId ?? null
	};
	const d = initialData(plan, ev);
	apply(plan, d, ev);
	d.revision = 1;
	d.events.push(ev);
	return { plan, clock, data: d };
}

export type Rejection =
	| 'ended'
	| 'pending'
	| 'unknown-item'
	| 'not-a-question'
	| 'not-on-page'
	| 'hidden'
	| 'back-disabled'
	| 'first-page'
	| 'stale'
	| 'unsupported'
	| 'bad-result'
	| 'unknown-language';

/** `answer`, also saying why a call was refused (refusals change nothing). */
export function tryAnswer(state: State, itemId: Id, value: unknown): { state: State; rejected?: Rejection } {
	const d = state.data;
	const page = currentPage(d);
	let rejected: Rejection | undefined;
	const item: Item | undefined = state.plan.items[itemId];
	if (d.ended) rejected = 'ended';
	else if (d.pending) rejected = 'pending';
	else if (!item) rejected = 'unknown-item';
	else if (!isQuestion(item)) rejected = 'not-a-question';
	else if (item.page !== page) rejected = 'not-on-page';
	else if (!new Env(state.plan, d).relevant(itemId)) rejected = 'hidden';
	if (rejected || !item || !isQuestion(item)) return { state, rejected };
	const checked = checkAnswer(item, value);
	const t = now(state.clock);
	const partial: NewEvent = checked.ok
		? { type: 'answer', t, item: itemId, value: checked.value }
		: { type: 'answer', t, item: itemId, value: null, invalid: checked.code };
	return { state: commit(state, partial).state };
}

/** Set an answer on the current page (live show-if follows). Refused calls return `state`. */
export function answer(state: State, itemId: Id, value: unknown): State {
	return tryAnswer(state, itemId, value).state;
}

/**
 * Submit the current page: validate, clear values made irrelevant, and move on. Returns an
 * effect when the runtime must act: `quota` (call the server, then `resolve`) or `end`.
 * Repeating `next` while an effect is pending or after the end returns the same effect
 * and changes nothing.
 */
export function next(state: State): { state: State; effect?: Effect; result: StepResult } {
	const d = state.data;
	if (d.ended) {
		const effect = endEffect(d)!;
		return { state, effect, result: { outcome: 'ended', to: null, effect } };
	}
	if (d.pending) {
		const effect = d.pending.effect;
		return { state, effect, result: { outcome: 'effect', effect } };
	}
	const out = commit(state, { type: 'next', t: now(state.clock), from: currentPage(d) });
	const result = out.result ?? { outcome: 'invalid' as const };
	return { state: out.state, effect: result.effect, result };
}

export function canGoBack(state: State): boolean {
	const d = state.data;
	return !d.ended && state.plan.settings.backNavigation && d.history.length > 1;
}

/** Go to the previous shown page, keeping values (§5). Refused calls return `state`. */
export function back(state: State): State {
	return tryBack(state).state;
}

export function tryBack(state: State): { state: State; rejected?: Rejection } {
	const d = state.data;
	if (d.ended) return { state, rejected: 'ended' };
	if (!state.plan.settings.backNavigation) return { state, rejected: 'back-disabled' };
	if (d.history.length <= 1) return { state, rejected: 'first-page' };
	return { state: commit(state, { type: 'back', t: now(state.clock), from: currentPage(d) }).state };
}

/**
 * Record the result of an effect and continue. A quota result must be `"open"` or `"full"`
 * and match the pending effect; anything else (stale, duplicate, wrong kind) is refused
 * and logged, and changes nothing else.
 */
export function resolve(state: State, effect: Effect, value: unknown): State {
	return tryResolve(state, effect, value).state;
}

export function tryResolve(state: State, effect: Effect, value: unknown): { state: State; rejected?: Rejection } {
	const d = state.data;
	const t = now(state.clock);
	const desc =
		effect?.kind === 'quota'
			? { kind: 'quota', nodeId: effect.nodeId }
			: effect?.kind === 'hook'
				? { kind: 'hook', invocationId: effect.invocationId }
				: { kind: String(effect?.kind) };
	let rejected: Rejection | undefined;
	if (effect?.kind === 'hook') rejected = 'unsupported'; // R7 seam: no hook actions yet
	else if (effect?.kind !== 'quota') rejected = 'unsupported';
	else if (!d.pending || d.pending.effect.nodeId !== effect.nodeId) rejected = 'stale';
	else if (value !== 'open' && value !== 'full') rejected = 'bad-result';
	const safeValue = typeof value === 'string' ? value.slice(0, 64) : null;
	const out = commit(state, { type: 'resolve', t, effect: desc, value: safeValue, ...(rejected ? { rejected } : {}) });
	return { state: out.state, rejected };
}

/** Switch the session language (one of the plan's languages). */
export function setLanguage(state: State, language: string): State {
	if (!state.plan.languages.includes(language) || language === state.data.language) return state;
	return commit(state, { type: 'language', t: now(state.clock), language }).state;
}

// --- Rendering -------------------------------------------------------------------------

function segmentsFor(plan: Plan, lang: string, text: Text | undefined | null): Segment[] {
	if (!text) return [];
	return text[lang] ?? text[plan.defaultLanguage] ?? Object.values(text)[0] ?? [];
}

/** Text without piping (pipes render empty): for choice labels inside a pipe. */
function plainText(plan: Plan, lang: string, text: Text | undefined): string {
	return segmentsFor(plan, lang, text)
		.map((s) => (typeof s === 'string' ? s : ''))
		.join('');
}

function formatValue(v: Value): string {
	if (v === null) return '';
	switch (v.k) {
		case 'num':
			return dec.toPlain(v.v);
		case 'bool':
			return v.v ? 'true' : 'false';
		case 'multi':
			return v.v.map(String).join(', ');
		default:
			return v.v;
	}
}

/** §8: choice label for choice answers, the raw value otherwise, empty when missing. */
function pipeText(plan: Plan, d: Data, env: Env, id: string): string {
	if (id.startsWith('$')) return formatValue(env.builtin(id));
	const item = plan.items[id];
	if (item) {
		if (!isQuestion(item)) return '';
		const stored = env.value(id);
		if (stored === null) return '';
		const label = (code: unknown) => {
			const c = item.choices?.find((ch) => ch.value === code);
			return c ? plainText(plan, d.language, c.label) : String(code);
		};
		if (item.type === 'single') return label(stored);
		// PROVISIONAL (R1-4, C3a-9): a multi answer pipes its labels in choice-list order,
		// joined with ", "; a decimal pipes as typed.
		if (item.type === 'multi') return (stored as ChoiceValue[]).map(label).join(', ');
		return String(stored);
	}
	return formatValue(env.lookup(id));
}

function render(plan: Plan, d: Data, env: Env, text: Text | undefined | null): RenderedText {
	const out: RenderedText = [];
	for (const s of segmentsFor(plan, d.language, text)) {
		if (typeof s === 'string') out.push({ kind: 'text', text: s });
		else out.push({ kind: 'value', text: pipeText(plan, d, env, s.pipe) });
	}
	return out;
}

const ESCAPES: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export function escapeHtml(s: string): string {
	return s.replace(/[&<>"']/g, (c) => ESCAPES[c]!);
}

/** HTML for rendered text: researcher text as is (sanitised at save), values escaped (§8). */
export function toHtml(text: RenderedText | null): string {
	if (!text) return '';
	return text.map((p) => (p.kind === 'value' ? escapeHtml(p.text) : p.text)).join('');
}

export function toPlain(text: RenderedText | null): string {
	return text ? text.map((p) => p.text).join('') : '';
}

function errorView(plan: Plan, d: Data, env: Env, id: Id, e: PageError) {
	const item = plan.items[id];
	const msg =
		e.kind === 'constraint' && item && isQuestion(item) && item.constraintMessage
			? render(plan, d, env, item.constraintMessage)
			: null;
	return { ...e, message: msg };
}

/** What to show now. Pure; call it after every state change. */
export function view(state: State): PageView {
	const { plan, data: d } = state;
	const env = new Env(plan, d);
	const page = currentPage(d);
	const items: ViewItem[] = [];
	const errors: PageView['errors'] = {};
	for (const [id, e] of Object.entries(d.errors)) errors[id] = errorView(plan, d, env, id, e);
	if (page !== null) {
		for (const id of displayOrder(plan, d, page)) {
			const item = plan.items[id];
			if (!item || !env.relevant(id)) continue;
			const q = isQuestion(item) ? (item as QuestionItem) : null;
			let choices: ViewItem['choices'] = null;
			if (q?.choices) {
				const order = d.orders.choices[id] ?? q.choices.map((c) => c.value);
				choices = order
					.map((v) => q.choices!.find((c) => c.value === v))
					.filter((c) => c !== undefined)
					.map((c) => ({ value: c.value, label: render(plan, d, env, c.label) }));
			}
			items.push({
				id,
				type: item.type,
				label: render(plan, d, env, item.label),
				help: item.help ? render(plan, d, env, item.help) : null,
				required: q?.required ?? false,
				state: q ? env.state(id) : null,
				value: q ? (d.values[id] ?? null) : null,
				error: errors[id] ?? null,
				choices
			});
		}
	}
	const endNode = d.ended?.nodeId ? index(plan).nodes.get(d.ended.nodeId) : undefined;
	return {
		status: d.ended ? 'ended' : d.pending ? 'pending' : 'page',
		page,
		block: page ? (plan.pages[page]?.block ?? null) : null,
		language: d.language,
		title: render(plan, d, env, plan.title),
		items,
		errors,
		nav: d.ended ? null : { back: canGoBack(state), next: !d.pending },
		focus: d.ended ? null : Object.keys(d.errors).length ? 'error-summary' : 'heading',
		effect: d.pending?.effect ?? endEffect(d),
		end: d.ended
			? {
					outcome: d.ended.outcome,
					message: endNode?.type === 'end' && endNode.message ? render(plan, d, env, endNode.message) : null
				}
			: null,
		trial: d.history.length,
		position: page ? position(plan, d, currentCursor(d)) : null
	};
}

// --- Results, context, snapshots -------------------------------------------------------

export function answers(state: State): Record<Id, AnswerRecord> {
	const env = new Env(state.plan, state.data);
	const out: Record<Id, AnswerRecord> = {};
	for (const id of state.plan.questions) out[id] = { state: env.state(id), value: env.value(id) };
	return out;
}

function variableValues(state: State) {
	const env = new Env(state.plan, state.data);
	const embedded: Record<Id, string | number | null> = {};
	const computed: Record<Id, string | boolean | null> = {};
	for (const v of Object.values(state.plan.variables)) {
		if (v.kind === 'embedded') embedded[v.id] = embeddedRaw(state.plan, state.data, v.id);
		if (v.kind === 'computed') {
			const r = env.lookup(v.id);
			computed[v.id] = r === null ? null : r.k === 'bool' ? r.v : formatValue(r);
		}
	}
	return { embedded, computed };
}

/** Conditions the server assigned at session start: what R2's submit checks against. */
function serverAssigned(d: Data): Record<Id, ChoiceValue> {
	const first = d.events[0];
	return first?.type === 'start' ? { ...first.assigned } : {};
}

/**
 * The response: values, per-question states, orders, event log and versions. `answers` is
 * `{questionId: {state, value}}` (semantics §1); `csvState` uses export names.
 */
export function result(state: State): ResponseRecord {
	const { plan, data: d } = state;
	const ans = answers(state);
	const csvState: Record<string, QuestionState> = {};
	for (const id of plan.questions) {
		const item = plan.items[id] as QuestionItem;
		csvState[`${item.name}__state`] = ans[id]!.state;
	}
	const { embedded, computed } = variableValues(state);
	const sources = Object.values(d.conditionSource);
	return {
		format: 'osp-response/1',
		surveyId: plan.survey.id,
		surveyVersion: plan.survey.version,
		planVersion: plan.planVersion,
		planChecksum: plan.checksum,
		engineVersion: ENGINE_VERSION,
		sessionSeed: d.sessionSeed,
		sessionId: d.sessionId,
		language: d.language,
		device: d.device,
		end: d.ended?.outcome ?? null,
		endNode: d.ended?.nodeId ?? null,
		// PROVISIONAL (R1-5): `seeded` when the engine drew any condition itself.
		allocation: sources.includes('seeded') ? 'seeded' : 'server',
		assigned: serverAssigned(d),
		conditions: { ...d.conditions },
		conditionSources: { ...d.conditionSource },
		orders: clone(d.orders),
		answers: ans,
		csvState,
		embedded,
		computed,
		quotas: { ...d.quotas },
		urlParams: { ...d.urlParams },
		startedAt: d.startedAt,
		endedAt: d.ended?.at ?? null,
		revision: d.revision,
		events: clone(d.events)
	};
}

/** Estimated total pages on the path, assuming current answers and open quotas. */
function estimatePages(state: State): number {
	const { plan } = state;
	const d = clone(state.data);
	if (d.ended) return d.history.length;
	let count = d.history.length;
	let cursor = clone(d.pending?.cursor ?? currentCursor(d));
	if (!d.pending) {
		const top = cursor[cursor.length - 1];
		if (top) top.i++;
	}
	d.pending = null;
	const limit = index(plan).pageCount + 2;
	for (let i = 0; i <= limit; i++) {
		const out = walk(plan, d, cursor, 0);
		if (out.kind === 'end') break;
		if (out.kind === 'effect') {
			d.quotas[d.pending!.effect.nodeId] = 'open';
			cursor = d.pending!.cursor;
			d.pending = null;
			continue;
		}
		count++;
		cursor = out.cursor;
		const top = cursor[cursor.length - 1];
		if (top) top.i++;
	}
	return count;
}

/** The read-only hook context (runtime-design.md §7a). `ctx.results` is filtered by R7. */
export function context(state: State): Ctx {
	const { plan, data: d } = state;
	const t = now(state.clock);
	const page = currentPage(d);
	const shownAt = d.history[d.history.length - 1]?.shownAt ?? d.startedAt;
	const env = new Env(plan, d);
	const vars: Ctx['vars'] = {};
	for (const v of Object.values(plan.variables)) {
		const r = env.lookup(v.id);
		vars[v.id] = r === null ? null : r.k === 'bool' ? r.v : r.k === 'num' && r.int ? Number(dec.toPlain(r.v)) : formatValue(r);
	}
	return {
		trial: d.history.length,
		trialId: page,
		blockId: page ? (plan.pages[page]?.block ?? null) : null,
		position: page ? position(plan, d, currentCursor(d)) : null,
		pagesDone: pagesDone(d),
		pagesEstimated: estimatePages(state),
		conditions: { ...d.conditions },
		language: d.language,
		device: d.device,
		elapsedMs: t - d.startedAt,
		trialElapsedMs: t - shownAt,
		results: answers(state),
		vars,
		sessionId: d.sessionId
	};
}

export function snapshot(state: State): Snapshot {
	return {
		format: 'osp-engine-snapshot/1',
		planChecksum: state.data.planChecksum,
		revision: state.data.revision,
		data: clone(state.data)
	};
}

/**
 * Rebuild a state from its event log alone (verification, R2's optional replay). The
 * recorded result of every `next`/`resolve` must come out the same.
 */
export function replay(plan: Plan, events: EngineEvent[], opts: { clock?: Clock } = {}): State | { error: { code: string; message: string } } {
	try {
		checkPlan(plan);
		const first = events[0];
		if (!first || first.type !== 'start') return { error: { code: 'replay.no_start', message: 'first event must be start' } };
		const d = initialData(plan, first);
		apply(plan, d, first);
		d.revision = 1;
		d.events.push(clone(first));
		for (let i = 1; i < events.length; i++) {
			const ev = clone(events[i]!);
			if (ev.seq !== i + 1 || ev.rev !== d.revision + 1) {
				return { error: { code: 'replay.sequence', message: `event ${i + 1} is out of sequence` } };
			}
			if (ev.rejected === undefined) {
				const res = apply(plan, d, ev);
				const recorded = ev.type === 'next' || ev.type === 'resolve' ? ev.result : undefined;
				if (canonicalJson(res ?? null) !== canonicalJson(recorded ?? null)) {
					return { error: { code: 'replay.diverged', message: `event ${i + 1} (${ev.type}) gave a different result` } };
				}
				if (ev.type === 'back' && ev.to !== currentPage(d)) {
					return { error: { code: 'replay.diverged', message: `event ${i + 1} (back) went elsewhere` } };
				}
			}
			d.revision += 1;
			d.events.push(ev);
		}
		const last = events[events.length - 1]!;
		return { plan, clock: opts.clock ?? (() => last.t), data: d };
	} catch (e) {
		const code = e instanceof EngineError ? e.code : 'replay.failed';
		return { error: { code, message: e instanceof Error ? e.message : String(e) } };
	}
}

/**
 * Restore a snapshot (refresh, resume, another device). The snapshot's event log is
 * replayed and must reproduce the snapshot exactly; otherwise `{ error }`.
 */
export function restore(plan: Plan, snap: unknown, opts: { clock?: Clock } = {}): State | { error: { code: string; message: string } } {
	try {
		const s = snap as Snapshot;
		if (!s || typeof s !== 'object' || s.format !== 'osp-engine-snapshot/1' || !s.data || !Array.isArray(s.data.events)) {
			return { error: { code: 'snapshot.format', message: 'not an engine snapshot' } };
		}
		if (s.planChecksum !== plan.checksum || s.data.planChecksum !== plan.checksum) {
			return { error: { code: 'snapshot.plan', message: 'snapshot belongs to another plan' } };
		}
		const r = replay(plan, s.data.events, opts);
		if ('error' in r) return r;
		if (canonicalJson(r.data) !== canonicalJson(s.data) || s.revision !== r.data.revision) {
			return { error: { code: 'snapshot.inconsistent', message: 'snapshot does not match its event log' } };
		}
		return r;
	} catch (e) {
		return { error: { code: 'snapshot.invalid', message: e instanceof Error ? e.message : String(e) } };
	}
}

export function isState(x: State | { error: unknown }): x is State {
	return !('error' in x);
}

export { matchChoice };
