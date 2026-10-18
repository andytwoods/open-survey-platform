/** Page and block ops: add, delete, rename, move (port of `osp_ops.page_ops`). */

import { BLOCK, IDENT, PAGE, claimId, deleteWithRefs, freshId, get, insertAt, locate, subtreeIds, takenNames } from '../doc.ts';
import { S } from '../pyd.ts';
import { deepCopy, get as dget, has, pyLen, reprStr, slice, type Json, type JsonObject } from '../py.ts';
import { REVERSE_PATCH, OpError, op, type Ctx, type Invocation } from '../registry.ts';
import { newQuestion } from './question.ts';
import { Index, JsonDict, QuestionType, def, flag, opt, params, req, str } from './params.ts';

function newPage(ctx: Ctx, pid: string, qtype: string, also: Set<string>): JsonObject {
	// A page needs at least one item (osp-spec), so a new page starts with one question.
	const qid = freshId(ctx.doc, 'q', { also: new Set([pid, ...also]) });
	return { id: pid, items: [newQuestion(qid, qtype)] };
}

function adopt(ctx: Ctx, obj: JsonObject, prefix: string, explicit: string | null): string {
	const oid = claimId(ctx, typeof dget(obj, 'id') === 'string' ? (obj.id as string) : explicit, prefix);
	obj.id = oid;
	return oid;
}

// --- pages ------------------------------------------------------------------------------------------

const AddPage = params('AddPage', [
	req('block', str),
	Index,
	opt('id', str),
	def('question_type', QuestionType, 'text'),
	opt('page', JsonDict)
]);

op('add_page', AddPage, { label: 'Add page', area: 'pages' }, (ctx, p): Invocation => {
	const pages = get(ctx.doc, locate(ctx, p.block, BLOCK).path).pages as Json[];
	let page: JsonObject;
	let pid: string;
	if (p.page !== null) {
		page = deepCopy(p.page as JsonObject);
		pid = adopt(ctx, page, 'page', p.id);
	} else {
		pid = claimId(ctx, p.id, 'page');
		page = newPage(ctx, pid, p.question_type, new Set());
	}
	insertAt(pages, p.index, page);
	ctx.touch();
	return { op: 'delete_page', params: { id: pid, force: true } };
});

const DeleteById = params('DeleteById', [req('id', str), flag('cascade'), flag('force')]);

op('delete_page', DeleteById, { label: 'Delete page', area: 'pages' }, (ctx, p): Invocation => {
	const loc = locate(ctx, p.id, PAGE);
	const pages = get(ctx.doc, loc.container) as Json[];
	const blockId = get(ctx.doc, loc.container.slice(0, -1)).id as string;
	if (pages.length === 1) {
		throw new OpError(
			'op.not_allowed',
			`'${p.id}' is the only page of block '${blockId}'; delete the block instead`,
			loc.pointer
		);
	}
	const gone = subtreeIds(get(ctx.doc, loc.path));
	const [page, cascaded] = deleteWithRefs(ctx, loc, gone, { cascade: p.cascade, force: p.force, what: `page '${p.id}'` });
	if (cascaded) return REVERSE_PATCH;
	return { op: 'add_page', params: { block: blockId, index: loc.index, page } };
});

const RenamePage = params('RenamePage', [req('id', str), req('new_id', str)]);

op('rename_page', RenamePage, { label: 'Rename page', area: 'pages' }, (ctx, p): Invocation => {
	const loc = locate(ctx, p.id, PAGE);
	if (p.new_id !== p.id) {
		if (!IDENT.test(p.new_id) || pyLen(p.new_id) > 64) {
			throw new OpError('op.params', `${reprStr(slice(p.new_id, 0, 64))} is not a valid id`, '/new_id');
		}
		if (takenNames(ctx.doc).has(p.new_id)) {
			throw new OpError('op.duplicate_id', `id ${reprStr(p.new_id)} is already used`, '/new_id');
		}
		get(ctx.doc, loc.path).id = p.new_id;
		ctx.touch();
	}
	return { op: 'rename_page', params: { id: p.new_id, new_id: p.id } };
});

