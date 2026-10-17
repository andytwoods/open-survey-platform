/**
 * Why a question is shown or hidden, for the debugger panel: the show-if condition as text
 * (printed by the server, `POST /preview-plan` → `conditions`), the values it reads, and
 * what it evaluates to now.
 *
 * The verdict is always the engine's (`answers`, `view`). The condition is re-evaluated
 * here with the engine's own evaluator (`evaluateCondition`) over the values the engine
 * reports (`answers`, `result`, `context`), only to show the reader *why*; if the two ever
 * disagree the row says so (`agrees: false`) instead of hiding it.
 */
import {
	answers,
	context,
	evaluate,
	evaluateCondition,
	isQuestion,
	result,
	view,
	type Expr,
	type Item,
	type Lookup,
	type Plan,
	type QuestionState,
	type State,
	type Value
} from '@osp/engine';

export interface Read {
	id: string;
	/** The value as stored (JSON), or null. */
	value: unknown;
	/** Where it comes from: a question's state, a condition, a built-in. */
	note: string;
}

export interface Reason {
	/** Short verdict, e.g. "Shown: condition is true". */
	summary: string;
	/** The condition that decides it, as text, if any. */
	condition: string | null;
	/** What the condition reads, with the values the engine has now. */
	reads: Read[];
	/** The condition evaluated now (null: no condition). */
	evaluated: boolean | null;
	/** Whether that evaluation agrees with the engine's verdict. */
	agrees: boolean;
}

export interface ItemExplanation {
	id: string;
	type: string;
	label: string;
	visible: boolean;
	state: QuestionState | null;
	value: unknown;
	reason: Reason;
}

/** Ids an expression reads, in first-use order. */
export function refsOf(expr: Expr | undefined): string[] {
	const out: string[] = [];
	const walk = (e: Expr | undefined) => {
		if (!e) return;
		switch (e.kind) {
			case 'ref':
				if (!out.includes(e.id)) out.push(e.id);
				return;
			case 'compare':
			case 'arith':
				walk(e.left);
				walk(e.right);
				return;
			case 'and':
			case 'or':
				e.args.forEach(walk);
				return;
			case 'not':
				walk(e.arg);
				return;
			case 'answered':
				walk(e.ref);
				return;
			case 'contains':
				walk(e.ref);
				walk(e.value);
				return;
			case 'if':
				walk(e.cond);
				walk(e.then);
				walk(e.else);
				return;
		}
	};
	walk(expr);
	return out;
}

const none: Lookup = () => null;
const int = (n: number | string): Value => evaluate({ kind: 'int', value: n }, none);
const decimal = (s: string): Value => evaluate({ kind: 'decimal', value: s }, none);
const text = (s: string): Value => (s === '' ? null : { k: 'text', v: s });

/** A stored value as an expression value, by the question's value type (as the engine reads it). */
function toValue(type: string, stored: unknown): Value {
	if (stored === null || stored === undefined) return null;
	switch (type) {
		case 'integer':
			return typeof stored === 'number' ? int(stored) : null;
		case 'decimal':
			return typeof stored === 'string' ? decimal(stored) : typeof stored === 'number' ? decimal(String(stored)) : null;
		case 'text':
			return typeof stored === 'string' ? text(stored) : null;
		case 'date':
			return typeof stored === 'string' ? { k: 'date', v: stored } : null;
		case 'single':
			return code(stored);
		case 'multi':
			return Array.isArray(stored) && stored.length ? { k: 'multi', v: stored as Array<string | number> } : null;
		case 'boolean':
			return typeof stored === 'boolean' ? { k: 'bool', v: stored } : null;
	}
	return null;
}

function code(c: unknown): Value {
	if (typeof c === 'number') return Number.isInteger(c) ? int(c) : null;
	if (typeof c === 'string') return text(c.trim());
	return null;
}

function valueType(item: Item): string {
	if (!isQuestion(item)) return 'none';
	return item.type === 'slider' ? (item.valueType ?? 'integer') : item.type;
}

/** What `id` holds now, as the engine reports it (stored JSON + a note). */
export function readOf(state: State, id: string): Read {
	const plan = state.plan;
	if (id.startsWith('$')) {
		const c = context(state);
		const v: Record<string, unknown> = {
			$trial: c.trial || null,
			$pagesDone: c.pagesDone,
			$language: c.language,
			$device: c.device,
			'$position.index': c.position?.index ?? null,
			'$position.of': c.position?.of ?? null
		};
		return { id, value: v[id] ?? null, note: 'built-in' };
	}
	const item = plan.items[id];
	if (item) {
		const a = answers(state)[id];
		return { id, value: a?.value ?? null, note: a ? a.state : 'not a question' };
	}
	const variable = plan.variables[id];
	if (!variable) return { id, value: null, note: 'unknown id' };
	const r = result(state);
	switch (variable.kind) {
		case 'assigned': {
			const reached = !!state.data.assignReached[id];
			return {
				id,
				value: reached ? (r.conditions[id] ?? null) : null,
				note: reached ? `condition (${r.conditionSources[id] ?? 'server'})` : 'condition, assign node not reached yet'
			};
		}
		case 'embedded':
			return { id, value: r.embedded[id] ?? null, note: 'embedded (URL)' };
		case 'computed':
			return { id, value: r.computed[id] ?? null, note: 'computed' };
		case 'hook':
			return { id, value: state.data.hooks?.vars[id] ?? null, note: 'set by a hook' };
	}
	return { id, value: null, note: '' };
}

