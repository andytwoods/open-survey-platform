import { describe, expect, it } from 'vitest';
import {
	groupDiagnostics,
	MAX_BYTES,
	readSurveyFile,
	summaryLines,
	typeLabel,
	validationNote,
	type ImportDiagnostic,
	type ImportPreview,
	type ImportSummary
} from './model';

const d = (severity: ImportDiagnostic['severity'], code: string): ImportDiagnostic => ({
	format: 'qsf',
	severity,
	code,
	feature: code,
	pointer: '/x',
	message: code,
	target: null
});

const summary: ImportSummary = {
	title: 'T',
	languages: ['en', 'de'],
	blocks: 2,
	pages: 3,
	questions: 7,
	byType: { single: 3, text: 2, note: 1, matrix: 1, slider: 0 },
	choiceLists: 0,
	variables: 2,
	quotas: 1,
	flowNodes: 5,
	conditions: 4,
	losses: 1,
	warnings: 1,
	infos: 2
};

const preview = (validation: ImportPreview['validation']): ImportPreview => ({
	format: 'qsf',
	ok: true,
	title: 'T',
	summary,
	diagnostics: [],
	validation
});

describe('import preview model', () => {
	it('groups diagnostics by what the reader must do about them', () => {
		const g = groupDiagnostics([d('info', 'a'), d('loss', 'b'), d('warning', 'c'), d('loss', 'e'), d('error', 'f')]);
		expect(g.losses.map((x) => x.code)).toEqual(['b', 'e']);
		expect(g.warnings.map((x) => x.code)).toEqual(['c']);
		expect(g.infos.map((x) => x.code)).toEqual(['a']);
		expect(g.errors.map((x) => x.code)).toEqual(['f']);
	});

	it('describes what will be created in plain words', () => {
		expect(summaryLines(summary)).toEqual([
			'7 questions on 3 pages in 2 blocks (3 single choice, 2 text, 1 note, 1 grid)',
			'Languages: en, de',
			'4 conditions (show-if, validation, branches)',
			'2 variables',
			'1 quota',
			'5 flow steps'
		]);
		expect(summaryLines({ ...summary, questions: 1, pages: 1, blocks: 1, byType: {}, languages: ['en'], conditions: 0, variables: 0, quotas: 0, flowNodes: 2 })).toEqual([
			'1 question on 1 page in 1 block'
		]);
		expect(typeLabel('matrix')).toBe('grid');
		expect(typeLabel('odd')).toBe('odd');
	});

	it('sums up the validator view of the draft', () => {
		expect(validationNote(preview([]))).toBeNull();
		expect(validationNote(preview([{ severity: 'warning', code: 'x', message: 'm', pointer: '' }]))).toBe(
			'The editor will show 1 warning (for example missing translations).'
		);
		expect(
			validationNote(
				preview([
					{ severity: 'error', code: 'x', message: 'm', pointer: '' },
					{ severity: 'error', code: 'y', message: 'm', pointer: '' },
					{ severity: 'warning', code: 'z', message: 'm', pointer: '' }
				])
			)
		).toBe('The editor will show 2 errors to fix.');
	});

	it('reads a file as text and refuses oversized ones before reading', async () => {
		expect(await readSurveyFile(new File(['{"pages": []}'], 's.json'))).toEqual({ content: '{"pages": []}' });
		const big = { name: 'big.lss', size: MAX_BYTES + 1, text: async () => 'x' } as unknown as File;
		expect(await readSurveyFile(big)).toEqual({ error: 'big.lss is larger than 20 MB.' });
	});
});
