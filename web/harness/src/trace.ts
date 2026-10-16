/**
 * The parts of a trace step the screen cannot show (off-page question states, orders,
 * conditions, end code, pending effect, built-ins), taken from the app's own engine state:
 * the snapshot it keeps (`Session.rec.snapshot`, the copy it writes to IndexedDB and PUTs to
 * the server) is restored here with `@osp/engine`. `restore` also checks that the snapshot
 * matches its own event log, so a corrupted copy fails loudly.
 *
 * Fixture traces name blocks, the engine pages and flow nodes (FORMAT.md §1); the renames
 * are the engine runner's (web/engine/test/fixture-runner.ts).
 */
import { answers, isState, restore, result, toHtml, view, type Plan, type ResponseRecord, type State } from '@osp/engine';

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

export function renameOrders(plan: Plan, orders: ResponseRecord['orders']) {
	const blocks: Record<string, string[]> = {};
	for (const [k, v] of Object.entries(orders?.blocks ?? {})) blocks[k] = v.map((id) => blockOfNode(plan, id));
	const items: Record<string, string[]> = {};
	for (const [k, v] of Object.entries(orders?.items ?? {})) items[blockOfPage(plan, k) ?? k] = v;
	return { blocks, items, choices: orders?.choices ?? {} };
}

export function restoreSnapshot(plan: Plan, snap: unknown): State {
	const r = restore(plan, snap);
	if (!isState(r)) throw new Error(`the app's snapshot does not restore: ${r.error.code}: ${r.error.message}`);
	return r;
}

/** Engine-side step fields for the app's current state. */
export function engineStep(state: State) {
	const v = view(state);
	const r = result(state);
	const errors: Record<string, { kind: string; message?: string | null; code?: string }> = {};
	for (const [id, e] of Object.entries(v.errors)) {
		if (e.kind === 'constraint') errors[id] = { kind: 'constraint', message: e.message ? toHtml(e.message) : null };
		else if (e.kind === 'invalid') errors[id] = { kind: 'invalid', code: e.code };
		else errors[id] = { kind: e.kind };
	}
	return {
		page: blockOfPage(state.plan, v.page),
		visible: v.items.map((i) => i.id),
		errors,
		questions: answers(state),
		orders: renameOrders(state.plan, r.orders),
		conditions: r.conditions,
		end: r.end,
		effect: v.status === 'pending' && v.effect?.kind === 'quota' ? { kind: 'quota', nodeId: v.effect.nodeId } : null,
		builtins: v.status === 'ended' ? null : { trial: v.trial, position: v.position },
		view: v
	};
}

/** A stored ResponseRecord in trace form (orders renamed to blocks). */
export function responseOf(plan: Plan, record: ResponseRecord) {
	return { ...record, orders: renameOrders(plan, record.orders) };
}
