/**
 * Pages and blocks (task B20): the ops for add, duplicate and delete, built from the
 * outline tree and the survey JSON. Pure. The server owns validity: these only choose
 * where things go and which ids to ask for (an id clash comes back as a rejection).
 */
import { walk, whereParams, type Invocation } from '../flow/model';
import type { NodeType, OutlineNode } from '../model/outline';

export type StructureType = Extract<NodeType, 'block' | 'page' | 'question'>;

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);

/** Where a block, page or question sits in the tree. */
export interface Place {
	type: StructureType;
	node: OutlineNode;
	block: OutlineNode;
	blockIndex: number;
	page?: OutlineNode;
	pageIndex?: number;
	questionIndex?: number;
}

export function placeOf(roots: readonly OutlineNode[], id: string | null | undefined): Place | undefined {
	if (!id) return undefined;
	for (const [bi, b] of roots.entries()) {
		if (b.type !== 'block') continue;
		if (b.id === id) return { type: 'block', node: b, block: b, blockIndex: bi };
		for (const [pi, p] of (b.children ?? []).entries()) {
			if (p.id === id) return { type: 'page', node: p, block: b, blockIndex: bi, page: p, pageIndex: pi };
			for (const [qi, q] of (p.children ?? []).entries()) {
				if (q.id === id)
					return { type: 'question', node: q, block: b, blockIndex: bi, page: p, pageIndex: pi, questionIndex: qi };
			}
		}
	}
	return undefined;
}

/** Every id and data name in use, including grid row variables (`<id>_<row>`). */
export function usedIds(survey: unknown): Set<string> {
	const out = new Set<string>();
	const visit = (v: unknown, depth: number) => {
		if (depth > 64) return;
		if (Array.isArray(v)) for (const x of v) visit(x, depth + 1);
		else if (isObj(v)) {
			for (const k of ['id', 'name']) if (typeof v[k] === 'string') out.add(v[k] as string);
			if (v.type === 'matrix' && Array.isArray(v.rows)) {
				for (const r of v.rows) {
					if (!isObj(r) || typeof r.id !== 'string') continue;
					for (const p of [v.id, v.name]) if (typeof p === 'string') out.add(`${p}_${r.id}`);
				}
			}
			for (const x of Object.values(v)) if (typeof x === 'object') visit(x, depth + 1);
		}
	};
	visit(survey, 0);
	return out;
}

/** `prefix` itself (if `exactFirst`) or the first free `prefix<n>`, compared ignoring case. */
export function freeId(taken: ReadonlySet<string>, prefix: string, exactFirst = false): string {
	const lower = new Set([...taken].map((t) => t.toLowerCase()));
	const stem = prefix.slice(0, 56);
	if (exactFirst && !lower.has(stem.toLowerCase())) return stem;
	for (let i = 1; ; i++) if (!lower.has(`${stem}${i}`.toLowerCase())) return `${stem}${i}`;
}

/** The first flow node that shows this block (where a copy or a neighbour goes). */
function flowRowOf(survey: unknown, blockId: string) {
	return walk(survey).find((r) => r.type === 'block' && r.node.block === blockId);
}

export interface Planned {
	/** The id of what the ops create (selected and focused afterwards). */
	id: string;
	ops: Invocation[];
}

/**
 * "Add page": after the selected page (or the selected question's page), at the end of
 * the selected block, else at the end of the last block. Undefined when there is no block.
 */
export function addPagePlan(survey: unknown, roots: readonly OutlineNode[], nearId?: string | null): Planned | undefined {
	const at = placeOf(roots, nearId);
	const block = at?.block ?? [...roots].reverse().find((b) => b.type === 'block');
	if (!block) return undefined;
	const index = at?.pageIndex !== undefined ? at.pageIndex + 1 : (block.children?.length ?? 0);
	const id = freeId(usedIds(survey), 'page');
	return { id, ops: [{ op: 'add_page', params: { block: block.id, index, id } }] };
}

/**
 * "Add block": a block (with one page and one question, the smallest a block can be)
 * after the selected item's block, else at the end, and a flow node showing it just after
 * that block's flow node, else at the end of the flow.
 */
