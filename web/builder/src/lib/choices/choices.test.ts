import { describe, expect, it } from 'vitest';
import {
	choicesPointer,
	codeErrors,
	codeKey,
	editorInputs,
	labelFallback,
	labelIn,
	listUsage,
	nextCode,
	parseCode,
	splitDiagnostics,
	suggestListId,
	withLabel
} from './model';
import {
	addChoiceOps,
	deleteChoiceOps,
	detachOps,
	duplicateChoiceOps,
	makeSharedOps,
	moveChoiceOps,
	setCodeOps,
	setLabelOps,
	useListOps
} from './ops';
import { MAX_PASTE, parsePaste, pasteOps } from './paste';
import { dropIndex, dropSlot, keyMoveTarget } from './reorder';

const C = [
	{ value: 1, label: 'Good' },
	{ value: 2, label: 'Okay' },
	{ value: 3, label: 'Bad' }
];

describe('codes', () => {
	it('parses integer-looking codes as numbers, others as trimmed text', () => {
		expect(parseCode(' 7 ')).toBe(7);
		expect(parseCode('-2')).toBe(-2);
		expect(parseCode('SD')).toBe('SD');
		expect(parseCode('1.5')).toBe('1.5');
		expect(parseCode('1234567890123456')).toBe('1234567890123456');
	});

	it('treats 1 and "1" as the same code', () => {
		expect(codeKey(1)).toBe(codeKey('1'));
		expect(codeErrors(['1', '1 '])).toEqual(['Code 1 is used more than once.', 'Code 1 is used more than once.']);
	});

	it('flags empty, whitespace and duplicate codes per row', () => {
		expect(codeErrors(['1', '', 'a b', 'x', 'x', '2'])).toEqual([
			null,
			'A code is required.',
			'Codes cannot contain spaces.',
			'Code x is used more than once.',
			'Code x is used more than once.',
			null
		]);
		expect(codeErrors(['a\tb'])[0]).toBe('Codes cannot contain spaces.');
	});

	it('next code follows the highest integer code', () => {
		expect(nextCode(C)).toBe(4);
		expect(nextCode([{ value: 'a' }, { value: 9 }, { value: '20' }])).toBe(10);
		expect(nextCode([])).toBe(1);
	});
});

describe('labels', () => {
	it('reads exactly one language, with a fallback for placeholders', () => {
		expect(labelIn('Hi', 'fr')).toBe('Hi');
		expect(labelIn({ en: 'Hi', fr: 'Salut' }, 'fr')).toBe('Salut');
		expect(labelIn({ en: 'Hi' }, 'fr')).toBe('');
		expect(labelFallback({ en: 'Hi' }, 'fr')).toBe('Hi');
		expect(labelIn(null)).toBe('');
		expect(labelIn(42 as unknown)).toBe('');
	});

	it('keeps plain labels plain in the default language and maps other languages', () => {
		expect(withLabel('Hi', 'Hello')).toBe('Hello');
		expect(withLabel('Hi', 'Hello', 'en', 'en')).toBe('Hello');
		expect(withLabel('Hi', 'Salut', 'fr', 'en')).toEqual({ en: 'Hi', fr: 'Salut' });
		expect(withLabel({ en: 'Hi' }, 'Salut', 'fr', 'en')).toEqual({ en: 'Hi', fr: 'Salut' });
		expect(withLabel({ en: 'Hi', fr: 'x' }, 'Hello', undefined, 'en')).toEqual({ en: 'Hello', fr: 'x' });
	});
});

