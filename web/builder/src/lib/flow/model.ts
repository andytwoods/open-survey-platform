/**
 * Pure helpers behind the flow editor (builder-design §3, task B8): read the survey's
 * flow tree, enumerate the places a node can go, build the op invocations for an edit,
 * and pin server diagnostics to nodes. Display and op-building only: the server decides
 * what is valid (AGENTS.md rule 8). Every function accepts hostile input and never throws.
 */
import { exprToText, textFor } from '../cards/logic';

export const NODE_TYPES = ['block', 'branch', 'randomiser', 'assign', 'quotaCheck', 'end'] as const;
export type FlowNodeType = (typeof NODE_TYPES)[number];
export type ArmName = 'then' | 'else' | 'children';

export const TYPE_LABEL: Readonly<Record<FlowNodeType, string>> = {
	block: 'Block',
	branch: 'Branch',
	randomiser: 'Randomiser',
	assign: 'Assign',
	quotaCheck: 'Quota check',
	end: 'End'
};

export const ARM_LABEL: Readonly<Record<ArmName, string>> = {
	then: 'Then',
	else: 'Otherwise',
	children: 'Children'
};

export type Json = Record<string, unknown>;

export interface FlowDiagnostic {
	code: string;
	message: string;
	pointer: string;
	severity: string;
}

export interface Invocation {
	op: string;
	params: Record<string, unknown>;
}

/** A node list's location: the top-level flow (parent null) or one arm of a container. */
export interface ListRef {
	parent: string | null;
	arm: ArmName | null;
}

/** A gap in a node list: insert or move a node to `index` of that list. */
export interface Slot extends ListRef {
	index: number;
	depth: number;
}

export interface FlowRow extends ListRef {
	id: string;
	type: FlowNodeType;
	node: Json;
	pointer: string;
	index: number;
	depth: number;
}

const isObj = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v);
const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string => (typeof v === 'string' ? v : '');

export function isNodeType(v: unknown): v is FlowNodeType {
	return typeof v === 'string' && (NODE_TYPES as readonly string[]).includes(v);
}

export function flowOf(survey: unknown): unknown[] {
	return isObj(survey) ? list(survey.flow) : [];
}

/** The arms a node type has, in display order. */
export function armsOf(type: unknown): ArmName[] {
	if (type === 'branch') return ['then', 'else'];
	if (type === 'randomiser') return ['children'];
	return [];
}

/** Every node in document order, with where it sits. */
export function walk(survey: unknown): FlowRow[] {
	const out: FlowRow[] = [];
	const visit = (nodes: unknown[], ref: ListRef, pointer: string, depth: number) => {
		nodes.forEach((n, index) => {
			if (!isObj(n) || !isNodeType(n.type) || typeof n.id !== 'string') return;
			const p = `${pointer}/${index}`;
			out.push({ ...ref, id: n.id, type: n.type, node: n, pointer: p, index, depth });
			for (const arm of armsOf(n.type)) visit(list(n[arm]), { parent: n.id, arm }, `${p}/${arm}`, depth + 1);
		});
	};
	visit(flowOf(survey), { parent: null, arm: null }, '/flow', 0);
	return out;
}

/** The node list at `ref`, or null if there is no such list. */
export function listAt(survey: unknown, ref: ListRef): unknown[] | null {
	if (ref.parent === null) return flowOf(survey);
	const row = walk(survey).find((r) => r.id === ref.parent);
	if (!row || !ref.arm || !armsOf(row.type).includes(ref.arm)) return null;
	return list(row.node[ref.arm]);
}

/** Number of nodes under a node (its whole subtree, not counting itself). */
export function descendantCount(node: unknown): number {
	if (!isObj(node)) return 0;
	let n = 0;
	for (const arm of armsOf(node.type)) for (const c of list(node[arm])) n += 1 + descendantCount(c);
	return n;
}

/** Every gap in document order. With `without`, that node's subtree is left out and the
 *  indexes are the ones `move_flow_node` expects (positions after removing it). */
export function slots(survey: unknown, without?: string): Slot[] {
	const out: Slot[] = [];
	const visit = (nodes: unknown[], ref: ListRef, depth: number) => {
		const kept = nodes.filter((n) => !(isObj(n) && without !== undefined && n.id === without));
		kept.forEach((n, i) => {
			out.push({ ...ref, index: i, depth });
			if (isObj(n) && typeof n.id === 'string' && isNodeType(n.type)) {
				for (const arm of armsOf(n.type)) visit(list(n[arm]), { parent: n.id, arm }, depth + 1);
			}
		});
		out.push({ ...ref, index: kept.length, depth });
	};
	visit(flowOf(survey), { parent: null, arm: null }, 0);
	return out;
}

