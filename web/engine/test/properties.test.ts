/**
 * Property tests (fast-check) on random valid plans and random participant actions:
 * 1. the engine never throws;
 * 2. it never shows, or demands, a question that is not relevant;
 * 3. every session terminates;
 * 4. snapshot → restore gives an identical state, at every step.
 */

import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import {
	answers,
	back,
	canonicalJson,
	isState,
	next,
	resolve,
	restore,
	snapshot,
	start,
	tryAnswer,
	view,
	type Expr,
	type FlowNode,
	type Item,
	type Plan,
	type Quota,
	type State,
	type Variable
} from '../src/index.ts';
import { blockNode, clock, makePlan, q } from './helpers.ts';

const TYPES = ['integer', 'decimal', 'text', 'single', 'multi', 'date', 'note'] as const;

interface QSpec {
	type: (typeof TYPES)[number];
	required: boolean;
	showIf: number | null; // refers to the k-th earlier question (mod count)
	op: '==' | '!=' | '<' | '>';
	constraint: boolean;
}

interface FlowSpec {
	kind: 'block' | 'branch' | 'randomiser' | 'quota' | 'end';
	pick: number;
	cond: number;
}

const qSpec = fc.record({
	type: fc.constantFrom(...TYPES),
	required: fc.boolean(),
	showIf: fc.option(fc.nat(20), { nil: null }),
	op: fc.constantFrom('==' as const, '!=' as const, '<' as const, '>' as const),
	constraint: fc.boolean()
});

const planSpec = fc.record({
	pages: fc.array(fc.array(qSpec, { minLength: 1, maxLength: 4 }), { minLength: 1, maxLength: 7 }),
	flow: fc.array(
		fc.record({
			kind: fc.constantFrom('block' as const, 'block' as const, 'branch' as const, 'randomiser' as const, 'quota' as const, 'end' as const),
			pick: fc.nat(3),
			cond: fc.nat(20)
		}),
		{ minLength: 1, maxLength: 7 }
	),
	assigned: fc.boolean(),
	backNavigation: fc.boolean()
});

function literalFor(type: string): Expr {
	switch (type) {
		case 'integer':
			return { kind: 'int', value: 3 };
		case 'decimal':
			return { kind: 'decimal', value: '2.5' };
		case 'single':
		case 'text':
			return { kind: 'text', value: 'a' };
		default:
			return { kind: 'null' };
	}
}

/** Build a valid plan: references only to earlier questions (osp-spec C2-1). */
interface PlanSpec {
	pages: QSpec[][];
	flow: FlowSpec[];
	assigned: boolean;
	backNavigation: boolean;
}

function buildPlan(s: PlanSpec): Plan {
	const pages: Record<string, Item[]> = {};
	const earlier: Item[] = [];
	s.pages.forEach((qs, pi) => {
		const items: Item[] = [];
		qs.forEach((qs1, qi) => {
			const id = `q${pi}_${qi}`;
			const extra: Record<string, unknown> = { required: qs1.required };
			const answerable = earlier.filter((e) => e.type !== 'note');
			if (qs1.showIf !== null && answerable.length) {
				const target = answerable[qs1.showIf % answerable.length]!;
				extra.showIf =
					target.type === 'multi'
						? { kind: 'contains', ref: { kind: 'ref', id: target.id }, value: { kind: 'text', value: 'a' } }
						: qs1.op === '<' && target.type === 'text'
							? { kind: 'answered', ref: { kind: 'ref', id: target.id } }
							: { kind: 'compare', op: qs1.op, left: { kind: 'ref', id: target.id }, right: literalFor(target.type) };
			}
			if (qs1.constraint && (qs1.type === 'integer' || qs1.type === 'decimal')) {
				extra.constraint = { kind: 'compare', op: '<=', left: { kind: 'ref', id }, right: { kind: 'int', value: 5 } };
			}
			const item = qs1.type === 'note' ? q(id, 'note', { showIf: extra.showIf }) : q(id, qs1.type, extra);
			if (qs1.type === 'note' && !extra.showIf) delete (item as { showIf?: unknown }).showIf;
			items.push(item);
			earlier.push(item);
		});
		pages[`p${pi}`] = items;
	});
	const pageIds = Object.keys(pages);
	const variables: Variable[] = s.assigned
		? [{ id: 'cond', kind: 'assigned', name: 'cond', levels: ['x', 'y'], seedNode: 'as/cond' }]
		: [];
	const quotas: Quota[] = [];
	const flow: FlowNode[] = s.assigned ? [{ type: 'assign', id: 'as', variables: ['cond'] }] : [];
	let next = 0;
	const take = () => (next < pageIds.length ? pageIds[next++]! : null);
	const answerable = earlier.filter((e) => e.type === 'integer');
	s.flow.forEach((f, i) => {
		const cond: Expr =
			answerable.length > 0
				? { kind: 'compare', op: '>', left: { kind: 'ref', id: answerable[f.cond % answerable.length]!.id }, right: { kind: 'int', value: 2 } }
				: { kind: 'compare', op: '==', left: { kind: 'ref', id: 'cond' }, right: { kind: 'text', value: 'x' } };
		if (f.kind === 'block') {
			const p = take();
			if (p) flow.push(blockNode(p));
		} else if (f.kind === 'branch') {
			const a = take();
			const b = take();
			flow.push({ type: 'branch', id: `br${i}`, if: cond, then: a ? [blockNode(a)] : [], else: b ? [blockNode(b)] : [] });
		} else if (f.kind === 'randomiser') {
			const kids = [take(), take(), take()].filter((x): x is string => !!x).map(blockNode);
			if (kids.length) flow.push({ type: 'randomiser', id: `r${i}`, children: kids, pick: f.pick && f.pick <= kids.length ? f.pick : null });
		} else if (f.kind === 'quota') {
			quotas.push({ id: `quota${i}`, when: cond, limit: 1, countOn: 'complete', onFull: { block: null, pages: [], outcome: 'full' } });
			flow.push({ type: 'quotaCheck', id: `qc${i}`, quota: `quota${i}` });
		} else if (f.kind === 'end' && i > 0) {
			flow.push({ type: 'end', id: `end${i}`, outcome: 'early' });
		}
	});
	for (let p = take(); p; p = take()) flow.push(blockNode(p));
	return makePlan({ pages, flow, variables, quotas, backNavigation: s.backNavigation });
}