/** A lookup over what the engine reports, for re-evaluating a condition to explain it. */
export function lookupFor(state: State): Lookup {
	const plan = state.plan;
	const ans = answers(state);
	const r = result(state);
	const busy = new Set<string>();
	const lookup: Lookup = (id) => {
		if (id.startsWith('$')) {
			const v = readOf(state, id).value;
			return typeof v === 'number' ? int(v) : typeof v === 'string' ? text(v) : null;
		}
		const item = plan.items[id];
		if (item) return isQuestion(item) ? toValue(valueType(item), ans[id]?.value ?? null) : null;
		const v = plan.variables[id];
		if (!v) return null;
		switch (v.kind) {
			case 'assigned':
				return state.data.assignReached[id] && id in r.conditions ? code(r.conditions[id]) : null;
			case 'embedded': {
				const raw = r.embedded[id] ?? null;
				if (raw === null) return null;
				if (v.valueType === 'text') return text(String(raw));
				return toValue(v.valueType, v.valueType === 'integer' ? raw : String(raw));
			}
			case 'computed': {
				if (busy.has(id)) return null;
				busy.add(id);
				const out = evaluate(v.expr, lookup);
				busy.delete(id);
				return out;
			}
			case 'hook':
				return toValue(v.valueType, state.data.hooks?.vars[id] ?? null);
		}
		return null;
	};
	return lookup;
}

function reads(state: State, expr: Expr | undefined): Read[] {
	return refsOf(expr).map((id) => readOf(state, id));
}

/**
 * Explain every item of `pageId` (default: the current page), in page order, including the
 * hidden ones.
 */
export function explainPage(state: State, texts: Record<string, string>, pageId?: string | null): ItemExplanation[] {
	const plan = state.plan;
	const v = view(state);
	const page = pageId ?? v.page;
	if (!page || !plan.pages[page]) return [];
	const shown = new Set(v.page === page ? v.items.map((i) => i.id) : []);
	const order = state.data.orders.items[page] ?? plan.pages[page]!.items;
	const ans = answers(state);
	return order
		.map((id) => plan.items[id])
		.filter((it): it is Item => !!it)
		.map((item) => {
			const rowState = item.type === 'matrix' ? null : (ans[item.id]?.state ?? null);
			const visible = v.page === page ? shown.has(item.id) : rowState !== null && rowState !== 'irrelevant' && rowState !== 'not-reached';
			return {
				id: item.id,
				type: item.type,
				label: firstText(item, plan),
				visible,
				state: rowState,
				value: ans[item.id]?.value ?? null,
				reason: explainItem(state, texts, item, visible)
			};
		});
}

function firstText(item: Item, plan: Plan): string {
	const segs = item.label[plan.defaultLanguage] ?? Object.values(item.label)[0] ?? [];
	return segs.map((s) => (typeof s === 'string' ? s.replace(/<[^>]*>/g, '') : `\${${s.pipe}}`)).join('');
}

export function explainItem(state: State, texts: Record<string, string>, item: Item, visible: boolean): Reason {
	const plan = state.plan;
	const page = plan.pages[item.page];
	const d = state.data;
	if (!d.reachedPages[item.page]) {
		return { summary: 'Not reached: the flow has not got to its page yet.', condition: null, reads: [], evaluated: null, agrees: !visible };
	}
	if (d.offPath[item.page]) {
		return {
			summary: 'Hidden: a later answer took its page off the path (its answers were cleared).',
			condition: null,
			reads: [],
			evaluated: null,
			agrees: !visible
		};
	}
	const lookup = lookupFor(state);
	if (page?.showIf) {
		const ok = evaluateCondition(page.showIf, lookup);
		if (!ok) {
			return {
				summary: 'Hidden: the page condition is false.',
				condition: texts[`pages.${page.id}.showIf`] ?? null,
				reads: reads(state, page.showIf),
				evaluated: false,
				agrees: !visible
			};
		}
	}
	if (isQuestion(item) && item.matrix) {
		const m = plan.items[item.matrix];
		if (m) return explainItem(state, texts, m, visible);
	}
	if (!item.showIf) {
		return {
			summary: visible ? 'Shown: no show-if condition.' : 'Hidden although it has no condition (empty page skipped).',
			condition: null,
			reads: [],
			evaluated: null,
			agrees: true
		};
	}
	const ok = evaluateCondition(item.showIf, lookup);
	return {
		summary: ok ? 'Shown: the show-if condition is true.' : 'Hidden: the show-if condition is not true (false or null).',
		condition: texts[`items.${item.id}.showIf`] ?? null,
		reads: reads(state, item.showIf),
		evaluated: ok,
		agrees: ok === visible
	};
}

/** The branch nodes on the flow with their condition now (the debugger's "path" section). */
export function branches(state: State, texts: Record<string, string>) {
	const out: Array<{ id: string; condition: string | null; reads: Read[]; now: boolean }> = [];
	const lookup = lookupFor(state);
	const walk = (ns: Plan['flow']) => {
		for (const n of ns) {
			if (n.type === 'branch') {
				out.push({ id: n.id, condition: texts[`flow.${n.id}.if`] ?? null, reads: reads(state, n.if), now: evaluateCondition(n.if, lookup) });
				walk(n.then);
				walk(n.else);
			} else if (n.type === 'randomiser') walk(n.children);
		}
	};
	walk(state.plan.flow);
	return out;
}

/** Shown values: JSON, with null spelled out. */
export function show(value: unknown): string {
	if (value === null || value === undefined) return 'null';
	return JSON.stringify(value);
}
