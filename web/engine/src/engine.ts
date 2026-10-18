/**
 * The participant engine: a pure state machine over a runtime plan (runtime-design.md §3,
 * semantics.md). No DOM, no I/O, no Math.random, no Date.now: time comes from the
 * injected clock and randomness from `nodeSeed`.
 *
 * Every call that changes the state appends one event to the log and applies it with
 * `apply`; `replay` re-applies a log, so a state is exactly its events. `restore` replays
 * a snapshot's log and refuses the snapshot unless the result is identical.
 *
 * Rules implemented, with semantics.md sections:
 * - §1 states: not-reached (page never reached), irrelevant (reached, hidden, or its block
 *   dropped off the path), unanswered, answered. Once reached, a page stays reached.
 * - §3 a value that is irrelevant at a page submit is cleared then; until then a hidden
 *   value is kept (live show-if within a page). Clearing is a fixpoint: an irrelevant
 *   question is null to every expression, so dependants follow in the same submit.
 * - §3 a submit after going back that takes a reached page off the path (a branch now
 *   goes the other way, an earlier end now ends the session) makes that page's questions
 *   irrelevant and clears them (`offPath`).
 * - §3 runtime type mismatches and division by zero give null and are logged in
 *   `data.diagnostics` (and the response), never thrown.
 * - §4 required only while relevant; numeric min/max and constraints only on answered
 *   values; unreadable input blocks the page (`invalid`), even on an optional question;
 *   validation on page submit (`next`).
 * - §5 back keeps values and re-evaluates later pages when they are reached again. Back is
 *   refused while a quota call is pending.
 * - §6 a page whose page-level `showIf` is false, or with no relevant item, is skipped and
 *   its questions become irrelevant; a relevant note counts as content, so a notes-only page
 *   is shown. Skipping is per page. Running off the end of the flow is `end: complete`.
 * - §6 a quota check asks the server once per node while its `when` is true and reuses the
 *   recorded result on every later pass; `full` shows the `onFull` block, then ends.
 * - §7 realised orders are computed at first reach and stored before the page renders.
 *   Assigned conditions are null to expressions until their `assign` node is reached.
 * - §2 (C2c-1) a matrix stores nothing itself: each row is a `single` question with its own
 *   state, value and `required`, relevant exactly when the matrix is. (C2c-3) a slider is
 *   unanswered until set and stores an integer or decimal on its step grid.
 */

import { planChecksum, canonicalJson } from './canonical.ts';
import { evaluate, evaluateCondition, type DiagnosticSink, type Lookup, type Value } from './expr.ts';
import * as dec from './decimal.ts';
import {
	ENGINE_VERSION,
	CONSENT_PAGE,
	PLAN_VERSION,
	isMatrix,
	isQuestion,
	valueTypeOf,
	type BlockNode,
	type ChoiceValue,
	type Expr,
	type FlowNode,
	type Id,
	type Item,
	type Plan,
	type QuestionItem,
	type Segment,
	type RichBlock,
	type InlineRun,
	toBlocks,
	type Text
} from './plan.ts';
import { assign as drawCondition, checkSeed, nodeSeed, randomize, InvalidSeedError } from './random.ts';
import { fillRedirect, templateHost } from './redirect.ts';
import {
	EngineError,
	type AnswerRecord,
	type Clock,
	type Ctx,
	type Data,
	type Effect,
	type EndView,
	type EngineEvent,
	type ExternalEffect,
	type HookAction,
	type HookData,
	type HookEffect,
	type HookResolution,
	type Frame,
	type PageError,
	type PageView,
	type Position,
	type QuestionState,
	type QuotaResult,
	type RenderedRun,
	type RenderedText,
	type ResolvedRedirect,
	type ResponseRecord,
	type RuntimeDiagnostic,
	type Snapshot,
	type StartOptions,
	type State,
	type StepResult,
	type ViewItem,
	type ViewRow
} from './types.ts';
import { canonicalDecimal, checkAnswer, codeValue, matchChoice, toValue, trimAnswer, type Stored } from './values.ts';

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

// --- Runtime diagnostics ---------------------------------------------------------------

/**
 * Where diagnostics go while an event is applied (`apply` sets it; evaluation in `view`,
 * `result` and other read-only calls logs nothing). Single-threaded and synchronous.
 */
let collector: Data['diagnostics'] | null = null;

function logDiagnostic(d: RuntimeDiagnostic): void {
	if (!collector) return;
	if (collector.some((x) => x.site === d.site && x.code === d.code && x.path === d.path)) return;
	collector.push(d);
}

function sinkFor(site: string): DiagnosticSink | undefined {
	return collector ? (d) => logDiagnostic({ code: d.code, path: d.path, site }) : undefined;
}

// --- Evaluation environment ------------------------------------------------------------

const INT_TEXT = /^[+-]?\d+$/;

/**
 * An embedded variable's value (semantics.md §6, C3a-5): the URL parameter captured at
 * start if present, else the declared default. A malformed parameter is unanswered (null)
 * and logged; the participant is never blocked.
 */
function embeddedRaw(plan: Plan, data: Data, id: Id): string | number | null {
	const v = plan.variables[id];
	if (!v || v.kind !== 'embedded') return null;
	const fromUrl = Object.prototype.hasOwnProperty.call(data.urlParams, v.param);
	const raw: string | number | null = fromUrl ? (data.urlParams[v.param] ?? null) : v.default;
	if (raw === null || raw === undefined) return null;
	const text = typeof raw === 'number' ? String(raw) : trimAnswer(raw);
	if (text === '') return null;
	const malformed = () => {
		logDiagnostic({ code: 'embedded.malformed', path: '/', site: `variables.${id}` });
		return null;
	};
	if (v.valueType === 'integer') {
		if (!INT_TEXT.test(text)) return malformed();
		const n = Number(text);
		return Number.isSafeInteger(n) ? n : malformed();
	}
	if (v.valueType === 'decimal') return canonicalDecimal(text) ?? malformed();
	return text;
}

class Env {
	private rel = new Map<Id, boolean>();
	private pageRel = new Map<Id, boolean>();
	private comp = new Map<Id, Value>();
	private busy = new Set<string>();
	constructor(
		readonly plan: Plan,
		readonly data: Data,
		readonly cursor: Frame[] | null = null
	) {}

	cond(expr: Expr, site: string): boolean {
		return evaluateCondition(expr, this.lookup, sinkFor(site));
	}

