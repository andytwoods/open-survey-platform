/**
 * Static facts about a plan the simulator needs: where every flow node sits, which
 * observations prove a node was reached, and how each question is used by expressions
 * (which decides whether the path space can be enumerated exhaustively).
 */

import { isQuestion, type Expr, type FlowNode, type Id, type Plan, type QuestionItem } from '@osp/engine';

export type Arm = 'then' | 'else';

export interface NodeInfo {
	node: FlowNode;
	/** The node list it is in: `root`, `then:<branch>`, `else:<branch>` or `rand:<randomiser>`. */
	list: string;
	/** Index in that list (plan order; a randomiser list is reordered per participant). */
	index: number;
	/** Enclosing flow nodes, outermost first, with the branch arm taken to get here. */
	ancestors: Array<{ id: Id; arm?: Arm }>;
}

export interface Structure {
	nodes: Map<Id, NodeInfo>;
	/** Node lists in plan order (`root`, `then:<id>`, `else:<id>`, `rand:<id>`). */
	lists: Map<string, Id[]>;
	/** Page → the flow node that shows it (block node; quotaCheck for onFull pages). */
	pageOwner: Map<Id, Id>;
	/** Assigned variable → its assign node, when exactly one node assigns it. */
	assignOwner: Map<Id, Id>;
	/** Number of possible realised orders of each randomiser (n! / (n − pick)!). */
	possibleOrders: Map<Id, number>;
}

function permutations(n: number, pick: number | null): number {
	const k = pick === null || pick <= 0 || pick > n ? n : pick;
	let out = 1;
	for (let i = 0; i < k; i++) out *= n - i;
	return out;
}

export function structure(plan: Plan): Structure {
	const nodes = new Map<Id, NodeInfo>();
	const lists = new Map<string, Id[]>();
	const pageOwner = new Map<Id, Id>();
	const assignCount = new Map<Id, Id[]>();
	const possibleOrders = new Map<Id, number>();
	const visit = (list: FlowNode[], key: string, ancestors: NodeInfo['ancestors']) => {
		lists.set(
			key,
			list.map((n) => n.id)
		);
		list.forEach((node, index) => {
			if (nodes.has(node.id)) return; // malformed plan: ids are unique in a valid one
			nodes.set(node.id, { node, list: key, index, ancestors });
			switch (node.type) {
				case 'block':
					for (const p of node.pages) if (!pageOwner.has(p)) pageOwner.set(p, node.id);
					break;
				case 'branch':
					visit(node.then, `then:${node.id}`, [...ancestors, { id: node.id, arm: 'then' }]);
					visit(node.else, `else:${node.id}`, [...ancestors, { id: node.id, arm: 'else' }]);
					break;
				case 'randomiser':
					possibleOrders.set(node.id, permutations(node.children.length, node.pick));
					visit(node.children, `rand:${node.id}`, [...ancestors, { id: node.id }]);
					break;
				case 'assign':
					for (const v of node.variables) assignCount.set(v, [...(assignCount.get(v) ?? []), node.id]);
					break;
				case 'quotaCheck':
					for (const p of plan.quotas[node.quota]?.onFull.pages ?? []) if (!pageOwner.has(p)) pageOwner.set(p, node.id);
					break;
			}
		});
	};
	visit(plan.flow, 'root', []);
	const assignOwner = new Map<Id, Id>();
	for (const [v, ids] of assignCount) if (ids.length === 1) assignOwner.set(v, ids[0]!);
	return { nodes, lists, pageOwner, assignOwner, possibleOrders };
}

/**
 * Whether entering this node list always leaves an observation behind (a reached page,
 * a realised randomiser order, a reached assign, an end), so that a branch arm with no
 * observation can be told apart from the other arm.
 */
export function leavesEvidence(s: Structure, plan: Plan, list: FlowNode[]): boolean {
	for (const n of list) {
		switch (n.type) {
			case 'block':
				if (n.pages.length) return true;
				break;
			case 'randomiser':
			case 'end':
				return true;
			case 'assign':
				if (n.variables.some((v) => s.assignOwner.get(v) === n.id)) return true;
				break;
			case 'branch':
				if (leavesEvidence(s, plan, n.then) && leavesEvidence(s, plan, n.else)) return true;
				break;
			case 'quotaCheck':
				break;
		}
	}
	return false;
}