const sameList = (a: ListRef, b: ListRef) => a.parent === b.parent && a.arm === b.arm;

/**
 * Alt+↑ / Alt+↓: the next gap before/after the node in document order, across levels
 * (into the arm of a neighbouring branch or randomiser, or out of the current one).
 * Null at either end of the flow, or for an unknown node.
 */
export function keyMoveTarget(survey: unknown, id: string, dir: -1 | 1): Slot | null {
	const row = walk(survey).find((r) => r.id === id);
	if (!row) return null;
	const all = slots(survey, id);
	const here = all.findIndex((s) => sameList(s, row) && s.index === row.index);
	if (here < 0) return null;
	return all[here + dir] ?? null;
}

/**
 * Dropping node `id` into the rendered gap `gap` (an index in the list as shown, node
 * still in place): the `move_flow_node` destination, or null for a no-op or a drop
 * inside the node's own subtree.
 */
export function dropTarget(survey: unknown, id: string, gap: ListRef & { index: number }): (ListRef & { index: number }) | null {
	const rows = walk(survey);
	const row = rows.find((r) => r.id === id);
	if (!row) return null;
	if (gap.parent !== null && inSubtree(rows, gap.parent, id)) return null;
	if (sameList(gap, row)) {
		if (gap.index === row.index || gap.index === row.index + 1) return null;
		return { parent: gap.parent, arm: gap.arm, index: gap.index > row.index ? gap.index - 1 : gap.index };
	}
	return { parent: gap.parent, arm: gap.arm, index: gap.index };
}

/** True if `id` is `root` or lies inside root's subtree. */
export function inSubtree(rows: FlowRow[], id: string, root: string): boolean {
	const byId = new Map(rows.map((r) => [r.id, r]));
	for (let cur = byId.get(id); cur; cur = cur.parent ? byId.get(cur.parent) : undefined) {
		if (cur.id === root) return true;
	}
	return false;
}

/** Params locating a list for insert/move (`parent`/`arm` omitted at the top level). */
export function whereParams(ref: ListRef & { index?: number }): Record<string, unknown> {
	const p: Record<string, unknown> = {};
	if (ref.parent !== null) {
		p.parent = ref.parent;
		if (ref.arm) p.arm = ref.arm;
	}
	if (ref.index !== undefined) p.index = ref.index;
	return p;
}

export function moveOp(id: string, to: ListRef & { index: number }): Invocation {
	return { op: 'move_flow_node', params: { id, ...whereParams(to) } };
}

// --- Survey lookups -------------------------------------------------------------------------

export interface BlockInfo {
	id: string;
	label: string;
	questions: number;
	placed: boolean;
}

export function blocks(survey: unknown): BlockInfo[] {
	if (!isObj(survey)) return [];
	const placed = new Set(walk(survey).filter((r) => r.type === 'block').map((r) => str(r.node.block)));
	return list(survey.blocks).flatMap((b) => {
		if (!isObj(b) || typeof b.id !== 'string') return [];
		const questions = list(b.pages).reduce<number>((n, p) => n + (isObj(p) ? list(p.items).length : 0), 0);
		return [{ id: b.id, label: str(b.title) || b.id, questions, placed: placed.has(b.id) }];
	});
}

export interface AssignedInfo {
	id: string;
	levels: string[];
}

export function assignedVariables(survey: unknown): AssignedInfo[] {
	if (!isObj(survey)) return [];
	return list(survey.variables).flatMap((v) =>
		isObj(v) && v.kind === 'assigned' && typeof v.id === 'string'
			? [{ id: v.id, levels: list(v.levels).map((l) => String(l)) }]
			: []
	);
}

export interface QuotaInfo {
	id: string;
	limit: number | null;
	when: string;
	onFull: string;
}

export function quotas(survey: unknown): QuotaInfo[] {
	if (!isObj(survey)) return [];
	return list(survey.quotas).flatMap((q) => {
		if (!isObj(q) || typeof q.id !== 'string') return [];
		const full = isObj(q.onFull) ? q.onFull : {};
		const parts = [full.block ? `show ${str(full.block)}` : '', `end “${str(full.outcome) || 'complete'}”`];
		return [
			{
				id: q.id,
				limit: typeof q.limit === 'number' ? q.limit : null,
				when: exprToText(q.when),
				onFull: parts.filter(Boolean).join(', then ')
			}
		];
	});
}

