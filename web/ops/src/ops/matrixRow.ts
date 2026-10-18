/**
 * Matrix row ops: add, rename, move, set required, delete (port of `osp_ops.matrix_row_ops`).
 * Row `r` of grid `m` is the variable `m_r`, so a row id never changes once made.
 */

import { IDENT, QUESTION, get, handleRefs, insertAt, locate, refSites, takenNames, type Path } from '../doc.ts';
import { KEYWORDS } from '../models.ts';
import { toPointer } from '../patch.ts';
import { S } from '../pyd.ts';
import { deepCopy, get as dget, has, pyLen, reprStr, slice, truthy, type Json, type JsonObject } from '../py.ts';
import { REVERSE_PATCH, OpError, op, type Ctx, type Invocation } from '../registry.ts';
import { RESERVED_NAMES, normaliseText } from '../spec.ts';
import { Index, Text, def, flag, opt, params, req, str } from './params.ts';

const MAX_ID = 64;

function matrix(ctx: Ctx, qid: string): [JsonObject, Path] {
	const loc = locate(ctx, qid, QUESTION);
	const q = get(ctx.doc, loc.path) as JsonObject;
	if (dget(q, 'type') !== 'matrix') throw new OpError('op.not_allowed', `question '${qid}' is not a grid (matrix)`, loc.pointer);
	return [q, loc.path];
}

function find(q: JsonObject, path: Path, row: string): number {
	const rows = q.rows as JsonObject[];
	for (let i = 0; i < rows.length; i++) if (rows[i]!.id === row) return i;
	throw new OpError('op.not_found', `grid '${q.id as string}' has no row ${reprStr(slice(row, 0, 64))}`, toPointer(path));
}

/** Why `row` cannot be a new row id of `q`, or null. */
function free(ctx: Ctx, q: JsonObject, row: string): string | null {
	if (!IDENT.test(row)) return `${reprStr(slice(row, 0, 64))} is not a valid row id`;
	if ((q.rows as JsonObject[]).some((r) => r.id === row)) return `row id ${reprStr(row)} is already used in '${q.id as string}'`;
	const qid = q.id as string;
	const v = `${qid}_${row}`;
	const name = `${(truthy(dget(q, 'name')) ? q.name : qid) as string}_${row}`;
	if (pyLen(v) > MAX_ID || pyLen(name) > MAX_ID) {
		return `the row variable '${slice(v, 0, 70)}' would be longer than ${MAX_ID} characters`;
	}
	const taken = new Set([...takenNames(ctx.doc)].map((t) => t.toLowerCase()));
	if (taken.has(v.toLowerCase()) || taken.has(name.toLowerCase())) return `the row variable '${v}' is already used`;
	if (KEYWORDS.has(v) || RESERVED_NAMES.has(v.toLowerCase())) return `the row variable '${v}' is a reserved word`;
	return null;
}

function freshRow(ctx: Ctx, q: JsonObject): string {
	let n = (q.rows as Json[]).length + 1;
	while (free(ctx, q, `r${n}`) !== null) {
		n += 1;
		if (n > 100_000) throw new OpError('op.not_allowed', 'no free row id', '');
	}
	return `r${n}`;
}

// --- add / delete ---------------------------------------------------------------------------------

const AddMatrixRow = params('AddMatrixRow', [
	req('question', str),
	opt('id', str),
	def('label', Text, ''),
	opt('required', S.bool),
	Index
]);

op('add_matrix_row', AddMatrixRow, { label: 'Add grid row', area: 'rows' }, (ctx, p): Invocation => {
	const [q] = matrix(ctx, p.question);
	let rid: string;
	if (p.id === null) rid = freshRow(ctx, q);
	else {
		const why = free(ctx, q, p.id);
		if (why) throw new OpError(!IDENT.test(p.id) ? 'op.params' : 'op.duplicate_id', why, '/id');
		rid = p.id;
	}
	const row: JsonObject = { id: rid, label: normaliseText(deepCopy(p.label)) };
	if (p.required !== null) row.required = p.required;
	insertAt(q.rows as Json[], p.index, row);
	return { op: 'delete_matrix_row', params: { question: p.question, row: rid, force: true } };
});

const DeleteMatrixRow = params('DeleteMatrixRow', [req('question', str), req('row', str), flag('cascade'), flag('force')]);

op('delete_matrix_row', DeleteMatrixRow, { label: 'Delete grid row', area: 'rows' }, (ctx, p): Invocation => {
	const [q0, path] = matrix(ctx, p.question);
	const i = find(q0, path, p.row);
	if ((q0.rows as Json[]).length === 1) {
		throw new OpError('op.not_allowed', 'a grid needs at least one row', toPointer([...path, 'rows']));
	}
	const rowPath = [...path, 'rows', i];
	const sites = refSites(ctx.doc, new Set([`${p.question}_${p.row}`]), rowPath);
	const cascaded = handleRefs(ctx, sites, {
		cascade: p.cascade,
		force: p.force,
		what: `row '${p.row}' of '${p.question}'`
	});
	const q = get(ctx.doc, path) as JsonObject;
	const row = (q.rows as JsonObject[]).splice(i, 1)[0]!;
	if (cascaded) return REVERSE_PATCH;
	const inverse: JsonObject = { question: p.question, id: row.id!, label: row.label!, index: i };
	if (has(row, 'required') && row.required !== null) inverse.required = row.required!;
	return { op: 'add_matrix_row', params: inverse };
});

// --- move / rename / required ---------------------------------------------------------------------

const MoveMatrixRow = params('MoveMatrixRow', [req('question', str), req('row', str), req('index', S.int({ ge: 0 }))]);

op('move_matrix_row', MoveMatrixRow, { label: 'Move grid row', area: 'rows' }, (ctx, p): Invocation => {
	const [q, path] = matrix(ctx, p.question);
	const i = find(q, path, p.row);
	const rows = q.rows as Json[];
	const row = rows.splice(i, 1)[0]!;
	insertAt(rows, p.index, row);
	return { op: 'move_matrix_row', params: { question: p.question, row: p.row, index: i } };
});

const RenameMatrixRow = params('RenameMatrixRow', [req('question', str), req('row', str), req('label', Text)]);

op('rename_matrix_row', RenameMatrixRow, { label: 'Rename grid row', area: 'rows' }, (ctx, p): Invocation => {
	const [q, path] = matrix(ctx, p.question);
	const row = (q.rows as JsonObject[])[find(q, path, p.row)]!;
	const old = row.label!;
	row.label = normaliseText(deepCopy(p.label));
	return { op: 'rename_matrix_row', params: { question: p.question, row: p.row, label: old } };
});

const SetMatrixRowRequired = params('SetMatrixRowRequired', [req('question', str), req('row', str), req('required', S.nullable(S.bool))]);

op('set_matrix_row_required', SetMatrixRowRequired, { label: 'Set grid row required', area: 'rows' }, (ctx, p): Invocation => {
	const [q, path] = matrix(ctx, p.question);
	const row = (q.rows as JsonObject[])[find(q, path, p.row)]!;
	const old = has(row, 'required') ? row.required! : null;
	if (p.required === null) delete row.required;
	else row.required = p.required;
	return { op: 'set_matrix_row_required', params: { question: p.question, row: p.row, required: old } };
});