const junk = fc.oneof(
	fc.constant(null),
	fc.constant(''),
	fc.constant('   '),
	fc.integer({ min: -10, max: 10 }),
	fc.double(),
	fc.string({ maxLength: 6 }),
	fc.constantFrom('a', 'b', 'c', '2.5', '2026-02-30', '2026-03-14', '1e9', '9007199254740993'),
	fc.array(fc.constantFrom('a', 'b', 'c', 'zz'), { maxLength: 4 }),
	fc.object({ maxDepth: 1 })
);

const action = fc.oneof(
	fc.record({ kind: fc.constant('answer' as const), item: fc.nat(30), value: junk }),
	fc.record({ kind: fc.constant('next' as const) }),
	fc.record({ kind: fc.constant('back' as const) }),
	fc.record({ kind: fc.constant('refresh' as const) }),
	fc.record({ kind: fc.constant('resolve' as const), full: fc.boolean() })
);

function roundTrip(s: State): State {
	const r = restore(s.plan, JSON.parse(JSON.stringify(snapshot(s))));
	if (!isState(r)) throw new Error(`restore failed: ${r.error.code} ${r.error.message}`);
	return r;
}

function checkInvariants(s: State) {
	const v = view(s);
	const states = answers(s);
	for (const it of v.items) {
		// (2) everything shown is relevant: never 'irrelevant' or 'not-reached'.
		if (it.state !== null) expect(['answered', 'unanswered']).toContain(it.state);
	}
	const visible = new Set(v.items.map((i) => i.id));
	for (const id of Object.keys(v.errors)) expect(visible.has(id)).toBe(true); // (2) never demanded while hidden
	for (const [id, a] of Object.entries(states)) {
		if (a.state !== 'answered') expect(a.value, id).toBeNull();
	}
}

const RUNS = Number(process.env.OSP_PROPERTY_RUNS ?? 300);

describe('engine properties', () => {
	it('never throws, never shows or demands a hidden question, and restores exactly', () => {
		fc.assert(
			fc.property(planSpec, fc.integer({ min: 1, max: Number.MAX_SAFE_INTEGER }), fc.array(action, { maxLength: 40 }), (spec, seed, actions) => {
				const plan = buildPlan(spec);
				let s = start(plan, { sessionSeed: seed, clock: clock() });
				checkInvariants(s);
				for (const a of actions) {
					const v = view(s);
					if (a.kind === 'answer') {
						const ids = Object.keys(plan.items);
						s = tryAnswer(s, ids[a.item % ids.length]!, a.value).state;
					} else if (a.kind === 'next') s = next(s).state;
					else if (a.kind === 'back') s = back(s);
					else if (a.kind === 'resolve' && v.effect?.kind === 'quota') s = resolve(s, v.effect, a.full ? 'full' : 'open');
					else if (a.kind === 'refresh') s = roundTrip(s);
					checkInvariants(s);
					// (4) snapshot → restore is the identity, at every step.
					expect(canonicalJson(roundTrip(s).data)).toBe(canonicalJson(s.data));
				}
			}),
			{ numRuns: RUNS, ...(process.env.OSP_PROPERTY_SEED ? { seed: Number(process.env.OSP_PROPERTY_SEED) } : {}) }
		);
	});

	it('always terminates when the participant answers what is asked', () => {
		fc.assert(
			fc.property(planSpec, fc.integer({ min: 1, max: Number.MAX_SAFE_INTEGER }), fc.boolean(), (spec, seed, full) => {
				const plan = buildPlan(spec);
				let s = start(plan, { sessionSeed: seed, clock: clock() });
				const limit = Object.keys(plan.pages).length + Object.keys(plan.quotas).length + 2;
				for (let step = 0; step <= limit && view(s).status !== 'ended'; step++) {
					const v = view(s);
					if (v.status === 'pending' && v.effect?.kind === 'quota') {
						s = resolve(s, v.effect, full ? 'full' : 'open');
						continue;
					}
					// Answering can reveal more items on the same page (live show-if): repeat
					// until every visible question has been answered.
					const done = new Set<string>();
					for (let more = true; more; ) {
						more = false;
						for (const it of view(s).items) {
							const value = { integer: 1, decimal: '1.5', text: 'ok', single: 'a', multi: ['b'], date: '2026-01-31' }[
								it.type as 'integer'
							];
							if (value === undefined || done.has(it.id)) continue;
							done.add(it.id);
							s = tryAnswer(s, it.id, value).state;
							more = true;
						}
					}
					const r = next(s);
					expect(r.result.outcome).not.toBe('invalid');
					s = r.state;
				}
				expect(view(s).status).toBe('ended');
				expect(view(s).nav).toBeNull();
			}),
			{ numRuns: RUNS, ...(process.env.OSP_PROPERTY_SEED ? { seed: Number(process.env.OSP_PROPERTY_SEED) } : {}) }
		);
	});
});