const MovePage = params('MovePage', [req('id', str), req('block', str), Index]);

op('move_page', MovePage, { label: 'Move page', area: 'pages' }, (ctx, p): Invocation => {
	const loc = locate(ctx, p.id, PAGE);
	const src = get(ctx.doc, loc.container) as Json[];
	const fromBlock = get(ctx.doc, loc.container.slice(0, -1)).id as string;
	if (src.length === 1 && fromBlock !== p.block) {
		throw new OpError('op.not_allowed', `moving '${p.id}' would leave block '${fromBlock}' empty`, loc.pointer);
	}
	const dest = get(ctx.doc, locate(ctx, p.block, BLOCK).path).pages as Json[];
	const page = src.splice(loc.index, 1)[0]!;
	insertAt(dest, p.index, page);
	ctx.touch();
	return { op: 'move_page', params: { id: p.id, block: fromBlock, index: loc.index } };
});

// --- blocks -----------------------------------------------------------------------------------------

const AddBlock = params('AddBlock', [
	Index,
	opt('id', str),
	opt('title', str),
	def('question_type', QuestionType, 'text'),
	opt('block', JsonDict)
]);

op('add_block', AddBlock, { label: 'Add block', area: 'blocks' }, (ctx, p): Invocation => {
	if (!has(ctx.d, 'blocks')) ctx.d.blocks = [];
	const blocks = ctx.d.blocks as Json[];
	let block: JsonObject;
	let bid: string;
	if (p.block !== null) {
		block = deepCopy(p.block as JsonObject);
		bid = adopt(ctx, block, 'block', p.id);
	} else {
		bid = claimId(ctx, p.id, 'block');
		const pid = freshId(ctx.doc, 'page', { also: new Set([bid]) });
		const page = newPage(ctx, pid, p.question_type, new Set([bid]));
		block = { id: bid, pages: [page] };
		if (p.title !== null) block = { id: bid, title: p.title, pages: [page] };
	}
	insertAt(blocks, p.index, block);
	ctx.touch();
	return { op: 'delete_block', params: { id: bid, force: true } };
});

op('delete_block', DeleteById, { label: 'Delete block', area: 'blocks' }, (ctx, p): Invocation => {
	const loc = locate(ctx, p.id, BLOCK);
	const gone = subtreeIds(get(ctx.doc, loc.path));
	const [block, cascaded] = deleteWithRefs(ctx, loc, gone, { cascade: p.cascade, force: p.force, what: `block '${p.id}'` });
	if (cascaded) return REVERSE_PATCH;
	return { op: 'add_block', params: { index: loc.index, block } };
});

const RenameBlock = params('RenameBlock', [req('id', str), req('title', S.nullable(str))]);

op('rename_block', RenameBlock, { label: 'Rename block', area: 'blocks' }, (ctx, p): Invocation => {
	const block = get(ctx.doc, locate(ctx, p.id, BLOCK).path) as JsonObject;
	const absent = !has(block, 'title');
	const old = absent ? null : block.title!;
	if (p.title === null) delete block.title;
	else block.title = p.title;
	const out: JsonObject = { target: p.id, property: 'title' };
	if (absent) out.unset = true;
	else out.value = old;
	return { op: 'set_property', params: out };
});

const MoveBlock = params('MoveBlock', [req('id', str), req('index', S.int({ ge: 0 }))]);

op('move_block', MoveBlock, { label: 'Move block', area: 'blocks' }, (ctx, p): Invocation => {
	const loc = locate(ctx, p.id, BLOCK);
	const blocks = get(ctx.doc, loc.container) as Json[];
	const block = blocks.splice(loc.index, 1)[0]!;
	insertAt(blocks, p.index, block);
	ctx.touch();
	return { op: 'move_block', params: { id: p.id, index: loc.index } };
});
