/** Question ops: add, delete, duplicate, move (port of `osp_ops.question_ops`). */

import { PAGE, PIPE, QUESTION, claimId, deleteWithRefs, freshId, get, insertAt, locate, setKey, subtreeIds } from '../doc.ts';
import { deepCopy, get as dget, has, isObj, reprStr, slice, strip, type Json, type JsonObject } from '../py.ts';
import { REVERSE_PATCH, OpError, op, type Ctx, type Invocation } from '../registry.ts';
import { normaliseText } from '../spec.ts';
import { Index, JsonDict, QuestionType, Text, def, flag, opt, params, req, str } from './params.ts';

export const DEFAULT_LABEL = 'New question';
export const DEFAULT_CHOICES: JsonObject[] = [{ value: 1, label: 'Option 1' }];
export const DEFAULT_ROWS: JsonObject[] = [
	{ id: 'r1', label: 'Row 1' },
	{ id: 'r2', label: 'Row 2' }
];

export function newQuestion(qid: string, qtype: string, label: Json = null): JsonObject {
	const q: JsonObject = { id: qid, type: qtype };
	q.label = label === null ? DEFAULT_LABEL : normaliseText(deepCopy(label));
	if (qtype === 'single' || qtype === 'multi' || qtype === 'matrix') q.choices = deepCopy(DEFAULT_CHOICES);
	if (qtype === 'matrix') q.rows = deepCopy(DEFAULT_ROWS);
	return q;
}

const TEXT_KEYS = ['label', 'help', 'constraintMessage', 'minLabel', 'maxLabel'];

/** Normalise every text of a question object in place (RT-D3). */
export function normaliseQuestionTexts(q: JsonObject): void {
	for (const key of TEXT_KEYS) if (has(q, key)) q[key] = normaliseText(q[key]!);
	for (const coll of ['choices', 'rows']) {
		const items = dget(q, coll);
		if (Array.isArray(items)) {
			for (const item of items) if (isObj(item) && has(item, 'label')) item.label = normaliseText(item.label!);
		}
	}
}

function pageItems(ctx: Ctx, pageId: string): Json[] {
	return get(ctx.doc, locate(ctx, pageId, PAGE).path).items as Json[];
}

function ownerPageId(ctx: Ctx, qpath: (string | number)[]): string {
	return get(ctx.doc, qpath.slice(0, -2)).id as string;
}

// --- add ------------------------------------------------------------------------------------------

const AddQuestion = params('AddQuestion', [
	req('page', str),
	def('type', QuestionType, 'text'),
	Index,
	opt('id', str),
	opt('label', Text),
	opt('question', JsonDict),
	opt('defaults', JsonDict)
]);

const NOT_DEFAULTABLE = new Set(['id', 'type', 'custom']);
const CUSTOM_PREFIX = 'custom.';

function applyDefaults(q: JsonObject, defaults: JsonObject): void {
	for (const key of Object.keys(defaults)) {
		const value = defaults[key]!;
		if (NOT_DEFAULTABLE.has(key) || (key.includes('.') && !key.startsWith(CUSTOM_PREFIX))) {
			throw new OpError('op.params', `${reprStr(slice(key, 0, 40))} cannot be a default for a new question`);
		}
		if (key.startsWith(CUSTOM_PREFIX)) {
			if (!has(q, 'custom')) q.custom = {};
			const custom = q.custom;
			if (!isObj(custom)) throw new OpError('op.params', '`custom` must be an object');
			setKey(custom, key.slice(CUSTOM_PREFIX.length), deepCopy(value));
		} else setKey(q, key, deepCopy(value));
	}
}

op('add_question', AddQuestion, { label: 'Add question', area: 'questions' }, (ctx, p): Invocation => {
	const items = pageItems(ctx, p.page);
	let q: JsonObject;
	let qid: string;
	if (p.question !== null) {
		q = deepCopy(p.question as JsonObject);
		qid = claimId(ctx, typeof dget(q, 'id') === 'string' ? (q.id as string) : p.id, 'q');
		q.id = qid;
		normaliseQuestionTexts(q);
	} else {
		qid = claimId(ctx, p.id, 'q');
		q = newQuestion(qid, p.type, p.label);
	}
	if (p.defaults !== null && Object.keys(p.defaults).length) applyDefaults(q, p.defaults);
	insertAt(items, p.index, q);
	ctx.touch();
	return { op: 'delete_question', params: { id: qid, force: true } };
});