describe('op generation', () => {
	it('add / duplicate / delete', () => {
		expect(addChoiceOps('q1')).toEqual([{ op: 'add_choice', params: { owner: 'q1', label: '' } }]);
		expect(addChoiceOps('q1', 'New', 0)).toEqual([{ op: 'add_choice', params: { owner: 'q1', label: 'New', index: 0 } }]);
		expect(duplicateChoiceOps('q1', C, 1)).toEqual([{ op: 'add_choice', params: { owner: 'q1', label: 'Okay', index: 2 } }]);
		expect(deleteChoiceOps('q1', C, 2)).toEqual([{ op: 'delete_choice', params: { owner: 'q1', value: 3 } }]);
		expect(deleteChoiceOps('q1', [C[0]], 0)).toEqual([]);
		expect(deleteChoiceOps('q1', C, 9)).toEqual([]);
	});

	it('duplicating copies a translated label instead of sharing it', () => {
		const label = { en: 'Hi', fr: 'Salut' };
		const [op] = duplicateChoiceOps('q1', [{ value: 1, label }], 0);
		expect(op.params.label).toEqual(label);
		expect(op.params.label).not.toBe(label);
	});

	it('move uses the final index, one op per gesture, nothing for a no-op', () => {
		expect(moveChoiceOps('L', C, 0, 2)).toEqual([{ op: 'move_choice', params: { owner: 'L', value: 1, index: 2 } }]);
		expect(moveChoiceOps('L', C, 2, 0)).toEqual([{ op: 'move_choice', params: { owner: 'L', value: 3, index: 0 } }]);
		expect(moveChoiceOps('L', C, 1, 1)).toEqual([]);
		expect(moveChoiceOps('L', C, 0, 3)).toEqual([]);
		expect(moveChoiceOps('L', C, 0, -1)).toEqual([]);
	});

	it('code changes send a typed code and never an invalid one', () => {
		expect(setCodeOps('q1', C, 0, '10')).toEqual([{ op: 'set_choice', params: { owner: 'q1', value: 1, new_value: 10 } }]);
		expect(setCodeOps('q1', C, 0, 'good')).toEqual([{ op: 'set_choice', params: { owner: 'q1', value: 1, new_value: 'good' } }]);
		expect(setCodeOps('q1', C, 0, '1')).toEqual([]);
		expect(setCodeOps('q1', C, 0, '2')).toEqual([]);
		expect(setCodeOps('q1', C, 0, 'a b')).toEqual([]);
		expect(setCodeOps('q1', C, 0, '  ')).toEqual([]);
		expect(setCodeOps('q1', [{ value: '1', label: 'x' }], 0, '1')).toEqual([]);
	});

	it('label changes only when the text changed, in the editing language', () => {
		expect(setLabelOps('q1', C, 0, 'Great')).toEqual([{ op: 'set_choice', params: { owner: 'q1', value: 1, label: 'Great' } }]);
		expect(setLabelOps('q1', C, 0, 'Good')).toEqual([]);
		expect(setLabelOps('q1', C, 0, 'Bien', { lang: 'fr', defaultLanguage: 'en' })).toEqual([
			{ op: 'set_choice', params: { owner: 'q1', value: 1, label: { en: 'Good', fr: 'Bien' } } }
		]);
		// An empty translation is still a change when the language had none.
		const t = [{ value: 1, label: { en: 'Good' } }];
		expect(setLabelOps('q1', t, 0, '', { lang: 'fr', defaultLanguage: 'en' })).toHaveLength(1);
		expect(setLabelOps('q1', t, 0, 'Good', { lang: 'en' })).toEqual([]);
	});

	it('shared lists: use, make shared, detach', () => {
		const inline = { id: 'q1', choices: C, choiceList: null };
		expect(useListOps(inline, 'agree5')).toEqual([
			{ op: 'set_property', params: { target: 'q1', property: 'choiceList', value: 'agree5' } },
			{ op: 'set_property', params: { target: 'q1', property: 'choices', unset: true } }
		]);
		const sharedQ = { id: 'q2', choiceList: 'agree5' };
		expect(useListOps(sharedQ, 'yesno')).toEqual([
			{ op: 'set_property', params: { target: 'q2', property: 'choiceList', value: 'yesno' } }
		]);
		expect(useListOps(sharedQ, 'agree5')).toEqual([]);
		expect(makeSharedOps(inline, 'q1_choices')).toEqual([
			{ op: 'create_choice_list', params: { id: 'q1_choices', choices: C } },
			{ op: 'set_property', params: { target: 'q1', property: 'choiceList', value: 'q1_choices' } },
			{ op: 'set_property', params: { target: 'q1', property: 'choices', unset: true } }
		]);
		expect(makeSharedOps(inline, '1bad')).toEqual([]);
		expect(makeSharedOps(inline, 'has space')).toEqual([]);
		expect(detachOps(sharedQ, C)).toEqual([
			{ op: 'set_property', params: { target: 'q2', property: 'choices', value: C } },
			{ op: 'set_property', params: { target: 'q2', property: 'choiceList', unset: true } }
		]);
		expect(detachOps(inline, C)).toEqual([]);
	});

	it('suggests a free, valid list id', () => {
		expect(suggestListId('q1', [])).toBe('q1_choices');
		expect(suggestListId('q1', ['q1_choices', 'q1_choices_2'])).toBe('q1_choices_3');
		expect(suggestListId('9-x', [])).toBe('_9_x_choices');
	});
});