// --- How expressions use each reference ---------------------------------------------------

type Literal = { kind: 'num'; value: string } | { kind: 'text'; value: string };

export interface Usage {
	/** Literals a question is compared with (`q < 3`, `"a" == q`). */
	literals: Map<Id, Literal[]>;
	/** Operators each question is compared with. */
	ops: Map<Id, Set<string>>;
	/** Questions used in any other way (arithmetic, compared with another reference …). */
	general: Set<Id>;
	/** Every id referenced by any expression (questions, variables, `$` built-ins). */
	refs: Set<Id>;
}

function isLiteral(e: Expr): Literal | null {
	if (e.kind === 'int' || e.kind === 'decimal') return { kind: 'num', value: String(e.value) };
	if (e.kind === 'text') return { kind: 'text', value: e.value };
	return null;
}

/** Every expression in the plan that can change a path, a validation result or a state. */
export function planExpressions(plan: Plan): Expr[] {
	const out: Expr[] = [];
	for (const item of Object.values(plan.items)) {
		if (item.showIf) out.push(item.showIf);
		if (isQuestion(item) && item.constraint) out.push(item.constraint);
	}
	for (const page of Object.values(plan.pages)) if (page.showIf) out.push(page.showIf);
	for (const q of Object.values(plan.quotas)) out.push(q.when);
	for (const v of Object.values(plan.variables)) if (v.kind === 'computed') out.push(v.expr);
	const walk = (ns: FlowNode[]) => {
		for (const n of ns) {
			if (n.type === 'branch') {
				out.push(n.if);
				walk(n.then);
				walk(n.else);
			} else if (n.type === 'randomiser') walk(n.children);
		}
	};
	walk(plan.flow);
	return out;
}

export function usage(plan: Plan): Usage {
	return usageOf(planExpressions(plan));
}

export function usageOf(exprs: readonly Expr[]): Usage {
	const u: Usage = { literals: new Map(), ops: new Map(), general: new Set(), refs: new Set() };
	const visit = (e: Expr | undefined): void => {
		if (!e || typeof e !== 'object') return;
		switch (e.kind) {
			case 'ref':
				u.refs.add(e.id);
				u.general.add(e.id);
				return;
			case 'answered':
				u.refs.add(e.ref.id);
				return;
			case 'contains':
				u.refs.add(e.ref.id);
				if (!isLiteral(e.value)) visit(e.value);
				return;
			case 'compare': {
				const pairs: Array<[Expr, Expr]> = [
					[e.left, e.right],
					[e.right, e.left]
				];
				for (const [a, b] of pairs) {
					const lit = isLiteral(b);
					if (a.kind === 'ref' && lit) {
						u.refs.add(a.id);
						u.literals.set(a.id, [...(u.literals.get(a.id) ?? []), lit]);
						u.ops.set(a.id, new Set([...(u.ops.get(a.id) ?? []), e.op]));
						return;
					}
				}
				visit(e.left);
				visit(e.right);
				return;
			}
			case 'arith':
				visit(e.left);
				visit(e.right);
				return;
			case 'and':
			case 'or':
				e.args.forEach(visit);
				return;
			case 'not':
				visit(e.arg);
				return;
			case 'if':
				visit(e.cond);
				visit(e.then);
				visit(e.else);
				return;
		}
	};
	exprs.forEach(visit);
	return u;
}

// --- Answer domains ---------------------------------------------------------------------

/** Marker for "leave the question blank". */
export const BLANK = Symbol('blank');
export type Answer = typeof BLANK | number | string | Array<number | string>;

const MAX_MULTI_CHOICES = 8;
const MAX_ABS = 1e15;

function num(x: number | string | undefined): number | null {
	if (x === undefined) return null;
	const n = Number(x);
	return Number.isFinite(n) ? n : null;
}

function fmt(n: number, integer: boolean): number | string {
	if (integer) return n;
	// Plain decimal text, no exponent (checkAnswer refuses "1e-7").
	const s = Math.abs(n) < 1e-6 && n !== 0 ? n.toFixed(12) : String(n);
	return s.includes('e') ? n.toFixed(6) : s;
}

