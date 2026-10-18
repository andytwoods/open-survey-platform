/** Flow ops: insert, delete and move a node with its subtree (port of `osp_ops.flow_ops`). */

import { NODE, claimId, flowNodes, get, insertAt, locate, setKey, type Loc } from '../doc.ts';
import { FLOW_NODE_TYPES } from '../models.ts';
import { S } from '../pyd.ts';
import { deepCopy, get as dget, has, type Json, type JsonObject } from '../py.ts';
import { OpError, op, type Ctx, type Invocation } from '../registry.ts';
import { Index, JsonDict, opt, params, req, str } from './params.ts';

const Arm = S.literal('then', 'else', 'children');
const ARMS: Record<string, string[]> = { branch: ['then', 'else'], randomiser: ['children'] };

function nodeList(ctx: Ctx, parent: string | null, arm: string | null): Json[] {
	if (parent === null) {
		if (arm !== null) throw new OpError('op.not_allowed', "the top-level flow has no arms; omit 'arm'");
		if (!has(ctx.d, 'flow')) ctx.d.flow = [];
		return ctx.d.flow as Json[];
	}
	const loc = locate(ctx, parent, NODE);
	const node = get(ctx.doc, loc.path) as JsonObject;
	const t = dget(node, 'type');
	const kind = t === undefined || t === null ? 'None' : String(t);
	const arms = has(ARMS, kind) ? ARMS[kind]! : [];
	if (!arms.length) throw new OpError('op.not_allowed', `flow node '${parent}' (${kind}) has no children`);
	const use = arm ?? arms[0]!;
	if (!arms.includes(use)) throw new OpError('op.not_allowed', `'${parent}' (${kind}) has ${arms.join(', ')}, not ${use}`);
	if (!has(node, use)) node[use] = [];
	return node[use] as Json[];
}

/** `{parent, arm}` params locating a node's list ({} for the top-level flow). */
function where(ctx: Ctx, loc: Loc): JsonObject {
	if (loc.path.length === 2) return {};
	const parent = get(ctx.doc, loc.path.slice(0, -2)) as JsonObject;
	return { parent: parent.id!, arm: loc.path[loc.path.length - 2] as string };
}

const InsertFlowNode = params('InsertFlowNode', [req('node', JsonDict), opt('parent', str), opt('arm', Arm), Index]);

op('insert_flow_node', InsertFlowNode, { label: 'Insert flow node', area: 'flow' }, (ctx, p): Invocation => {
	let node = deepCopy(p.node as JsonObject);
	const kind = dget(node, 'type');
	if (typeof kind !== 'string' || !FLOW_NODE_TYPES.includes(kind)) {
		throw new OpError('op.params', `node type must be one of ${FLOW_NODE_TYPES.join(', ')}`, '/node/type');
	}
	const nid = claimId(ctx, typeof dget(node, 'id') === 'string' ? (node.id as string) : null, kind);
	const rest: JsonObject = { type: kind, id: nid };
	for (const k of Object.keys(node)) if (k !== 'type' && k !== 'id') setKey(rest, k, node[k]!);
	node = rest;
	insertAt(nodeList(ctx, p.parent, p.arm), p.index, node);
	ctx.touch();
	return { op: 'delete_flow_node', params: { id: nid } };
});

const DeleteFlowNode = params('DeleteFlowNode', [req('id', str)]);

op('delete_flow_node', DeleteFlowNode, { label: 'Delete flow node', area: 'flow' }, (ctx, p): Invocation => {
	const loc = locate(ctx, p.id, NODE);
	const out: JsonObject = { ...where(ctx, loc), index: loc.index };
	out.node = (get(ctx.doc, loc.container) as Json[]).splice(loc.index, 1)[0]!;
	ctx.touch();
	return { op: 'insert_flow_node', params: out };
});

const MoveFlowNode = params('MoveFlowNode', [req('id', str), opt('parent', str), opt('arm', Arm), Index]);

op('move_flow_node', MoveFlowNode, { label: 'Move flow node', area: 'flow' }, (ctx, p): Invocation => {
	const loc = locate(ctx, p.id, NODE);
	const back: JsonObject = { id: p.id, ...where(ctx, loc), index: loc.index };
	const node = get(ctx.doc, loc.path) as JsonObject;
	if (p.parent !== null) {
		const inside = new Set<string>();
		for (const [, n] of flowNodes([node], [])) inside.add(n.id as string);
		if (inside.has(p.parent)) throw new OpError('op.not_allowed', `cannot move '${p.id}' into itself`, loc.pointer);
	}
	(get(ctx.doc, loc.container) as Json[]).splice(loc.index, 1);
	ctx.touch();
	insertAt(nodeList(ctx, p.parent, p.arm), p.index, node);
	ctx.touch();
	return { op: 'move_flow_node', params: back };
});
