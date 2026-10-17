import { describe, expect, it } from 'vitest';
import {
	addRowOps,
	deleteRowOps,
	describeSite,
	moveRowOps,
	referencingSites,
	renameRowOps,
	rowRequired,
	rowsEditorInputs,
	rowsOf,
	rowVariable,
	setRequiredOps,
	type RowsQuestion
} from './model';

const Q: RowsQuestion = {
	id: 'taste',
	required: true,
	rows: [
		{ id: 'tea', label: 'Tea', required: null },
		{ id: 'coffee', label: { en: 'Coffee', de: 'Kaffee' }, required: null },
		{ id: 'cocoa', label: 'Cocoa', required: false }
	]
};

const SURVEY = {
	metadata: { languages: ['en', 'de'], defaultLanguage: 'en' },
	blocks: [
		{
			id: 'b',
			pages: [
				{
					id: 'p',
					items: [
						{ id: 'intro', type: 'note', label: 'Hi' },
						{ id: 'taste', type: 'matrix', label: 'Rate', required: true, rows: Q.rows, choices: [] },
						{ id: 'cups', type: 'integer', label: { en: 'Cups?' } }
					]
				}
			]
		}
	]
};

describe('reading the survey', () => {
	it('finds a grid with its pointer and languages', () => {
		const inputs = rowsEditorInputs(SURVEY, 'taste');
		expect(inputs.question?.rows.map((r) => r.id)).toEqual(['tea', 'coffee', 'cocoa']);
		expect(inputs.question?.required).toBe(true);
		expect(inputs.pointer).toBe('/blocks/0/pages/0/items/1/rows');
		expect(inputs.defaultLanguage).toBe('en');
		expect(rowsEditorInputs(SURVEY, 'intro').question).toBeNull();
		expect(rowsEditorInputs(null, 'taste').question).toBeNull();
	});

	it('drops rows without a usable id and survives junk', () => {
		expect(rowsOf({ rows: [{ id: 'a', label: 'A' }, { id: 'a' }, { label: 'x' }, 7, null, { id: 'b', label: 5 }] })).toEqual([
			{ id: 'a', label: 'A', required: null },
			{ id: 'b', label: '', required: null }
		]);
		expect(rowsOf('nope')).toEqual([]);
	});

	it('a row follows the grid unless it says otherwise', () => {
		expect(Q.rows.map((r) => rowRequired(Q, r))).toEqual([true, true, false]);
		expect(rowVariable('taste', 'tea')).toBe('taste_tea');
	});
});

describe('op builders', () => {
	it('add / delete / move', () => {
		expect(addRowOps('taste')).toEqual([{ op: 'add_matrix_row', params: { question: 'taste', label: '' } }]);
		expect(addRowOps('taste', 'X', 0)[0].params).toEqual({ question: 'taste', label: 'X', index: 0 });
		expect(deleteRowOps(Q, 1)).toEqual([{ op: 'delete_matrix_row', params: { question: 'taste', row: 'coffee' } }]);
		expect(deleteRowOps(Q, 1, true)[0].params.force).toBe(true);
		expect(deleteRowOps({ ...Q, rows: [Q.rows[0]] }, 0)).toEqual([]);
		expect(deleteRowOps(Q, 9)).toEqual([]);
		expect(moveRowOps(Q, 0, 2)).toEqual([{ op: 'move_matrix_row', params: { question: 'taste', row: 'tea', index: 2 } }]);
		expect(moveRowOps(Q, 0, 0)).toEqual([]);
		expect(moveRowOps(Q, 0, 3)).toEqual([]);
	});

	it('rename edits one language and keeps the others', () => {
		expect(renameRowOps(Q, 0, 'Tea')).toEqual([]);
		expect(renameRowOps(Q, 0, 'Green tea')[0].params).toEqual({ question: 'taste', row: 'tea', label: 'Green tea' });
		const de = renameRowOps(Q, 1, 'Kaffee!', { lang: 'de', defaultLanguage: 'en' });
		expect(de[0].params.label).toEqual({ en: 'Coffee', de: 'Kaffee!' });
		const plainToDe = renameRowOps(Q, 0, 'Tee', { lang: 'de', defaultLanguage: 'en' });
		expect(plainToDe[0].params.label).toEqual({ en: 'Tea', de: 'Tee' });
		// A language with no text yet: an empty string is still a change.
		const fr = renameRowOps(Q, 1, '', { lang: 'fr', defaultLanguage: 'en' });
		expect(fr[0].params.label).toEqual({ en: 'Coffee', de: 'Kaffee', fr: '' });
	});

	it('required matching the grid goes back to following it', () => {
		expect(setRequiredOps(Q, 0, false)[0].params).toEqual({ question: 'taste', row: 'tea', required: false });
		expect(setRequiredOps(Q, 0, true)).toEqual([]);
		expect(setRequiredOps(Q, 2, true)[0].params).toEqual({ question: 'taste', row: 'cocoa', required: null });
		const optionalGrid = { ...Q, required: false };
		expect(setRequiredOps(optionalGrid, 0, true)[0].params.required).toBe(true);
		// An explicit setting equal to the grid's is dropped (the row follows the grid again).
		expect(setRequiredOps(optionalGrid, 2, false)[0].params.required).toBeNull();
		expect(setRequiredOps({ ...optionalGrid, rows: [{ id: 'x', label: 'X' }] }, 0, false)).toEqual([]);
	});
});

describe('naming the places that use a row', () => {
	it('describes question sites, flow and other pointers', () => {
		expect(describeSite(SURVEY, '/blocks/0/pages/0/items/2/showIf')).toBe('Cups? (condition)');
		expect(describeSite(SURVEY, '/blocks/0/pages/0/items/2/label/en', 'en')).toBe('Cups? (text)');
		expect(describeSite(SURVEY, '/flow/2/if')).toBe('Survey flow (/flow/2/if)');
		expect(describeSite(SURVEY, '/variables/0/expr')).toBe('/variables/0/expr');
		expect(describeSite(SURVEY, undefined)).toBe('the survey');
		expect(describeSite(null, '/blocks/9/pages/0/items/0/showIf')).toBe('/blocks/9/pages/0/items/0/showIf');
	});

	it('lists each site once, skipping the summary diagnostic', () => {
		const d = (pointer: string) => ({ severity: 'error' as const, code: 'op.dangling_ref', message: 'x', pointer });
		expect(
			referencingSites(SURVEY, [
				d('/blocks/0/pages/0/items/2/label/en'),
				d('/blocks/0/pages/0/items/2/label/en'),
				d('/blocks/0/pages/0/items/2/label/de'),
				d('/blocks/0/pages/0/items/2/showIf')
			])
		).toEqual(['Cups? (text)', 'Cups? (condition)']);
		expect(referencingSites(SURVEY, null)).toEqual([]);
	});
});
