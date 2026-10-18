/**
 * Choice ops: add, delete, move, set, bulk paste (port of `osp_ops.choice_ops`).
 * `owner` is a choice list id, or a single/multi/matrix question with inline `choices`.
 */

import { CHOICE_LIST, QUESTION, choiceValueSites, get, handleRefs, insertAt, locate, type RefSite } from '../doc.ts';
import { toPointer } from '../patch.ts';
import { S } from '../pyd.ts';
import { PY_SPACE_CLASS, deepCopy, get as dget, isInt, repr, same, splitlines, strip, type Json, type JsonObject } from '../py.ts';
import { REVERSE_PATCH, OpError, op, type Ctx, type Invocation } from '../registry.ts';
import { normaliseText } from '../spec.ts';
import { ChoiceValue, Index, Text, def, flag, opt, params, req, str } from './params.ts';

const MAX_PASTE = 100_000;

export function ownerChoices(ctx: Ctx, owner: string): [JsonObject[], Set<string>, string] {
	const loc = locate(ctx, owner, QUESTION, CHOICE_LIST);
	const obj = get(ctx.doc, loc.path) as JsonObject;
	if (loc.kind === CHOICE_LIST) {
		const users = new Set<string>();
		for (const b of (dget(ctx.d, 'blocks') as JsonObject[] | undefined) ?? []) {
			for (const page of b.pages as JsonObject[]) {
				for (const q of page.items as JsonObject[]) if (dget(q, 'choiceList') === owner) users.add(q.id as string);
			}
		}
		return [obj.choices as JsonObject[], users, toPointer([...loc.path, 'choices'])];
	}
	const t = dget(obj, 'type');
	if (t !== 'single' && t !== 'multi' && t !== 'matrix') {
		throw new OpError('op.not_allowed', `question '${owner}' has no choices`, loc.pointer);
	}
	if (dget(obj, 'choices') === undefined || obj.choices === null) {
		const shared = dget(obj, 'choiceList');
		throw new OpError(
			'op.not_allowed',
			`question '${owner}' uses the shared list '${shared === undefined || shared === null ? 'None' : String(shared)}'; edit that list instead`,
			loc.pointer
		);
	}
	return [obj.choices as JsonObject[], new Set([owner]), toPointer([...loc.path, 'choices'])];
}

function findChoice(choices: JsonObject[], value: Json, ptr: string): number {
	for (let i = 0; i < choices.length; i++) if (same(choices[i]!.value!, value)) return i;
	throw new OpError('op.not_found', `no choice with code ${repr(value)}`, ptr);
}

export function nextCode(choices: JsonObject[]): number {
	let max = 0;
	let any = false;
	for (const c of choices) {
		if (isInt(c.value) && (!any || c.value > max)) {
			max = c.value;
			any = true;
		}
	}
	return max + 1;
}

/** A plain label for single-language surveys, else one in the default language. */
function defaultLabel(ctx: Ctx, label: string): Json {
	const md = (dget(ctx.d, 'metadata') ?? {}) as JsonObject;
	const langs = (dget(md, 'languages') as string[] | null | undefined) || [];
	if (langs.length <= 1) return label;
	const dl = dget(md, 'defaultLanguage');
	const key = typeof dl === 'string' && dl !== '' ? dl : langs[0]!;
	return { [key]: label };
}

function valueRefs(ctx: Ctx, users: Set<string>, value: Json): RefSite[] {
	return users.size ? choiceValueSites(ctx.doc, users, value) : [];
}

// --- add / delete -------------------------------------------------------------------------------

const AddChoice = params('AddChoice', [req('owner', str), def('label', Text, ''), opt('value', ChoiceValue), Index]);

op('add_choice', AddChoice, { label: 'Add choice', area: 'choices' }, (ctx, p): Invocation => {
	const [choices, , ptr] = ownerChoices(ctx, p.owner);
	const value = p.value === null ? nextCode(choices) : p.value;
	if (choices.some((c) => same(c.value!, value))) throw new OpError('op.not_allowed', `code ${repr(value)} is already used`, ptr);
	const label = normaliseText(deepCopy(p.label));
	insertAt(choices, p.index, { value, label });
	return { op: 'delete_choice', params: { owner: p.owner, value, force: true } };
});

const DeleteChoice = params('DeleteChoice', [req('owner', str), req('value', ChoiceValue), flag('cascade'), flag('force')]);

op('delete_choice', DeleteChoice, { label: 'Delete choice', area: 'choices' }, (ctx, p): Invocation => {
	const [choices, users, ptr] = ownerChoices(ctx, p.owner);
	const i = findChoice(choices, p.value, ptr);
	if (choices.length === 1) throw new OpError('op.not_allowed', 'a choice list needs at least one choice', ptr);
	const c = choices.splice(i, 1)[0]!;
	const cascaded = handleRefs(ctx, valueRefs(ctx, users, p.value), {
		cascade: p.cascade,
		force: p.force,
		what: `code ${repr(p.value)}`
	});
	if (cascaded) return REVERSE_PATCH;
	return { op: 'add_choice', params: { owner: p.owner, label: c.label!, value: c.value!, index: i } };
});