/**
 * Representative numbers for a numeric question compared with literals: every literal, a
 * point strictly between each neighbouring pair, one below and one above, and the
 * bounds, all inside [min, max]. One point per region of the number line the comparisons
 * can tell apart, so enumerating them covers every outcome of those comparisons.
 */
export function numericPoints(item: QuestionItem, literals: readonly Literal[]): Array<number | string> | null {
	const integer = item.type === 'integer';
	const lo = num(item.min);
	const hi = num(item.max);
	const cuts: number[] = [];
	for (const l of literals) {
		const n = l.kind === 'num' ? num(l.value) : null;
		if (n === null || Math.abs(n) > MAX_ABS) return null;
		cuts.push(n);
	}
	const sorted = [...new Set(cuts)].sort((a, b) => a - b);
	const pts = new Set<number>();
	if (lo !== null) pts.add(lo);
	if (hi !== null) pts.add(hi);
	if (!sorted.length && lo === null && hi === null) pts.add(1);
	for (const c of sorted) pts.add(c);
	if (sorted.length) {
		pts.add(integer ? Math.floor(sorted[0]!) - 1 : sorted[0]! - 1);
		pts.add(integer ? Math.ceil(sorted[sorted.length - 1]!) + 1 : sorted[sorted.length - 1]! + 1);
	}
	for (let i = 0; i + 1 < sorted.length; i++) {
		const a = sorted[i]!;
		const b = sorted[i + 1]!;
		if (integer) {
			const m = Math.floor(a) + 1;
			if (m < b) pts.add(m);
		} else pts.add((a + b) / 2);
	}
	return [...pts]
		.filter((p) => (!integer || Number.isInteger(p)) && (lo === null || p >= lo) && (hi === null || p <= hi))
		.sort((a, b) => a - b)
		.map((p) => fmt(p, integer));
}

function subsets<T>(xs: readonly T[]): T[][] {
	const out: T[][] = [];
	for (let mask = 1; mask < 1 << xs.length; mask++) out.push(xs.filter((_, i) => mask & (1 << i)));
	return out;
}

/** One answer that is valid whatever the expressions say (for unreferenced questions). */
export function representative(item: QuestionItem): Answer {
	switch (item.type) {
		case 'single':
			return item.choices?.[0]?.value ?? BLANK;
		case 'multi':
			return item.choices?.length ? [item.choices[0]!.value] : BLANK;
		case 'integer':
		case 'decimal':
			return numericPoints(item, [])?.[0] ?? 1;
		case 'text':
			return 'sim';
		case 'date':
			return '2000-01-01';
		case 'slider':
			return sliderPoint(item, 0);
	}
}

/** The k-th valid slider answer (min + k·step), clamped to max; as stored text for decimals. */
export function sliderPoint(item: QuestionItem, k: number): Answer {
	const lo = Number(item.min ?? 0);
	const step = Number(item.step ?? 1) || 1;
	const hi = item.max !== undefined ? Number(item.max) : lo + 10 * step;
	const v = Math.min(hi, lo + Math.max(0, k) * step);
	return item.valueType === 'decimal' ? String(Number(v.toFixed(10))) : Math.round(v);
}

/** How many valid slider answers there are (at least 1). */
export function sliderCount(item: QuestionItem): number {
	const lo = Number(item.min ?? 0);
	const step = Number(item.step ?? 1) || 1;
	const hi = item.max !== undefined ? Number(item.max) : lo + 10 * step;
	return Math.max(1, Math.floor((hi - lo) / step + 1e-9) + 1);
}

export interface Domains {
	domains: Map<Id, Answer[]>;
	/** Why the path space cannot be enumerated exhaustively (empty: it can). */
	reasons: string[];
}

const DETERMINISTIC_BUILTINS = new Set(['$trial', '$position.index', '$position.of', '$pagesDone']);

/**
 * A finite answer domain per question such that every combination of comparison
 * outcomes the plan's expressions can see is represented, or the reasons this is not
 * possible (then coverage can only be sampled).
 */