describe('bulk paste parsing', () => {
	it('auto-codes bare labels from 1 (replace)', () => {
		const p = parsePaste('Strongly disagree\n\nDisagree\r\nAgree\n', C, 'replace');
		expect(p.rows.map((r) => [r.line, r.code, r.label, r.auto])).toEqual([
			[1, 1, 'Strongly disagree', true],
			[3, 2, 'Disagree', true],
			[4, 3, 'Agree', true]
		]);
		expect(p.errors).toBe(0);
		expect(p.text).toBe('1\tStrongly disagree\n2\tDisagree\n3\tAgree');
	});

	it('reads leading numbers as codes when every line has one', () => {
		const p = parsePaste('1 Strongly disagree\n2. Disagree\n3) Neutral\n4 = Agree\n5 - Strongly agree\n99: Don\'t know');
		expect(p.rows.map((r) => [r.code, r.label, r.auto])).toEqual([
			[1, 'Strongly disagree', false],
			[2, 'Disagree', false],
			[3, 'Neutral', false],
			[4, 'Agree', false],
			[5, 'Strongly agree', false],
			[99, "Don't know", false]
		]);
	});

	it('keeps a leading number in the label when other lines have none', () => {
		const p = parsePaste('None\n1 or 2\n3 or more');
		expect(p.rows.map((r) => [r.code, r.label])).toEqual([
			[1, 'None'],
			[2, '1 or 2'],
			[3, '3 or more']
		]);
	});

	it('reads tab-separated code and label (spreadsheet columns), any code', () => {
		const p = parsePaste('SD\tStrongly disagree\nD\t Disagree \n\tBare');
		expect(p.rows.map((r) => [r.code, r.label, r.auto])).toEqual([
			['SD', 'Strongly disagree', false],
			['D', 'Disagree', false],
			[1, 'Bare', true]
		]);
		expect(p.mixed).toBe(true);
	});

	it('append continues after the highest code and flags codes already in the list', () => {
		const p = parsePaste('Terrible\n2\tOkay again', C, 'append');
		expect(p.rows[0]).toMatchObject({ code: 4, auto: true, error: null });
		expect(p.rows[1]).toMatchObject({ code: 2, error: 'Code 2 is already in the list.' });
		expect(p.errors).toBe(1);
		expect(pasteOps('q1', p, 'append')).toEqual([]);
	});

	it('flags duplicates, whitespace codes and empty labels', () => {
		const p = parsePaste('1\tA\n1\tB\na b\tC\n7\t');
		expect(p.rows.map((r) => r.error)).toEqual([
			'Code 1 is used more than once.',
			'Code 1 is used more than once.',
			'Codes cannot contain spaces.',
			null
		]);
		expect(p.rows[3].warning).toBe('Empty label.');
		// Auto codes collide with a later explicit code exactly as the server's would.
		expect(parsePaste('A\n1\tB').rows[1].error).toBe('Code 1 is used more than once.');
	});

	it('explicit integer codes move the auto counter on (like the server)', () => {
		const p = parsePaste('10\tTen\nNext');
		expect(p.rows.map((r) => r.code)).toEqual([10, 11]);
	});

	it('blank or oversized pastes are problems, not ops', () => {
		const blank = parsePaste(' \n\t\n');
		expect(blank.rows).toEqual([]);
		expect(blank.problems).toEqual(['Nothing to paste: every line is blank.']);
		expect(pasteOps('q1', blank, 'replace')).toEqual([]);
		const big = parsePaste('x'.repeat(MAX_PASTE + 1));
		expect(big.problems[0]).toMatch(/^Too long/);
		expect(parsePaste(undefined as unknown as string).rows).toEqual([]);
	});

	it('a clean preview is one bulk_paste_choices with every code explicit', () => {
		const p = parsePaste('1 Strongly disagree\n2 Disagree');
		expect(pasteOps('agree5', p, 'replace')).toEqual([
			{ op: 'bulk_paste_choices', params: { owner: 'agree5', text: '1\tStrongly disagree\n2\tDisagree', mode: 'replace' } }
		]);
	});
});