export function defaultLanguage(survey: unknown): string {
	const langs = isObj(survey) && isObj(survey.metadata) ? list(survey.metadata.languages) : [];
	return typeof langs[0] === 'string' ? langs[0] : 'en';
}

/** Every id and name in the survey (ids and names share one namespace server-side). */
export function takenIds(survey: unknown): Set<string> {
	const out = new Set<string>();
	const visit = (v: unknown, depth: number) => {
		if (depth > 64) return;
		if (Array.isArray(v)) for (const x of v) visit(x, depth + 1);
		else if (isObj(v)) {
			for (const k of ['id', 'name']) if (typeof v[k] === 'string') out.add(v[k] as string);
			for (const x of Object.values(v)) if (typeof x === 'object') visit(x, depth + 1);
		}
	};
	visit(survey, 0);
	return out;
}

export function freshId(survey: unknown, prefix: string): string {
	const taken = takenIds(survey);
	for (let i = 1; ; i++) if (!taken.has(`${prefix}_${i}`)) return `${prefix}_${i}`;
}

// --- Labels ---------------------------------------------------------------------------------

export function conditionText(node: unknown): string {
	return isObj(node) ? exprToText(node.if) : '';
}

/** A one-line description of a node, used as its card heading and accessible name. */
export function nodeLabel(node: unknown, survey?: unknown): string {
	if (!isObj(node)) return 'Unknown node';
	switch (node.type) {
		case 'block': {
			const b = blocks(survey).find((x) => x.id === node.block);
			return `Block: ${b?.label ?? (str(node.block) || '(none)')}`;
		}
		case 'branch':
			return `Branch: if ${conditionText(node) || '…'}`;
		case 'randomiser': {
			const n = list(node.children).length;
			return typeof node.pick === 'number' ? `Randomiser: ${node.pick} of ${n}` : `Randomiser: all ${n}, shuffled`;
		}
		case 'assign':
			return `Assign: ${list(node.variables).map(String).join(', ') || '(none)'}`;
		case 'quotaCheck':
			return `Quota check: ${str(node.quota) || '(none)'}`;
		case 'end':
			return `End: ${str(node.outcome) || 'complete'}`;
		default:
			return 'Unknown node';
	}
}

export function endMessage(node: unknown, language: string): string {
	return isObj(node) ? textFor(node.message, language) : '';
}

// --- Diagnostics ----------------------------------------------------------------------------

/** Pin each `/flow…` diagnostic to the deepest node whose pointer contains it. */
export function diagnosticsByNode(rows: FlowRow[], diagnostics: readonly FlowDiagnostic[]): Map<string, FlowDiagnostic[]> {
	const out = new Map<string, FlowDiagnostic[]>();
	const byPointer = [...rows].sort((a, b) => b.pointer.length - a.pointer.length);
	for (const d of diagnostics) {
		if (!d || typeof d.pointer !== 'string' || !d.pointer.startsWith('/flow/')) continue;
		const row = byPointer.find((r) => d.pointer === r.pointer || d.pointer.startsWith(r.pointer + '/'));
		if (!row) continue;
		out.set(row.id, [...(out.get(row.id) ?? []), d]);
	}
	return out;
}

export interface Flag {
	kind: 'unreachable' | 'empty' | 'error' | 'warning';
	label: string;
	/** Why, in plain words: the tooltip and the flag's accessible name. */
	explanation: string;
	code: string;
}

const EXPLAIN: Record<string, Omit<Flag, 'code'>> = {
	'flow.unreachable': {
		kind: 'unreachable',
		label: 'Unreachable',
		explanation:
			'Unreachable: an End node earlier in this list always ends the survey, so participants never reach this node.'
	},
	'flow.empty_branch': {
		kind: 'empty',
		label: 'Empty',
		explanation: 'Empty: this branch has no nodes under “Then”, so it does nothing when its condition is true.'
	}
};

export function flagFor(d: FlowDiagnostic): Flag {
	const known = EXPLAIN[d.code];
	if (known) return { ...known, code: d.code };
	const error = d.severity === 'error';
	return {
		kind: error ? 'error' : 'warning',
		label: error ? 'Error' : 'Warning',
		explanation: `${error ? 'Error' : 'Warning'}: ${d.message}`,
		code: d.code
	};
}

/** Blocks the validator reports as not placed anywhere in the flow. */
export function unusedBlocks(survey: unknown): BlockInfo[] {
	return blocks(survey).filter((b) => !b.placed);
}

// --- New nodes ------------------------------------------------------------------------------