// --- move / set -----------------------------------------------------------------------------------

const MoveChoice = params('MoveChoice', [req('owner', str), req('value', ChoiceValue), req('index', S.int({ ge: 0 }))]);

op('move_choice', MoveChoice, { label: 'Move choice', area: 'choices' }, (ctx, p): Invocation => {
	const [choices, , ptr] = ownerChoices(ctx, p.owner);
	const i = findChoice(choices, p.value, ptr);
	const c = choices.splice(i, 1)[0]!;
	insertAt(choices, p.index, c);
	return { op: 'move_choice', params: { owner: p.owner, value: p.value, index: i } };
});

const SetChoice = params('SetChoice', [
	req('owner', str),
	req('value', ChoiceValue),
	opt('new_value', ChoiceValue),
	opt('label', Text),
	flag('force')
]);

op('set_choice', SetChoice, { label: 'Edit choice', area: 'choices' }, (ctx, p): Invocation => {
	const [choices, users, ptr] = ownerChoices(ctx, p.owner);
	const i = findChoice(choices, p.value, ptr);
	const c = choices[i]!;
	const old = deepCopy(c);
	let inverse: JsonObject = { owner: p.owner, value: p.value, force: true };
	if (p.new_value !== null && !same(p.new_value, p.value)) {
		if (choices.some((o) => same(o.value!, p.new_value))) {
			throw new OpError('op.not_allowed', `code ${repr(p.new_value)} is already used`, ptr);
		}
		const sites = valueRefs(ctx, users, p.value);
		if (sites.length && !p.force) {
			throw new OpError(
				'op.dangling_ref',
				`conditions compare with code ${repr(p.value)} at ` +
					sites
						.slice(0, 10)
						.map((s) => s.pointer)
						.join(', ') +
					'; update them first, or pass force: true',
				sites[0]!.pointer
			);
		}
		c.value = p.new_value;
		inverse = { ...inverse, value: p.new_value, new_value: old.value! };
	}
	if (p.label !== null) {
		c.label = normaliseText(deepCopy(p.label));
		inverse.label = old.label!;
	}
	return { op: 'set_choice', params: inverse };
});

// --- bulk paste ---------------------------------------------------------------------------------

const WS = `[${PY_SPACE_CLASS}]`;
const CODED = new RegExp(`^${WS}*([^\\t]+?)${WS}*\\t${WS}*(.*?)${WS}*$`, 'u');
const INT = /^-?[0-9]{1,15}$/;

/** One choice per non-blank line: `code<TAB>label`, or a bare label numbered from `start`. */
export function parsePaste(text: string, start: number): [Json, string][] {
	const out: [Json, string][] = [];
	let n = start;
	for (const line of splitlines(text)) {
		if (!strip(line)) continue;
		const m = CODED.exec(line);
		if (m) {
			const code: Json = INT.test(m[1]!) ? Number(m[1]!) || 0 : m[1]!;
			out.push([code, m[2]!]);
			if (typeof code === 'number') n = Math.max(n, code + 1);
		} else {
			out.push([n, strip(line)]);
			n += 1;
		}
	}
	return out;
}

const BulkPasteChoices = params('BulkPasteChoices', [
	req('owner', str),
	req('text', S.str({ max: MAX_PASTE })),
	def('mode', S.literal('replace', 'append'), 'replace'),
	flag('force')
]);

op('bulk_paste_choices', BulkPasteChoices, { label: 'Paste choices', area: 'choices' }, (ctx, p): Invocation => {
	const [choices, users, ptr] = ownerChoices(ctx, p.owner);
	const old = deepCopy(choices);
	const start = p.mode === 'replace' ? 1 : nextCode(choices);
	const pasted = parsePaste(p.text, start);
	if (!pasted.length) throw new OpError('op.not_allowed', 'nothing to paste: every line is blank', ptr);
	const fresh: JsonObject[] = pasted.map(([v, label]) => ({ value: v, label: defaultLabel(ctx, label) }));
	const result = p.mode === 'replace' ? fresh : [...choices, ...fresh];
	const seen: Json[] = [];
	for (const c of result) {
		if (seen.some((s) => same(c.value!, s))) throw new OpError('op.not_allowed', `code ${repr(c.value)} appears twice`, ptr);
		seen.push(c.value!);
	}
	if (p.mode === 'replace' && !p.force) {
		for (const c of old) {
			if (!seen.some((s) => same(c.value!, s))) {
				const sites = valueRefs(ctx, users, c.value!);
				if (sites.length) {
					throw new OpError(
						'op.dangling_ref',
						`code ${repr(c.value)} would be removed but conditions compare with it at ${sites[0]!.pointer}; keep it, or pass force: true`,
						sites[0]!.pointer
					);
				}
			}
		}
	}
	choices.splice(0, choices.length, ...result);
	return { op: 'set_property', params: { target: p.owner, property: 'choices', value: old } };
});
