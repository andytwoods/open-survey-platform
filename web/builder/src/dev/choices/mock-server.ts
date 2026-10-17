/**
 * A stand-in for the op endpoint on the /dev/choices page (test double, not product code:
 * the real rules live in osp-ops). Applies a transaction of choice ops to a copy of the
 * survey, all or nothing, so the editor can be driven end to end without a backend.
 * Invented content only; no real personal data.
 */
import type { ChoiceDiagnostic, ChoiceOp } from '#lib/choices/index.js';

type Json = Record<string, unknown>;
type Choice = { value: string | number; label: unknown };

export const SURVEY: Json = {
	metadata: { title: 'Choice editor sandbox', languages: ['en'], defaultLanguage: 'en' },
	choiceLists: [
		{
			id: 'agree5',
			choices: [
				{ value: 1, label: 'Strongly disagree' },
				{ value: 2, label: 'Disagree' },
				{ value: 3, label: 'Neither agree nor disagree' },
				{ value: 4, label: 'Agree' },
				{ value: 5, label: 'Strongly agree' }
			]
		},
		{ id: 'yesno', choices: [{ value: 1, label: 'Yes' }, { value: 0, label: 'No' }] }
	],
	blocks: [
		{
			id: 'b1',
			pages: [
				{
					id: 'p1',
					items: [
						{
							id: 'q_mood',
							type: 'single',
							label: 'How do you feel today?',
							choices: [
								{ value: 1, label: 'Good' },
								{ value: 2, label: 'Okay' },
								{ value: 3, label: 'Bad' }
							]
						},
						{ id: 'q_work', type: 'single', label: 'I enjoy my work.', choiceList: 'agree5' },
						{ id: 'q_team', type: 'single', label: 'My team supports me.', choiceList: 'agree5' },
						{ id: 'q_pets', type: 'multi', label: 'Which pets do you have?', choiceList: 'yesno' }
					]
				}
			]
		}
	]
};

/** A pretend condition elsewhere in the survey compares q_mood with code 2. */
const REFERENCED = { owner: 'q_mood', value: 2 };

class Reject extends Error {
	constructor(
		message: string,
		readonly diagnostic: ChoiceDiagnostic
	) {
		super(message);
	}
}

const key = (v: unknown) => String(v);
const items = (s: Json) =>
	(s.blocks as Json[]).flatMap((b) => (b.pages as Json[]).flatMap((p) => p.items as Json[]));

function owner(s: Json, id: string): { choices: Choice[]; ptr: string } {
	const lists = s.choiceLists as Json[];
	const li = lists.findIndex((l) => l.id === id);
	if (li >= 0) return { choices: lists[li].choices as Choice[], ptr: `/choiceLists/${li}/choices` };
	const q = items(s).find((q) => q.id === id);
	if (!q?.choices) throw new Reject(`no choices '${id}'`, { severity: 'error', code: 'op.not_found', message: `no owner '${id}'` });
	return { choices: q.choices as Choice[], ptr: `/blocks/0/pages/0/items/${items(s).indexOf(q)}/choices` };
}

function find(choices: Choice[], value: unknown, ptr: string): number {
	const i = choices.findIndex((c) => key(c.value) === key(value));
	if (i < 0) throw new Reject('not found', { severity: 'error', code: 'op.not_found', message: `no choice with code ${key(value)}`, pointer: ptr });
	return i;
}

function guardRef(o: string, value: unknown, ptr: string, i: number, force: unknown) {
	if (o === REFERENCED.owner && key(value) === key(REFERENCED.value) && !force) {
		throw new Reject('dangling', {
			severity: 'error',
			code: 'op.dangling_ref',
			message: `A condition compares q_mood with code ${key(value)}; update it first.`,
			pointer: `${ptr}/${i}/value`
		});
	}
}

function next(choices: Choice[]): number {
	return Math.max(0, ...choices.map((c) => (typeof c.value === 'number' ? c.value : 0))) + 1;
}

function apply1(s: Json, { op, params: p }: ChoiceOp) {
	switch (op) {
		case 'add_choice': {
			const { choices } = owner(s, p.owner as string);
			const value = (p.value as number | undefined) ?? next(choices);
			choices.splice((p.index as number | undefined) ?? choices.length, 0, { value, label: p.label ?? '' });
			return;
		}
		case 'delete_choice': {
			const { choices, ptr } = owner(s, p.owner as string);
			const i = find(choices, p.value, ptr);
			guardRef(p.owner as string, p.value, ptr, i, p.force);
			choices.splice(i, 1);
			return;
		}
		case 'move_choice': {
			const { choices, ptr } = owner(s, p.owner as string);
			const [c] = choices.splice(find(choices, p.value, ptr), 1);
			choices.splice(p.index as number, 0, c);
			return;
		}
		case 'set_choice': {
			const { choices, ptr } = owner(s, p.owner as string);
			const i = find(choices, p.value, ptr);
			if (p.new_value !== undefined && key(p.new_value) !== key(p.value)) {
				guardRef(p.owner as string, p.value, ptr, i, p.force);
				choices[i].value = p.new_value as string | number;
			}
			if (p.label !== undefined) choices[i].label = p.label;
			return;
		}
		case 'bulk_paste_choices': {
			const { choices } = owner(s, p.owner as string);
			const pasted = (p.text as string).split('\n').map((line) => {
				const [code, ...rest] = line.split('\t');
				return { value: /^-?\d+$/.test(code) ? Number(code) : code, label: rest.join('\t') };
			});
			choices.splice(p.mode === 'append' ? choices.length : 0, p.mode === 'append' ? 0 : choices.length, ...pasted);
			return;
		}
		case 'create_choice_list':
			(s.choiceLists as Json[]).push({ id: p.id, choices: p.choices });
			return;
		case 'set_property': {
			const q = items(s).find((q) => q.id === p.target);
			if (!q) throw new Reject('target', { severity: 'error', code: 'op.not_found', message: `no target ${p.target}` });
			if (p.unset) delete q[p.property as string];
			else q[p.property as string] = p.value;
			return;
		}
		default:
			throw new Reject('op', { severity: 'error', code: 'op.unknown', message: `unknown op ${op}` });
	}
}

/** Apply one transaction. Returns the new survey, or the rejection's diagnostics. */
export function applyOps(
	survey: Json,
	ops: ChoiceOp[]
): { ok: true; survey: Json } | { ok: false; diagnostics: ChoiceDiagnostic[] } {
	const s = JSON.parse(JSON.stringify(survey)) as Json;
	try {
		for (const o of ops) apply1(s, o);
		return { ok: true, survey: s };
	} catch (e) {
		if (e instanceof Reject) return { ok: false, diagnostics: [e.diagnostic] };
		throw e;
	}
}