describe('reorder', () => {
	const mids = [10, 30, 50, 70];
	it('drop index from the dragged row midpoint', () => {
		expect(dropIndex(mids, 10, 0)).toBe(0);
		expect(dropIndex(mids, 55, 0)).toBe(2);
		expect(dropIndex(mids, 99, 0)).toBe(3);
		expect(dropIndex(mids, 0, 3)).toBe(0);
		expect(dropIndex(mids, 35, 3)).toBe(2);
	});
	it('drop slot is the gap the indicator marks', () => {
		expect(dropSlot(0, 2)).toBe(3);
		expect(dropSlot(3, 0)).toBe(0);
		expect(dropSlot(1, 1)).toBeNull();
	});
	it('Alt+↑/↓ only, stopping at the edges', () => {
		const k = (key: string, altKey = true) => ({ key, altKey, ctrlKey: false, metaKey: false, shiftKey: false });
		expect(keyMoveTarget(k('ArrowUp'), 2, 4)).toBe(1);
		expect(keyMoveTarget(k('ArrowDown'), 2, 4)).toBe(3);
		expect(keyMoveTarget(k('ArrowUp'), 0, 4)).toBeNull();
		expect(keyMoveTarget(k('ArrowDown'), 3, 4)).toBeNull();
		expect(keyMoveTarget(k('ArrowDown', false), 1, 4)).toBeNull();
		expect(keyMoveTarget({ ...k('ArrowDown'), shiftKey: true }, 1, 4)).toBeNull();
	});
});

describe('reading the survey', () => {
	const survey = {
		metadata: { languages: ['en', 'fr'], defaultLanguage: 'en' },
		choiceLists: [
			{ id: 'agree5', choices: [{ value: 1, label: 'x' }] },
			{ id: 'unused', choices: [{ value: 1, label: 'y' }] }
		],
		blocks: [
			{
				pages: [
					{ items: [{ id: 'q0', type: 'note' }, { id: 'q1', type: 'single', choices: C }] },
					{ items: [{ id: 'q2', type: 'single', choiceList: 'agree5' }, { id: 'q3', type: 'multi', choiceList: 'agree5' }] }
				]
			}
		]
	};

	it('counts the questions using each list', () => {
		expect(listUsage(survey)).toEqual({ agree5: ['q2', 'q3'], unused: [] });
		expect(listUsage(null)).toEqual({});
		expect(listUsage({ blocks: 'nope' })).toEqual({});
	});

	it('points at inline choices or the shared list', () => {
		expect(choicesPointer(survey, 'q1')).toBe('/blocks/0/pages/0/items/1/choices');
		expect(choicesPointer(survey, 'q2')).toBe('/choiceLists/0/choices');
		expect(choicesPointer(survey, 'nope')).toBeUndefined();
	});

	it('gathers the editor inputs', () => {
		const inp = editorInputs(survey, 'q2');
		expect(inp.question).toMatchObject({ id: 'q2', choiceList: 'agree5', choices: null });
		expect(inp.languages).toEqual(['en', 'fr']);
		expect(inp.defaultLanguage).toBe('en');
		expect(editorInputs({}, 'q1').question).toBeNull();
	});

	it('routes diagnostics to rows by pointer', () => {
		const d = (pointer: string) => ({ severity: 'error' as const, code: 'x', message: pointer, pointer });
		const { rows, general } = splitDiagnostics(
			[d('/choiceLists/0/choices/2/value'), d('/choiceLists/0/choices/2'), d('/choiceLists/0/choices'), d('/choiceLists/10/choices/1')],
			'/choiceLists/0/choices'
		);
		expect([...rows.keys()]).toEqual([2]);
		expect(rows.get(2)).toHaveLength(2);
		expect(general.map((g) => g.pointer)).toEqual(['/choiceLists/0/choices', '/choiceLists/10/choices/1']);
		expect(splitDiagnostics([d('/a/0')], undefined).general).toHaveLength(1);
		expect(splitDiagnostics(null, '/a').general).toEqual([]);
	});
});