// --- delete -----------------------------------------------------------------------------------------

const DeleteQuestion = params('DeleteQuestion', [req('id', str), flag('cascade'), flag('force')]);

op('delete_question', DeleteQuestion, { label: 'Delete question', area: 'questions' }, (ctx, p): Invocation => {
	const loc = locate(ctx, p.id, QUESTION);
	const pageId = ownerPageId(ctx, loc.path);
	if ((get(ctx.doc, loc.container) as Json[]).length === 1) {
		throw new OpError(
			'op.not_allowed',
			`'${p.id}' is the only question on page '${pageId}'; delete the page instead`,
			loc.pointer
		);
	}
	const [q, cascaded] = deleteWithRefs(ctx, loc, subtreeIds(get(ctx.doc, loc.path)), {
		cascade: p.cascade,
		force: p.force,
		what: `question '${p.id}'`
	});
	if (cascaded) return REVERSE_PATCH;
	return { op: 'add_question', params: { page: pageId, index: loc.index, question: q } };
});

// --- duplicate --------------------------------------------------------------------------------------

const DuplicateQuestion = params('DuplicateQuestion', [req('id', str), opt('new_id', str)]);

function renameSelf(node: Json, old: string, nu: string): Json {
	if (isObj(node)) {
		if (dget(node, 'kind') === 'ref' && dget(node, 'id') === old) return { ...node, id: nu };
		if (dget(node, 'pipe') === old && Object.keys(node).length === 1) return { pipe: nu };
		const out: JsonObject = {};
		for (const k of Object.keys(node)) setKey(out, k, renameSelf(node[k]!, old, nu));
		return out;
	}
	if (Array.isArray(node)) return node.map((v) => renameSelf(v, old, nu));
	if (typeof node === 'string') return node.replace(PIPE, (m: string, inner: string) => (strip(inner) === old ? `\${${nu}}` : m));
	return node;
}

op('duplicate_question', DuplicateQuestion, { label: 'Duplicate question', area: 'questions' }, (ctx, p): Invocation => {
	const loc = locate(ctx, p.id, QUESTION);
	const newId =
		p.new_id === null ? freshId(ctx.doc, `${slice(p.id, 0, 58)}_copy`, { exactFirst: true }) : claimId(ctx, p.new_id, 'q');
	const orig = get(ctx.doc, loc.path) as JsonObject;
	const copy: JsonObject = { id: newId };
	for (const k of Object.keys(orig)) if (k !== 'id' && k !== 'name') setKey(copy, k, renameSelf(orig[k]!, p.id, newId));
	(get(ctx.doc, loc.container) as Json[]).splice(loc.index + 1, 0, copy);
	ctx.touch();
	return { op: 'delete_question', params: { id: newId, force: true } };
});

// --- move -------------------------------------------------------------------------------------------

const MoveQuestion = params('MoveQuestion', [req('id', str), req('page', str), Index]);

op('move_question', MoveQuestion, { label: 'Move question', area: 'questions' }, (ctx, p): Invocation => {
	const loc = locate(ctx, p.id, QUESTION);
	const fromPage = ownerPageId(ctx, loc.path);
	const src = get(ctx.doc, loc.container) as Json[];
	if (src.length === 1 && fromPage !== p.page) {
		throw new OpError('op.not_allowed', `moving '${p.id}' would leave page '${fromPage}' empty`, loc.pointer);
	}
	const dest = pageItems(ctx, p.page);
	const q = src.splice(loc.index, 1)[0]!;
	insertAt(dest, p.index, q);
	ctx.touch();
	return { op: 'move_question', params: { id: p.id, page: fromPage, index: loc.index } };
});