export interface NewNodeForm {
	type: FlowNodeType;
	block: string;
	condition: string;
	randomiserBlock: string;
	variables: string[];
	quota: string;
	outcome: string;
	message: string;
}

export function emptyForm(survey: unknown, type: FlowNodeType = 'block'): NewNodeForm {
	const free = unusedBlocks(survey);
	const first = (free[0] ?? blocks(survey)[0])?.id ?? '';
	const assigned = new Set(
		walk(survey)
			.filter((r) => r.type === 'assign')
			.flatMap((r) => list(r.node.variables).map(String))
	);
	return {
		type,
		block: first,
		condition: '',
		randomiserBlock: first,
		variables: assignedVariables(survey)
			.map((v) => v.id)
			.filter((v) => !assigned.has(v)),
		quota: quotas(survey)[0]?.id ?? '',
		outcome: 'complete',
		message: ''
	};
}

/** Why a node type can't be added to this survey yet, or null if it can. */
export function unavailable(survey: unknown, type: FlowNodeType): string | null {
	if ((type === 'block' || type === 'randomiser') && !blocks(survey).length) return 'Add a block to the survey first.';
	if (type === 'assign' && !assignedVariables(survey).length) return 'Add an assigned variable (a between-subjects condition) first.';
	if (type === 'quotaCheck' && !quotas(survey).length) return 'Define a quota first.';
	return null;
}

/** Form problems the server would reject anyway, caught before sending. */
export function formError(f: NewNodeForm): string | null {
	if (f.type === 'block' && !f.block) return 'Choose a block.';
	if (f.type === 'branch' && !f.condition.trim()) return 'Enter a condition, e.g. consent == 0.';
	if (f.type === 'randomiser' && !f.randomiserBlock) return 'Choose a first block for the randomiser.';
	if (f.type === 'assign' && !f.variables.length) return 'Choose at least one variable.';
	if (f.type === 'quotaCheck' && !f.quota) return 'Choose a quota.';
	if (f.type === 'end' && f.outcome.trim() && !/^[A-Za-z_][A-Za-z0-9_]*$/.test(f.outcome.trim())) {
		return 'Outcome must be a name: letters, digits and _, not starting with a digit.';
	}
	return null;
}

/**
 * The ops (one transaction) that insert the node described by `f` at `at`, and the new
 * node's id. A branch is inserted with a placeholder condition that `set_condition`
 * replaces from the text in the same transaction (so it is one undo step).
 */
export function insertOps(survey: unknown, f: NewNodeForm, at: ListRef & { index?: number }, language = 'en'): { id: string; ops: Invocation[] } {
	const id = freshId(survey, f.type === 'quotaCheck' ? 'quota_check' : f.type);
	let node: Json;
	const after: Invocation[] = [];
	switch (f.type) {
		case 'block':
			node = { type: 'block', id, block: f.block };
			break;
		case 'branch':
			node = { type: 'branch', id, if: { kind: 'bool', value: true }, then: [] };
			after.push({ op: 'set_condition', params: { target: id, condition: f.condition.trim() } });
			break;
		case 'randomiser': {
			const taken = takenIds(survey);
			taken.add(id);
			let i = 1;
			while (taken.has(`block_${i}`)) i++;
			node = { type: 'randomiser', id, children: [{ type: 'block', id: `block_${i}`, block: f.randomiserBlock }] };
			break;
		}
		case 'assign':
			node = { type: 'assign', id, variables: [...f.variables] };
			break;
		case 'quotaCheck':
			node = { type: 'quotaCheck', id, quota: f.quota };
			break;
		case 'end':
			node = { type: 'end', id };
			if (f.outcome.trim() && f.outcome.trim() !== 'complete') node.outcome = f.outcome.trim();
			if (f.message.trim()) node.message = { [language]: f.message.trim() };
			break;
	}
	return { id, ops: [{ op: 'insert_flow_node', params: { node, ...whereParams(at) } }, ...after] };
}

/** set_property, or unset when `value` is undefined. */
export function setProp(target: string, property: string, value: unknown): Invocation {
	return value === undefined
		? { op: 'set_property', params: { target, property, unset: true } }
		: { op: 'set_property', params: { target, property, value } };
}

/** Describe a place for screen readers: "Then of Branch: if consent == 0, position 1". */
export function describeSlot(survey: unknown, slot: ListRef & { index: number }): string {
	const where =
		slot.parent === null
			? 'top level'
			: `${ARM_LABEL[slot.arm ?? 'then']} of ${nodeLabel(walk(survey).find((r) => r.id === slot.parent)?.node, survey)}`;
	return `${where}, position ${slot.index + 1}`;
}