export function addBlockPlan(survey: unknown, roots: readonly OutlineNode[], nearId?: string | null): Planned {
	const at = placeOf(roots, nearId);
	const taken = usedIds(survey);
	const id = freeId(taken, 'block');
	const node = freeId(new Set([...taken, id]), `n_${id}`, true);
	const ops: Invocation[] = [{ op: 'add_block', params: at ? { id, index: at.blockIndex + 1 } : { id } }];
	ops.push(flowInsert(survey, at?.block.id, { type: 'block', id: node, block: id }));
	return { id, ops };
}

function flowInsert(survey: unknown, afterBlock: string | undefined, node: Obj): Invocation {
	const row = afterBlock ? flowRowOf(survey, afterBlock) : undefined;
	const where = row ? whereParams({ parent: row.parent, arm: row.arm, index: row.index + 1 }) : {};
	return { op: 'insert_flow_node', params: { node, ...where } };
}

/** "Duplicate": the copy goes just after the original (a block copy also into the flow). */
export function duplicatePlan(survey: unknown, roots: readonly OutlineNode[], id: string): Planned | undefined {
	const at = placeOf(roots, id);
	if (!at) return undefined;
	const taken = usedIds(survey);
	const copyId = freeId(taken, `${id}_copy`, true);
	if (at.type === 'question') return { id: copyId, ops: [{ op: 'duplicate_question', params: { id, new_id: copyId } }] };
	if (at.type === 'page') return { id: copyId, ops: [{ op: 'duplicate_page', params: { id, new_id: copyId } }] };
	const ops: Invocation[] = [{ op: 'duplicate_block', params: { id, new_id: copyId } }];
	// Only a block that is in the flow gets its copy placed (next to it); else neither shows.
	if (flowRowOf(survey, id)) {
		const node = freeId(new Set([...taken, copyId]), `n_${copyId}`, true);
		ops.push(flowInsert(survey, id, { type: 'block', id: node, block: copyId }));
	}
	return { id: copyId, ops };
}

export type DeletePlan = { ops: Invocation[] } | { refused: string };

/**
 * "Delete": the op, or why it cannot be done. A block's flow nodes go with it (in the
 * same transaction, so one undo restores both); anything else still referring to what is
 * deleted makes the server refuse unless `force`.
 */
export function deletePlan(survey: unknown, roots: readonly OutlineNode[], id: string, force = false): DeletePlan | undefined {
	const at = placeOf(roots, id);
	if (!at) return undefined;
	const f = force ? { force: true } : {};
	if (at.type === 'question') {
		if ((at.page?.children?.length ?? 0) <= 1)
			return { refused: 'A page needs at least one question. Delete the page instead.' };
		return { ops: [{ op: 'delete_question', params: { id, ...f } }] };
	}
	if (at.type === 'page') {
		if ((at.block.children?.length ?? 0) <= 1)
			return { refused: 'A block needs at least one page. Delete the block instead.' };
		return { ops: [{ op: 'delete_page', params: { id, ...f } }] };
	}
	const nodes = walk(survey)
		.filter((r) => r.type === 'block' && r.node.block === id)
		.map((r): Invocation => ({ op: 'delete_flow_node', params: { id: r.id } }));
	return { ops: [...nodes, { op: 'delete_block', params: { id, ...f } }] };
}

/** What to select after deleting `id`: the next sibling, else the previous, else the parent. */
export function neighbourOf(roots: readonly OutlineNode[], id: string): string | undefined {
	const at = placeOf(roots, id);
	if (!at) return undefined;
	const siblings =
		at.type === 'block' ? roots.filter((b) => b.type === 'block') : at.type === 'page' ? (at.block.children ?? []) : (at.page?.children ?? []);
	const i = siblings.findIndex((n) => n.id === id);
	const parent = at.type === 'block' ? undefined : at.type === 'page' ? at.block.id : at.page?.id;
	return siblings[i + 1]?.id ?? siblings[i - 1]?.id ?? parent;
}

export const KIND_NAME: Readonly<Record<StructureType, string>> = { block: 'block', page: 'page', question: 'question' };