export function exhaustiveDomains(plan: Plan): Domains {
	const u = usage(plan);
	const reasons: string[] = [];
	const domains = new Map<Id, Answer[]>();
	for (const id of u.refs) {
		if (plan.items[id]) continue;
		const v = plan.variables[id];
		if (v?.kind === 'embedded') reasons.push(`embedded variable ${id} (URL parameter) is used in a condition`);
		else if (v?.kind === 'hook') reasons.push(`hook variable ${id} is used in a condition (hooks don't run in the simulator)`);
		else if (id === '$language' && plan.languages.length > 1) reasons.push('$language is used in a condition');
		else if (id === '$device') reasons.push('$device is used in a condition');
		else if (id.startsWith('$') && !DETERMINISTIC_BUILTINS.has(id) && id !== '$language') {
			reasons.push(`${id} is used in a condition`);
		}
	}
	for (const item of Object.values(plan.items)) {
		if (!isQuestion(item)) continue;
		const q = item;
		const blank: Answer[] = q.required ? [] : [BLANK];
		if (!u.refs.has(q.id)) {
			domains.set(q.id, [representative(q)]);
			continue;
		}
		const general = u.general.has(q.id);
		const lits = u.literals.get(q.id) ?? [];
		const ops = u.ops.get(q.id) ?? new Set<string>();
		switch (q.type) {
			case 'single':
				domains.set(q.id, [...blank, ...(q.choices ?? []).map((c) => c.value)]);
				break;
			case 'multi': {
				const codes = (q.choices ?? []).map((c) => c.value);
				if (codes.length > MAX_MULTI_CHOICES) {
					reasons.push(`multi question ${q.id} has more than ${MAX_MULTI_CHOICES} choices`);
					domains.set(q.id, [...blank, codes.slice(0, 1)]);
				} else domains.set(q.id, [...blank, ...subsets(codes)]);
				break;
			}
			case 'integer':
			case 'decimal': {
				const pts = general || lits.some((l) => l.kind !== 'num') ? null : numericPoints(q, lits);
				if (pts === null) {
					reasons.push(`${q.type} question ${q.id} is used in arithmetic or compared with something other than a number`);
					domains.set(q.id, [...blank, representative(q)]);
				} else domains.set(q.id, [...blank, ...pts]);
				break;
			}
			case 'text': {
				const textOnly = !general && lits.every((l) => l.kind === 'text') && [...ops].every((o) => o === '==' || o === '!=');
				if (!textOnly) {
					reasons.push(`text question ${q.id} is used in a condition other than ==/!= with text`);
					domains.set(q.id, [...blank, 'sim']);
				} else {
					const vals = [...new Set(lits.map((l) => l.value))].filter((v) => v.trim() !== '');
					domains.set(q.id, [...blank, ...vals, 'sim-other']);
				}
				break;
			}
			case 'date':
				if (general || lits.length) reasons.push(`date question ${q.id} is compared in a condition`);
				domains.set(q.id, [...blank, '2000-01-01']);
				break;
			case 'slider': {
				// Unreferenced: one value is enough. Referenced: every step, if there are few.
				const n = sliderCount(q);
				if (!general && !lits.length) domains.set(q.id, [...blank, sliderPoint(q, 0)]);
				else if (n <= 50) domains.set(q.id, [...blank, ...Array.from({ length: n }, (_, k) => sliderPoint(q, k))]);
				else {
					reasons.push(`slider question ${q.id} has ${n} steps and is used in a condition`);
					domains.set(q.id, [...blank, sliderPoint(q, 0)]);
				}
				break;
			}
		}
	}
	// Live show-if inside a page is enumerated in display order, so a show-if may only look
	// at questions shown before it on a fixed-order page.
	for (const page of Object.values(plan.pages)) {
		const pos = new Map(page.items.map((id, i) => [id, i]));
		page.items.forEach((id, i) => {
			const e = plan.items[id]?.showIf;
			if (!e) return;
			for (const r of usageOf([e]).refs) {
				const j = pos.get(r);
				if (j !== undefined && (page.itemOrder === 'shuffle' || j >= i)) {
					reasons.push(`show-if of ${id} looks at ${r}, which is not shown before it on page ${page.id}`);
				}
			}
		});
	}
	return { domains, reasons: [...new Set(reasons)] };
}