	/** A reached page is relevant unless it is off the path or its own `showIf` is false. */
	pageRelevant(pageId: Id): boolean {
		const memo = this.pageRel.get(pageId);
		if (memo !== undefined) return memo;
		const page = this.plan.pages[pageId];
		let r = false;
		if (page && this.data.reachedPages[pageId] && !this.data.offPath[pageId]) {
			if (!page.showIf) r = true;
			else if (this.busy.has(`p:${pageId}`)) return false; // a cycle: never in a valid plan
			else {
				this.busy.add(`p:${pageId}`);
				r = this.cond(page.showIf, `pages.${pageId}.showIf`);
				this.busy.delete(`p:${pageId}`);
			}
		}
		this.pageRel.set(pageId, r);
		return r;
	}

	relevant(id: Id): boolean {
		const memo = this.rel.get(id);
		if (memo !== undefined) return memo;
		const item = this.plan.items[id];
		let r = false;
		if (item && isQuestion(item) && item.matrix !== undefined) {
			// §2 (C2c-1): a matrix row is relevant exactly when its matrix is.
			r = item.matrix !== id && isMatrix(this.plan.items[item.matrix]) && this.relevant(item.matrix);
		} else if (item && this.pageRelevant(item.page)) {
			if (!item.showIf) r = true;
			else if (this.busy.has(`r:${id}`)) return false; // a cycle: never in a valid plan
			else {
				this.busy.add(`r:${id}`);
				r = this.cond(item.showIf, `items.${id}.showIf`);
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
		if (item) return isQuestion(item) ? toValue(valueTypeOf(item), this.value(id)) : null;
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
				// §7 (C3a-7): null until the assign node is reached, although the value is fixed
				// at start and always recorded in the response.
				return this.data.assignReached[id] && id in this.data.conditions
					? codeValue(this.data.conditions[id])
					: null;
			case 'computed': {
				// §2 (C2-6): recomputed from current values whenever read.
				const memo = this.comp.get(id);
				if (memo !== undefined) return memo;
				if (this.busy.has(`c:${id}`)) return null;
				this.busy.add(`c:${id}`);
				const r = evaluate(v.expr, this.lookup, sinkFor(`variables.${id}.expr`));
				this.busy.delete(`c:${id}`);
				this.comp.set(id, r);
				return r;
			}
			case 'hook':
				return hookValue(v.valueType, this.data.hooks?.vars[id] ?? null);
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
			// Ending-only built-ins (end-of-survey plan §4.2, EN2); empty until the session ends.
			case '$session.id':
				return text(d.ended ? d.sessionId : null);
			case '$outcome':
				return text(d.ended?.outcome ?? null);
			case '$response.id':
				return text(d.ended ? (d.responseId ?? null) : null);
		}
		return null;
	}
}

/** A hook variable's stored value as an expression value (null when unset or mistyped). */
function hookValue(type: 'text' | 'integer' | 'decimal' | 'boolean', v: string | number | boolean | null): Value {
	if (v === null) return null;
	if (type === 'boolean') return typeof v === 'boolean' ? { k: 'bool', v } : null;
	if (type === 'integer') return typeof v === 'number' && Number.isSafeInteger(v) ? toValue('integer', v) : null;
	if (type === 'decimal') return typeof v === 'string' ? toValue('decimal', v) : null;
	return typeof v === 'string' ? toValue('text', v) : null;
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
function enterPage(plan: Plan, d: Data, pageId: Id, entered?: Set<Id>): void {
	const page = plan.pages[pageId];
	d.reachedPages[pageId] = true;
	entered?.add(pageId);
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
	return env.pageRelevant(pageId) && (plan.pages[pageId]?.items ?? []).some((id) => env.relevant(id));
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
function walk(plan: Plan, d: Data, cursor: Frame[], t: number, entered?: Set<Id>): WalkOutcome {
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
			enterPage(plan, d, pageId, entered);
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
				const yes = new Env(plan, d, cursor).cond(node.if, `flow.${node.id}.if`);
				cursor.push({ k: `${yes ? 'then' : 'else'}:${node.id}`, i: 0 });
				break;
			}
			case 'randomiser': {
				if (!d.orders.blocks[node.id]) {
					// §7 (C2-4): `pick` takes the first `pick` children of the seeded shuffle
					// (a uniform draw without replacement), frozen at first reach.
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
				// §6 (C3a-3, C2-7, R6-4): the check applies only while `when` is true; the
				// server result is asked once per node and then reused (idempotent, also on
				// replay); `full` shows the onFull block's pages, then ends with its outcome.
				const applies = quota ? new Env(plan, d, cursor).cond(quota.when, `quotas.${quota.id}.when`) : false;
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
			case 'externalTask': {
				// Task EX2: like a quota check, the hop runs once. Its recorded result (the
				// captured return values) is reused on back, refresh and replay. Until then it
				// is an effect: the runtime mints a return token, sends the participant out and
				// resolves on return (or at once with no values when the URL cannot be built).
				if (d.external?.[node.id]) {
					top.i++;
					break;
				}
				d.pending = {
					effect: externalEffect(plan, d, new Env(plan, d, cursor), node),
					cursor: clone(cursor)
				};
				return { kind: 'effect' };
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

/** Item ids with every matrix replaced by its rows (C2c-1). */
function withRows(plan: Plan, ids: Id[]): Id[] {
	return ids.flatMap((id) => {
		const item = plan.items[id];
		return isMatrix(item) ? item.rows : [id];
	});
}

function validate(plan: Plan, d: Data, pageId: Id): Record<Id, PageError> {
	const env = new Env(plan, d);
	const errors: Record<Id, PageError> = {};
	for (const id of withRows(plan, displayOrder(plan, d, pageId))) {
		const item = plan.items[id];
		if (!item || !isQuestion(item) || !env.relevant(id)) continue;
		// §4 (R1-4): unreadable input blocks the page, even on an optional question.
		const bad = d.invalid[id];
		if (bad !== undefined) errors[id] = { kind: 'invalid', code: bad };
		else if (env.value(id) === null) {
			if (item.required) errors[id] = { kind: 'required' };
		} else if (!inRange(item, env.lookup(id))) {
			errors[id] = { kind: 'range' };
		} else if (item.constraint && !env.cond(item.constraint, `items.${id}.constraint`)) {
			errors[id] = { kind: 'constraint' };
		}
	}
	return errors;
}

/** §4: numeric `min` / `max` (inclusive) on an answered integer or decimal. */
function inRange(item: QuestionItem, v: Value): boolean {
	if (v === null || v.k !== 'num') return true;
	const bound = (b: number | string | undefined) =>
		b === undefined ? null : typeof b === 'number' ? dec.fromInteger(b) : dec.parseDecimal(b);
	const lo = bound(item.min);
	const hi = bound(item.max);
	if (lo !== null && dec.cmp(v.v, lo) < 0) return false;
	if (hi !== null && dec.cmp(v.v, hi) > 0) return false;
	return true;
}

/**
 * §3 (C3a-6): the reached pages that are no longer on the participant's path, given the
 * current answers. The path is re-walked from the start, passing every page (shown or
 * not yet reached), with recorded quota results and an unrecorded quota taken as open
 * (so an uncertain future never clears anything). Iterated to a fixpoint, because answers
 * on a page that drops off are null to every later branch.
 */
function offPathPages(plan: Plan, d: Data): Record<Id, true> {
	const outer = collector;
	collector = null; // a simulation: nothing it evaluates is logged
	try {
		return offPathFixpoint(plan, d);
	} finally {
		collector = outer;
	}
}

function offPathFixpoint(plan: Plan, d: Data): Record<Id, true> {
	let off: Record<Id, true> = {};
	const limit = index(plan).pageCount + 2;
	for (let round = 0; round <= limit; round++) {
		const dd: Data = clone({ ...d, events: [], diagnostics: [], offPath: off, pending: null, ended: null });
		const seen = new Set<Id>();
		let cursor: Frame[] = [{ k: 'root', i: 0 }];
		for (let i = 0; i <= limit; i++) {
			const out = walk(plan, dd, cursor, 0, seen);
			if (out.kind === 'end') break;
			if (out.kind === 'effect') {
				{
						const eff = dd.pending!.effect;
						if (eff.kind === 'quota') dd.quotas[eff.nodeId] = 'open';
						else (dd.external ??= {})[eff.nodeId] = { returned: {} };
					}
				cursor = dd.pending!.cursor;
				dd.pending = null;
				continue;
			}
			cursor = out.cursor;
			const top = cursor[cursor.length - 1];
			if (top) top.i++;
		}
		const next: Record<Id, true> = {};
		for (const p of Object.keys(d.reachedPages)) if (!seen.has(p)) next[p] = true;
		if (canonicalJson(next) === canonicalJson(off)) return next;
		off = next;
	}
	return off;
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

/** Re-evaluate every question's state (a page change). Passes `r` through. */
function pageChanged<T>(plan: Plan, d: Data, r: T): T {
	const env = new Env(plan, d);
	const frozen: Record<Id, QuestionState> = {};
	for (const id of plan.questions) frozen[id] = env.state(id);
	d.frozen = frozen;
	return r;
}

/** The reported state: live on the current page, as of the last page change elsewhere. */
function reportedState(plan: Plan, d: Data, env: Env, id: Id): QuestionState {
	const page = currentPage(d);
	if (page !== null && plan.items[id]?.page === page) return env.state(id);
	return d.frozen[id] ?? env.state(id);
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
		offPath: {},
		conditions: {},
		conditionSource: {},
		assignReached: {},
		orders: { blocks: {}, items: {}, choices: {} },
		quotas: {},
		history: [],
		pending: null,
		errors: {},
		frozen: {},
		ended: null,
		diagnostics: [],
		events: []
	};
	for (const v of Object.values(plan.variables)) {
		if (v.kind !== 'assigned') continue;
		if (Object.prototype.hasOwnProperty.call(ev.assigned, v.id)) {
			d.conditions[v.id] = ev.assigned[v.id]!;
			d.conditionSource[v.id] = 'server';
		} else {
			// §7 (C2-5, R1-8): an independent uniform seeded draw per variable, on the stream
			// `seedNode` (`<assign node>/<variable>`), exactly as the server's simple
			// assignment, recorded as `seeded` for that variable. Drawn at start, so it never
			// re-rolls. Normally the server sends every level and this is not used.
			const seed = nodeSeed(seedVersion(plan), ev.sessionSeed, v.seedNode || v.id);
			d.conditions[v.id] = drawCondition(v.levels, null, seed);
			d.conditionSource[v.id] = 'seeded';
		}
	}
	return d;
}

/**
 * Apply one (non-rejected) event to `d` in place. Returns the step result, if any. Runtime
 * diagnostics raised while applying it are appended to `d.diagnostics`.
 */
function apply(plan: Plan, d: Data, ev: EngineEvent): StepResult | undefined {
	const outer = collector;
	collector = d.diagnostics;
	try {
		return applyEvent(plan, d, ev);
	} finally {
		collector = outer;
	}
}

function applyEvent(plan: Plan, d: Data, ev: EngineEvent): StepResult | undefined {
	switch (ev.type) {
		case 'start': {
			for (const v of Object.values(plan.variables)) if (v.kind === 'embedded') embeddedRaw(plan, d, v.id);
			// semantics.md §11: with a consent page, the flow starts only once they agree.
			if (plan.consent) return pageChanged(plan, d, undefined);
			const out = walk(plan, d, [{ k: 'root', i: 0 }], ev.t);
			return pageChanged(plan, d, finishWalk(d, out, ev.t));
		}
		case 'consent': {
			const c = plan.consent;
			if (!c || d.consent || d.ended) return undefined;
			d.consent = { decision: ev.decision, version: ev.version, at: ev.t };
			if (ev.decision === 'decline') {
				d.ended = { outcome: c.declineOutcome, nodeId: null, at: ev.t };
				return { outcome: 'ended', to: null, effect: endEffect(d)! };
			}
			const out = walk(plan, d, [{ k: 'root', i: 0 }], ev.t);
			return pageChanged(plan, d, finishWalk(d, out, ev.t));
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
			dropHiddenErrors(plan, d);
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
			d.offPath = offPathPages(plan, d);
			clearIrrelevant(plan, d);
			const cursor = clone(currentCursor(d));
			const top = cursor[cursor.length - 1];
			if (top) top.i++;
			return pageChanged(plan, d, finishWalk(d, walk(plan, d, cursor, ev.t), ev.t));
		}
		case 'back':
			d.pending = null;
			d.errors = {};
			d.history.pop();
			pageChanged(plan, d, undefined);
			return undefined;
		case 'resolve': {
			if (ev.effect.kind === 'hook') return applyHook(plan, d, ev.effect.event ?? '', ev.value as HookResolution, ev.t);
			if (ev.effect.kind === 'external') return applyExternal(plan, d, ev);
			const p = d.pending;
			if (!p || ev.effect.kind !== 'quota') return undefined;
			d.quotas[p.effect.nodeId] = ev.value as QuotaResult;
			d.pending = null;
			return pageChanged(plan, d, finishWalk(d, walk(plan, d, clone(p.cursor), ev.t), ev.t));
		}
		case 'language':
			d.language = ev.language;
			return undefined;
	}
}

// --- Researcher hooks (R7, runtime-design.md §7a) ---------------------------------------

/** Outcome of a flow-critical hook that failed after its retry. */
export const HOOK_FAILED_OUTCOME = 'hook-failed';
const HOOK_AFTER_END = new Set(['onBeforeSubmit', 'onSubmitted']);
const PARADATA_KEY = /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/;
const MAX_HOOK_TEXT = 2000;

function hookData(d: Data): HookData {
	if (!d.hooks) d.hooks = { vars: {}, paradata: [], redirect: null, parentMessages: 0 };
	return d.hooks;
}

/** Apply a recorded (already checked) hook resolution. Replay uses this; it runs no code. */
function applyHook(plan: Plan, d: Data, event: string, r: HookResolution, t: number): StepResult | undefined {
	const h = hookData(d);
	for (const a of r.actions) {
		switch (a.kind) {
			case 'setVariable':
				h.vars[a.id] = a.value;
				break;
			case 'addParadata':
				h.paradata.push({ key: a.key, value: a.value, event });
				break;
			case 'rejectPage': {
				const page = currentPage(d);
				if (page !== null) d.errors[a.itemId ?? page] = { kind: 'hook', text: a.message };
				break;
			}
			case 'setEndRedirect':
				h.redirect = { templateId: a.templateId, params: { ...a.params } };
				break;
			case 'postToParent':
				h.parentMessages += 1;
				break;
		}
	}
	if (r.status === 'fatal' && !d.ended) {
		d.pending = null;
		d.ended = { outcome: HOOK_FAILED_OUTCOME, nodeId: null, at: t };
		return pageChanged(plan, d, { outcome: 'ended', to: null, effect: endEffect(d)! });
	}
	return undefined;
}

const isPrimitive = (v: unknown): v is string | number | boolean | null =>
	v === null ||
	typeof v === 'boolean' ||
	(typeof v === 'number' && Number.isFinite(v)) ||
	(typeof v === 'string' && v.length <= MAX_HOOK_TEXT);

function checkHookAction(plan: Plan, d: Data, event: string, a: unknown): HookAction | null {
	if (!a || typeof a !== 'object') return null;
	const x = a as Record<string, unknown>;
	const str = (v: unknown, max: number) => typeof v === 'string' && v.length > 0 && v.length <= max;
	const afterSubmit = event === 'onSubmitted';
	switch (x.kind) {
		case 'setVariable': {
			const v = typeof x.id === 'string' ? plan.variables[x.id] : undefined;
			if (afterSubmit || !v || v.kind !== 'hook' || !isPrimitive(x.value)) return null;
			const val = x.value;
			const ok =
				val === null ||
				(v.valueType === 'boolean' && typeof val === 'boolean') ||
				(v.valueType === 'integer' && typeof val === 'number' && Number.isSafeInteger(val)) ||
				(v.valueType === 'decimal' && typeof val === 'string' && dec.parseDecimal(val) !== null) ||
				(v.valueType === 'text' && typeof val === 'string');
			return ok ? { kind: 'setVariable', id: v.id, value: val } : null;
		}
		case 'addParadata':
			if (afterSubmit || typeof x.key !== 'string' || !PARADATA_KEY.test(x.key) || !isPrimitive(x.value)) return null;
			return { kind: 'addParadata', key: x.key, value: x.value };
		case 'rejectPage': {
			const page = currentPage(d);
			const itemId = x.itemId === undefined ? null : x.itemId;
			if (event !== 'onPageNext' || page === null || !str(x.message, 500)) return null;
			if (itemId !== null && (typeof itemId !== 'string' || plan.items[itemId]?.page !== page)) return null;
			return { kind: 'rejectPage', itemId, message: x.message as string };
		}
		case 'setEndRedirect': {
			if (!str(x.templateId, 64) || !x.params || typeof x.params !== 'object' || Array.isArray(x.params)) return null;
			const entries = Object.entries(x.params as Record<string, unknown>);
			if (entries.length > 16 || entries.some(([k, v]) => !str(k, 64) || typeof v !== 'string' || v.length > 256)) return null;
			return { kind: 'setEndRedirect', templateId: x.templateId as string, params: Object.fromEntries(entries) as Record<string, string> };
		}
		case 'postToParent': {
			if (!str(x.type, 64)) return null;
			let size: number;
			try {
				size = canonicalJson(x.payload ?? null).length;
			} catch {
				return null;
			}
			return size <= 8192 ? { kind: 'postToParent', type: x.type as string, payload: clone(x.payload ?? null) } : null;
		}
	}
	return null;
}

/** The engine's own check of a hook result (the host validates first; this guards the log). */
function checkHookResolution(plan: Plan, d: Data, event: string, value: unknown): HookResolution | null {
	if (!value || typeof value !== 'object') return null;
	const r = value as Record<string, unknown>;
	if (r.status !== 'ok' && r.status !== 'failed' && r.status !== 'fatal') return null;
	if (!Array.isArray(r.actions) || r.actions.length > 64) return null;
	if (r.status !== 'ok' && r.actions.length) return null;
	if (typeof r.seed !== 'number' || !Number.isSafeInteger(r.seed)) return null;
	if (typeof r.now !== 'number' || !Number.isFinite(r.now)) return null;
	const actions: HookAction[] = [];
	for (const a of r.actions) {
		const ok = checkHookAction(plan, d, event, a);
		if (!ok) return null;
		actions.push(ok);
	}
	const out: HookResolution = { status: r.status, actions, seed: r.seed, now: r.now };
	if (r.error !== undefined) {
		if (typeof r.error !== 'string' || r.error.length > 200) return null;
		out.error = r.error;
	}
	if (r.diagnostics !== undefined) {
		const ds = r.diagnostics;
		if (!Array.isArray(ds) || ds.length > 64 || ds.some((x) => typeof x !== 'string' || x.length > 200)) return null;
		out.diagnostics = [...(ds as string[])];
	}
	return out;
}

type NewEvent = EngineEvent extends infer E ? (E extends EngineEvent ? Omit<E, 'seq' | 'rev'> : never) : never;

/**
 * An answer can hide another question on the page (live show-if). The error a failed Next
 * left on it goes with it: a hidden question is never demanded (semantics §4, `required`
 * applies only while relevant). Since SEM1's two-valued logic, clearing an answer hides
 * questions whose `showIf` compares it (`null != 0` is false), so this case is reachable.
 * Page-level errors (a hook's rejectPage, keyed by page id) stay.
 */
function dropHiddenErrors(plan: Plan, d: Data) {
	const ids = Object.keys(d.errors).filter((id) => plan.items[id] !== undefined);
	if (!ids.length) return;
	const env = new Env(plan, d);
	for (const id of ids) if (!env.relevant(id)) delete d.errors[id];
}

function commit(state: State, partial: NewEvent): { state: State; result?: StepResult } {
	const d = clone(state.data);
	const ev = { ...partial, seq: d.events.length + 1, rev: d.revision + 1 } as EngineEvent;
	let result: StepResult | undefined;
	if (ev.rejected === undefined) result = apply(state.plan, d, ev);
	if (result !== undefined && (ev.type === 'next' || ev.type === 'resolve' || ev.type === 'consent')) ev.result = result;
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

/**
 * §5 (R6-5): start the same session again from the beginning, for an `end-only` session
 * whose only copy was in memory and is lost on refresh: the same seed, server conditions,
 * language, device, URL parameters and session id, so orders and assignment repeat. The
 * runtime shows the participant a notice.
 */
export function restart(state: State, opts: { clock?: Clock } = {}): State {
	const first = state.data.events[0];
	if (!first || first.type !== 'start') throw new EngineError('state.invalid', 'state has no start event');
	return start(state.plan, {
		sessionSeed: first.sessionSeed,
		assigned: first.assigned,
		clock: opts.clock ?? state.clock,
		language: first.language,
		device: first.device,
		urlParams: first.urlParams,
		sessionId: first.sessionId
	});
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
	| 'unknown-language'
	/** semantics.md §11: the consent page is still shown. */
	| 'consent-pending'
	/** There is no consent page, or the participant already decided. */
	| 'no-consent';

/** The consent page is shown: the plan has one and the participant has not decided. */
export function awaitingConsent(state: State): boolean {
	return !!state.plan.consent && !state.data.consent && !state.data.ended;
}

/** The participant declined consent (the session records no response). */
export function declinedConsent(state: State): boolean {
	return state.data.consent?.decision === 'decline';
}

/**
 * The participant's decision on the consent page (semantics.md §11). `agree` starts the
 * flow; `decline` ends the session with the plan's `declineOutcome`. Refused (and
 * unchanged) without a consent page or once decided.
 */
export function tryConsent(state: State, decision: 'agree' | 'decline'): { state: State; rejected?: Rejection } {
	const c = state.plan.consent;
	if (!c || !awaitingConsent(state)) return { state, rejected: 'no-consent' };
	if (decision !== 'agree' && decision !== 'decline') return { state, rejected: 'bad-result' };
	return { state: commit(state, { type: 'consent', t: now(state.clock), decision, version: c.version }).state };
}

export function agree(state: State): State {
	return tryConsent(state, 'agree').state;
}

export function decline(state: State): State {
	return tryConsent(state, 'decline').state;
}

/** `answer`, also saying why a call was refused (refusals change nothing). */
export function tryAnswer(state: State, itemId: Id, value: unknown): { state: State; rejected?: Rejection } {
	const d = state.data;
	const page = currentPage(d);
	let rejected: Rejection | undefined;
	const item: Item | undefined = state.plan.items[itemId];
	if (d.ended) rejected = 'ended';
	else if (awaitingConsent(state)) rejected = 'consent-pending';
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
	// The consent page is answered with agree/decline, never with Next (semantics.md §11).
	if (awaitingConsent(state)) return { state, result: { outcome: 'invalid', to: null } };
	const out = commit(state, { type: 'next', t: now(state.clock), from: currentPage(d) });
	const result = out.result ?? { outcome: 'invalid' as const };
	return { state: out.state, effect: result.effect, result };
}

/** §5 (R6-4): back is allowed by the survey, there is a page to go to, and no call is pending. */
export function canGoBack(state: State): boolean {
	const d = state.data;
	return !d.ended && !d.pending && state.plan.settings.backNavigation && d.history.length > 1;
}

/** Go to the previous shown page, keeping values (§5). Refused calls return `state`. */
export function back(state: State): State {
	return tryBack(state).state;
}

export function tryBack(state: State): { state: State; rejected?: Rejection } {
	const d = state.data;
	if (d.ended) return { state, rejected: 'ended' };
	if (d.pending) return { state, rejected: 'pending' };
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
	if (effect?.kind === 'hook') return tryResolveHook(state, effect, value, t);
	if (effect?.kind === 'external') return tryResolveExternal(state, effect, value, t);
	let rejected: Rejection | undefined;
	if (effect?.kind !== 'quota') rejected = 'unsupported';
	else if (!d.pending || d.pending.effect.nodeId !== effect.nodeId) rejected = 'stale';
	else if (value !== 'open' && value !== 'full') rejected = 'bad-result';
	const safeValue = typeof value === 'string' ? value.slice(0, 64) : null;
	const out = commit(state, { type: 'resolve', t, effect: desc, value: safeValue, ...(rejected ? { rejected } : {}) });
	return { state: out.state, rejected };
}

/** The whitelisted return values for an external resolve: string→string, length-capped. */
function sanitizeReturnValue(value: unknown): { params: Record<string, string> } {
	const out: Record<string, string> = {};
	const params = (value as { params?: unknown } | null)?.params;
	if (params && typeof params === 'object' && !Array.isArray(params)) {
		for (const [k, v] of Object.entries(params as Record<string, unknown>)) {
			if (typeof v === 'string' && k.length <= 100 && v.length <= 2000) out[k] = v;
		}
	}
	return { params: out };
}

/**
 * Record an external-task return (task EX2). Refused as `stale` when the state has moved on
 * since the hop was pending (a second return then changes nothing: same-context replay). The
 * engine filters the values to the node's declared `returns` when applying the event.
 */
function tryResolveExternal(
	state: State,
	effect: ExternalEffect,
	value: unknown,
	t: number
): { state: State; rejected?: Rejection } {
	const d = state.data;
	const desc = { kind: 'external', nodeId: effect.nodeId };
	const stale = !d.pending || d.pending.effect.kind !== 'external' || d.pending.effect.nodeId !== effect.nodeId;
	const rejected: Rejection | undefined = stale ? 'stale' : undefined;
	const out = commit(state, {
		type: 'resolve',
		t,
		effect: desc,
		value: rejected ? null : sanitizeReturnValue(value),
		...(rejected ? { rejected } : {})
	});
	return { state: out.state, rejected };
}

/**
 * Record a hook outcome (R7). Refused, and logged, when the state has moved on since the
 * hook was invoked (`stale`), when the invocation was already recorded, after the end
 * (except `onBeforeSubmit`/`onSubmitted`), or when the result is malformed.
 */
function tryResolveHook(state: State, effect: HookEffect, value: unknown, t: number): { state: State; rejected?: Rejection } {
	const d = state.data;
	const event = typeof effect.event === 'string' ? effect.event.slice(0, 64) : '';
	const invocationId = typeof effect.invocationId === 'string' ? effect.invocationId.slice(0, 128) : '';
	const desc = { kind: 'hook', invocationId, event, revision: Number(effect.revision) };
	const seen = d.events.some(
		(e) => e.type === 'resolve' && e.rejected === undefined && e.effect.kind === 'hook' && e.effect.invocationId === invocationId
	);
	let rejected: Rejection | undefined;
	let checked: HookResolution | null = null;
	if (!invocationId || !event) rejected = 'bad-result';
	else if (effect.revision !== d.revision || seen) rejected = 'stale';
	else if (d.ended && !HOOK_AFTER_END.has(event)) rejected = 'ended';
	else if (!(checked = checkHookResolution(state.plan, d, event, value))) rejected = 'bad-result';
	const out = commit(state, { type: 'resolve', t, effect: desc, value: rejected ? null : checked, ...(rejected ? { rejected } : {}) });
	return { state: out.state, rejected };
}

/** Switch the session language (one of the plan's languages). */
export function setLanguage(state: State, language: string): State {
	if (!state.plan.languages.includes(language) || language === state.data.language) return state;
	return commit(state, { type: 'language', t: now(state.clock), language }).state;
}

// --- Rendering -------------------------------------------------------------------------

function segmentsFor(plan: Plan, lang: string, text: Text | undefined | null): Segment[] | RichBlock[] {
	if (!text) return [];
	return text[lang] ?? text[plan.defaultLanguage] ?? Object.values(text)[0] ?? [];
}

/** The text in `lang` as blocks (a plain string is one paragraph; planning/rich-text.md §7). */
function blocksFor(plan: Plan, lang: string, text: Text | undefined | null): RichBlock[] {
	return toBlocks(segmentsFor(plan, lang, text));
}

function runsOf(block: RichBlock): InlineRun[] {
	return 'items' in block ? block.items.flat() : block.content;
}

/** Text without piping or formatting (pipes render empty): for choice labels inside a pipe. */
function plainText(plan: Plan, lang: string, text: Text | undefined): string {
	return blocksFor(plan, lang, text)
		.flatMap(runsOf)
		.map((r) => ('text' in r ? r.text : ''))
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
		// §8 (C3a-9): a multi answer pipes its labels in the order they were displayed (the
		// realised choice order), joined with ", "; a decimal pipes in canonical form, which
		// is how it is stored.
		if (item.type === 'multi') {
			const picked = stored as ChoiceValue[];
			const shown = d.orders.choices[id] ?? (item.choices ?? []).map((c) => c.value);
			return shown.filter((v) => picked.includes(v)).map(label).join(', ');
		}
		return String(stored);
	}
	return formatValue(env.lookup(id));
}

/** Rendered blocks: every pipe filled (semantics.md §8), formatting kept. */
function render(plan: Plan, d: Data, env: Env, text: Text | undefined | null): RenderedText {
	const run = (n: InlineRun): RenderedRun => {
		if ('pipe' in n) return { kind: 'value', text: pipeText(plan, d, env, n.pipe) };
		if ('br' in n) return { kind: 'br' };
		return { kind: 'text', ...n };
	};
	return blocksFor(plan, d.language, text).map((b) =>
		'items' in b ? { type: b.type, items: b.items.map((i) => i.map(run)) } : { ...b, content: b.content.map(run) }
	);
}

/** A participant-supplied string (a hook's message) as rendered text: one `value` run. */
export function valueText(text: string): RenderedText {
	return [{ type: 'p', content: [{ kind: 'value', text }] }];
}

const ESCAPES: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export function escapeHtml(s: string): string {
	return s.replace(/[&<>"']/g, (c) => ESCAPES[c]!);
}

function runsHtml(runs: RenderedRun[]): string {
	let out = '';
	let i = 0;
	while (i < runs.length) {
		const r = runs[i]!;
		if (r.kind === 'br') {
			out += '<br>';
			i++;
			continue;
		}
		if (r.kind === 'value') {
			out += escapeHtml(r.text);
			i++;
			continue;
		}
		if (r.href) {
			// Adjacent runs with the same href are one link (planning/rich-text.md §3.1).
			let inner = '';
			const href = r.href;
			while (i < runs.length) {
				const n = runs[i]!;
				if (n.kind !== 'text' || n.href !== href) break;
				inner += runHtml({ ...n, href: undefined });
				i++;
			}
			out += `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${inner}</a>`;
			continue;
		}
		out += runHtml(r);
		i++;
	}
	return out;
}

function runHtml(r: Extract<RenderedRun, { kind: 'text' }>): string {
	// Researcher text is written as it is (fixtures/FORMAT.md §3: traces keep plain text
	// byte-identical); the structure is our own tags only; attribute values are escaped.
	let s = r.text;
	if (r.marks?.includes('i')) s = `<em>${s}</em>`;
	if (r.marks?.includes('b')) s = `<strong>${s}</strong>`;
	if (r.lang) s = `<span lang="${escapeHtml(r.lang)}">${s}</span>`;
	return s;
}

/**
 * HTML for rendered text, as fixture traces record it (fixtures/FORMAT.md §3): researcher
 * text as written, piped values escaped (§8), formatting as our own tags (`strong`, `em`,
 * `a` with `target="_blank" rel="noopener noreferrer"`, `span lang`, `br`, `p`, `h3`–`h5`,
 * `ul`/`ol`/`li`). A single paragraph has no `<p>` wrapper, so every trace written before
 * RT2 is unchanged. Never rendered by the runtime, which builds text nodes from the blocks.
 */
export function toHtml(text: RenderedText | null): string {
	if (!text) return '';
	if (text.length === 1 && text[0]!.type === 'p') return runsHtml(text[0]!.content);
	return text
		.map((b) => {
			if (b.type === 'p') return `<p>${runsHtml(b.content)}</p>`;
			if (b.type === 'h') return `<h${b.level + 2}>${runsHtml(b.content)}</h${b.level + 2}>`;
			return `<${b.type}>${b.items.map((i) => `<li>${runsHtml(i)}</li>`).join('')}</${b.type}>`;
		})
		.join('');
}

function runsPlain(runs: RenderedRun[]): string {
	return runs.map((r) => (r.kind === 'br' ? '\n' : r.text)).join('');
}

/** Plain text of rendered blocks: blocks separated by a blank line, list items by a newline. */
export function toPlain(text: RenderedText | null): string {
	if (!text) return '';
	return text
		.map((b) => ('items' in b ? b.items.map(runsPlain).join('\n') : runsPlain(b.content)))
		.join('\n\n');
}

// --- External task (task EX2, planning/external-tasks.md) ------------------------------

/** The pending external effect for a node: the outbound URL filled like a redirect. */
function externalEffect(
	plan: Plan,
	d: Data,
	env: Env,
	node: Extract<FlowNode, { type: 'externalTask' }>
): ExternalEffect {
	const returns = node.returns ?? [];
	const t = Object.prototype.hasOwnProperty.call(plan.redirectTemplates ?? {}, node.template)
		? plan.redirectTemplates![node.template]
		: undefined;
	if (!t) return { kind: 'external', nodeId: node.id, url: null, rejected: '$template', host: '', returns };
	const values: Record<string, string> = {};
	for (const [name, segs] of Object.entries(node.params)) {
		values[name] = segs.map((s) => (typeof s === 'string' ? s : pipeText(plan, d, env, s.pipe))).join('');
	}
	const filled = fillRedirect(t, values);
	return { kind: 'external', nodeId: node.id, url: filled.url, rejected: filled.rejected, host: templateHost(t.url), returns };
}

/**
 * Record an external-task return (task EX2): capture the whitelisted values into the
 * session's URL parameters (each into the matching embedded variable), mark the node
 * resolved so it never runs twice, note a rejected outbound URL, then walk on.
 */
function applyExternal(plan: Plan, d: Data, ev: Extract<EngineEvent, { type: 'resolve' }>): StepResult | undefined {
	const p = d.pending;
	if (!p || p.effect.kind !== 'external') return undefined;
	const node = index(plan).nodes.get(p.effect.nodeId);
	const returns = node?.type === 'externalTask' ? node.returns : [];
	const incoming = (ev.value as { params?: Record<string, string> } | null)?.params ?? {};
	const captured: Record<string, string> = {};
	for (const r of returns) {
		if (Object.prototype.hasOwnProperty.call(incoming, r.param) && typeof incoming[r.param] === 'string') {
			captured[r.param] = incoming[r.param]!;
			d.urlParams[r.param] = incoming[r.param]!; // the embedded variable reads it (semantics §1)
		}
	}
	(d.external ??= {})[p.effect.nodeId] = { returned: captured };
	if (p.effect.rejected) {
		logDiagnostic({ code: 'external.param_rejected', site: `flow.${p.effect.nodeId}`, path: `/${p.effect.rejected}` });
	}
	d.pending = null;
	return pageChanged(plan, d, finishWalk(d, walk(plan, d, clone(p.cursor), ev.t), ev.t));
}

/**
 * The ending screen for an ended session (end-of-survey plan §4.1): the end node's message,
 * the outcome's ending with its pipes filled (semantics.md §8), and the truthful status line.
 */
function endView(state: State, env: Env, endNode: FlowNode | undefined): EndView {
	const { plan, data: d } = state;
	const outcome = d.ended!.outcome;
	const ending = plan.endings?.[outcome];
	const declined = declinedConsent(state);
	return {
		outcome,
		message: endNode?.type === 'end' && endNode.message ? render(plan, d, env, endNode.message) : null,
		ending: ending
			? {
					title: ending.title ? render(plan, d, env, ending.title) : null,
					body: ending.body ? render(plan, d, env, ending.body) : null,
					summary: ending.summary
				}
			: null,
		// A decline kept nothing, and the screen must say so whatever the ending sets.
		status: declined ? 'not-recorded' : ending?.status === 'none' ? null : 'recorded',
		redirect: resolveRedirect(plan, d, env, outcome)
	};
}

/**
 * The ending's redirect for `outcome` with its pipes filled, pattern-checked and encoded
 * (end-of-survey plan §4.2, EN2; `redirect.ts`). Null when the ending has none or names
 * no declared template; `url: null` with `rejected` set when a value failed its check.
 */
function resolveRedirect(plan: Plan, d: Data, env: Env, outcome: Id): ResolvedRedirect | null {
	const r = plan.endings?.[outcome]?.redirect;
	if (!r) return null;
	const t = Object.prototype.hasOwnProperty.call(plan.redirectTemplates ?? {}, r.template)
		? plan.redirectTemplates![r.template]
		: undefined;
	if (!t) return null;
	const values: Record<string, string> = {};
	for (const [name, segs] of Object.entries(r.params)) {
		values[name] = segs.map((s) => (typeof s === 'string' ? s : pipeText(plan, d, env, s.pipe))).join('');
	}
	const filled = fillRedirect(t, values);
	return {
		url: filled.url,
		rejected: filled.rejected,
		host: templateHost(t.url),
		delay: r.delay,
		mode: r.mode,
		label: r.label ? render(plan, d, env, r.label) : null
	};
}

/**
 * The ending's redirect for an ended session (null before the end). The app resolves it
 * again after the server's acknowledgement, when `$response.id` is known (`withResponseId`).
 */
export function endRedirect(state: State): ResolvedRedirect | null {
	const { plan, data: d } = state;
	if (!d.ended) return null;
	return resolveRedirect(plan, d, new Env(plan, d), d.ended.outcome);
}

/**
 * The state after the server acknowledged the submit with `responseId` (EN2): only the
 * `$response.id` built-in changes. No event is logged: the record was built and sent before
 * the acknowledgement, and nothing replays past the end.
 */
export function withResponseId(state: State, responseId: string): State {
	if (!state.data.ended || state.data.responseId === responseId) return state;
	return { ...state, data: { ...state.data, responseId } };
}

/** Whether a redirect param's segments pipe `$response.id`, which is known only after the ack. */
function needsResponseId(segs: Segment[]): boolean {
	return segs.some((s) => typeof s !== 'string' && s.pipe === '$response.id');
}

/** `redirect.param_rejected` diagnostics for the record (none for a value that waits on the ack). */
function redirectDiagnostics(state: State): RuntimeDiagnostic[] {
	const { plan, data: d } = state;
	if (!d.ended) return [];
	const r = plan.endings?.[d.ended.outcome]?.redirect;
	const resolved = endRedirect(state);
	if (!r || !resolved?.rejected) return [];
	const param = resolved.rejected;
	if (d.responseId === undefined && param in r.params && needsResponseId(r.params[param]!)) return [];
	return [{ code: 'redirect.param_rejected', site: `endings.${d.ended.outcome}.redirect`, path: `/params/${param}` }];
}

function errorView(plan: Plan, d: Data, env: Env, id: Id, e: PageError) {
	const item = plan.items[id];
	if (e.kind === 'hook') return { ...e, message: valueText(e.text) }; // untrusted: escaped
	const msg =
		e.kind === 'constraint' && item && isQuestion(item) && item.constraintMessage
			? render(plan, d, env, item.constraintMessage)
			: null;
	return { ...e, message: msg };
}

/** A matrix as shown: its columns and one entry per row (C2c-1). */
function matrixView(
	plan: Plan,
	d: Data,
	env: Env,
	item: Extract<Item, { type: 'matrix' }>,
	errors: PageView['errors']
): ViewItem {
	const rows: ViewRow[] = [];
	for (const rid of item.rows) {
		const row = plan.items[rid];
		if (!row || !isQuestion(row)) continue;
		rows.push({
			id: rid,
			label: render(plan, d, env, row.label),
			required: row.required,
			state: env.state(rid),
			value: d.values[rid] ?? null,
			error: errors[rid] ?? null
		});
	}
	return {
		id: item.id,
		type: 'matrix',
		label: render(plan, d, env, item.label),
		help: item.help ? render(plan, d, env, item.help) : null,
		required: rows.some((r) => r.required),
		state: null,
		value: null,
		error: rows.find((r) => r.error)?.error ?? null,
		choices: item.choices.map((c) => ({ value: c.value, label: render(plan, d, env, c.label) })),
		rows
	};
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
			if (isMatrix(item)) {
				items.push(matrixView(plan, d, env, item, errors));
				continue;
			}
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
				choices,
				...(q?.type === 'slider'
					? {
							slider: {
								min: q.min ?? 0,
								max: q.max ?? 100,
								step: q.step ?? 1,
								valueType: q.valueType ?? 'integer',
								minLabel: q.minLabel ? render(plan, d, env, q.minLabel) : null,
								maxLabel: q.maxLabel ? render(plan, d, env, q.maxLabel) : null
							}
						}
					: {})
			});
		}
	}
	const endNode = d.ended?.nodeId ? index(plan).nodes.get(d.ended.nodeId) : undefined;
	if (plan.consent && awaitingConsent(state)) {
		const c = plan.consent;
		return {
			status: 'consent',
			page: CONSENT_PAGE,
			block: null,
			language: d.language,
			title: render(plan, d, env, plan.title),
			items: [],
			errors: {},
			nav: null,
			focus: 'heading',
			effect: null,
			end: null,
			trial: 0,
			position: null,
			consent: { text: render(plan, d, env, c.text), agree: render(plan, d, env, c.agree), decline: render(plan, d, env, c.decline) }
		};
	}
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
		end: d.ended ? endView(state, env, endNode) : null,
		trial: d.history.length,
		position: page ? position(plan, d, currentCursor(d)) : null
	};
}

// --- Results, context, snapshots -------------------------------------------------------

export function answers(state: State): Record<Id, AnswerRecord> {
	const env = new Env(state.plan, state.data);
	const out: Record<Id, AnswerRecord> = {};
	for (const id of state.plan.questions) {
		const st = reportedState(state.plan, state.data, env, id);
		const v = state.data.values[id];
		out[id] = { state: st, value: st === 'answered' && v !== undefined ? v : null };
	}
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

/** Question ids an expression reads, following computed variables (cycles cut). */
function questionInputs(plan: Plan, expr: Expr, out = new Set<Id>(), seen = new Set<Id>()): Set<Id> {
	const visit = (n: Expr): void => {
		switch (n.kind) {
			case 'ref': {
				if (plan.items[n.id]) out.add(n.id);
				const v = plan.variables[n.id];
				if (v?.kind === 'computed' && !seen.has(v.id)) {
					seen.add(v.id);
					visit(v.expr);
				}
				return;
			}
			case 'answered':
				return visit(n.ref);
			case 'contains':
				visit(n.ref);
				return visit(n.value);
			case 'compare':
			case 'arith':
				visit(n.left);
				return visit(n.right);
			case 'and':
			case 'or':
				return n.args.forEach(visit);
			case 'not':
				return visit(n.arg);
			case 'if':
				visit(n.cond);
				visit(n.then);
				return visit(n.else);
		}
	};
	visit(expr);
	return out;
}

/**
 * The export state of each embedded and computed variable (semantics.md §1, C2-6, C3a-5).
 * Embedded: answered when it has a value (a parameter or its default), else unanswered.
 * Computed: answered when non-null; when null, not-reached if every question it reads is
 * not-reached, irrelevant if each is not-reached or irrelevant, otherwise unanswered.
 */
function varStates(
	state: State,
	ans: Record<Id, AnswerRecord>,
	embedded: Record<Id, string | number | null>,
	computed: Record<Id, string | boolean | null>
): Record<Id, QuestionState> {
	const out: Record<Id, QuestionState> = {};
	for (const v of Object.values(state.plan.variables)) {
		if (v.kind === 'embedded') out[v.id] = embedded[v.id] === null ? 'unanswered' : 'answered';
		if (v.kind !== 'computed') continue;
		if (computed[v.id] !== null) {
			out[v.id] = 'answered';
			continue;
		}
		const inputs = [...questionInputs(state.plan, v.expr)].map((q) => ans[q]?.state ?? 'not-reached');
		if (inputs.length && inputs.every((s) => s === 'not-reached')) out[v.id] = 'not-reached';
		else if (inputs.length && inputs.every((s) => s === 'not-reached' || s === 'irrelevant')) out[v.id] = 'irrelevant';
		else out[v.id] = 'unanswered';
	}
	return out;
}

/** Effect results the session recorded, in order (replay reuses them, never re-asks). */
function recordedEffects(plan: Plan, d: Data): ResponseRecord['effects'] {
	const out: ResponseRecord['effects'] = [];
	for (const ev of d.events) {
		if (ev.type !== 'resolve' || ev.rejected !== undefined || ev.effect.kind !== 'quota') continue;
		const node = ev.effect.nodeId ?? '';
		const qn = index(plan).nodes.get(node);
		out.push({ kind: 'quota', nodeId: node, quota: qn?.type === 'quotaCheck' ? qn.quota : '', result: ev.value as QuotaResult });
	}
	return out;
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
	const variableStates = varStates(state, ans, embedded, computed);
	for (const [id, st] of Object.entries(variableStates)) csvState[`${plan.variables[id]!.name}__state`] = st;
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
		// §7 (R1-8): `seeded` when the engine drew any condition itself; per variable in
		// `conditionSources`.
		allocation: sources.includes('seeded') ? 'seeded' : 'server',
		assigned: serverAssigned(d),
		conditions: { ...d.conditions },
		conditionSources: { ...d.conditionSource },
		orders: clone(d.orders),
		answers: ans,
		csvState,
		embedded,
		computed,
		variableStates,
		quotas: { ...d.quotas },
		diagnostics: [...clone(d.diagnostics), ...redirectDiagnostics(state)],
		effects: recordedEffects(plan, d),
		urlParams: { ...d.urlParams },
		startedAt: d.startedAt,
		endedAt: d.ended?.at ?? null,
		revision: d.revision,
		events: clone(d.events),
		...(d.hooks ? { hooks: { vars: { ...d.hooks.vars }, paradata: clone(d.hooks.paradata), redirect: clone(d.hooks.redirect) } } : {}),
		...(plan.consent
			? {
					consentVersion: d.consent?.decision === 'agree' ? d.consent.version : null,
					consentedAt: d.consent?.decision === 'agree' ? d.consent.at : null
				}
			: {})
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
			{
					const eff = d.pending!.effect;
					if (eff.kind === 'quota') d.quotas[eff.nodeId] = 'open';
					else (d.external ??= {})[eff.nodeId] = { returned: {} };
				}
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
				const recorded = ev.type === 'next' || ev.type === 'resolve' || ev.type === 'consent' ? ev.result : undefined;
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
