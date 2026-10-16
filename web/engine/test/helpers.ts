/** Small builders for hand-made plans in unit and property tests. */

import { withChecksum, type Expr, type FlowNode, type Item, type Plan, type Quota, type Variable } from '../src/index.ts';

export const t = (s: string) => ({ en: [s] });
export const ref = (id: string): Expr => ({ kind: 'ref', id });
export const int = (value: number): Expr => ({ kind: 'int', value });
export const txt = (value: string): Expr => ({ kind: 'text', value });
export const cmp = (op: '==' | '!=' | '<' | '<=' | '>' | '>=', left: Expr, right: Expr): Expr => ({
	kind: 'compare',
	op,
	left,
	right
});

export function q(id: string, type: Item['type'], extra: Record<string, unknown> = {}): Item {
	const base = { id, type, page: '', label: t(id) };
	if (type === 'note') return { ...base, ...extra } as Item;
	const choices =
		type === 'single' || type === 'multi'
			? { choices: ['a', 'b', 'c'].map((v) => ({ value: v, label: t(v.toUpperCase()) })), choiceOrder: 'fixed' }
			: {};
	return { ...base, name: id, required: false, ...choices, ...extra } as Item;
}

export interface Spec {
	/** page id → items (each page is its own block `b_<page>`). */
	pages: Record<string, Item[]>;
	flow?: FlowNode[];
	variables?: Variable[];
	quotas?: Quota[];
	backNavigation?: boolean;
	itemOrder?: Record<string, 'fixed' | 'shuffle'>;
	languages?: string[];
}

export function blockNode(page: string): FlowNode {
	return { type: 'block', id: `n_${page}`, block: `b_${page}`, pages: [page] };
}

export function makePlan(spec: Spec): Plan {
	const items: Plan['items'] = {};
	const pages: Plan['pages'] = {};
	const blocks: Plan['blocks'] = {};
	const questions: string[] = [];
	for (const [pid, its] of Object.entries(spec.pages)) {
		for (const it of its) {
			items[it.id] = { ...it, page: pid };
			if (it.type !== 'note') questions.push(it.id);
		}
		pages[pid] = { id: pid, block: `b_${pid}`, items: its.map((i) => i.id), itemOrder: spec.itemOrder?.[pid] ?? 'fixed' };
		blocks[`b_${pid}`] = { id: `b_${pid}`, pages: [pid] };
	}
	return withChecksum({
		planVersion: 'osp-runtime-plan/1',
		engineVersion: '1',
		survey: { id: 'srv_test', version: 1, specVersion: 'osp-survey/0.1', seedVersion: '1' },
		languages: spec.languages ?? ['en'],
		defaultLanguage: (spec.languages ?? ['en'])[0]!,
		title: t('Test'),
		settings: { backNavigation: spec.backNavigation ?? true, saveMode: 'every-page', localCopy: 'browser', resumeExpiryDays: 30 },
		items,
		questions,
		pages,
		blocks,
		variables: Object.fromEntries((spec.variables ?? []).map((v) => [v.id, v])),
		quotas: Object.fromEntries((spec.quotas ?? []).map((x) => [x.id, x])),
		flow: spec.flow ?? Object.keys(spec.pages).map(blockNode)
	});
}

export function clock(start = 0, step = 10) {
	let now = start;
	return () => (now += step);
}
