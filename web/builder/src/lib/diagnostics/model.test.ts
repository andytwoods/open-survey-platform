import { describe, expect, it } from 'vitest';
import {
	SURVEY_ID,
	countItems,
	countsText,
	exportBadges,
	ownerOf,
	reasonOf,
	stripItems,
	type ExportDiagnostic
} from './model';

const SURVEY = {
	settings: { backNavigation: false },
	blocks: [
		{
			id: 'b1',
			pages: [
				{
					id: 'p1',
					items: [
						{ id: 'q1', type: 'single', choiceOrder: 'shuffle' },
						{ id: 'q2', type: 'text' }
					]
				}
			]
		}
	]
};

function xd(feature: string, level: ExportDiagnostic['level'], pointer: string, target = 'LimeSurvey'): ExportDiagnostic {
	const severity = level === 'unsupported' ? 'loss' : level === 'approximated' ? 'warning' : 'info';
	return {
		target: 'lss',
		severity,
		code: `lss.${level}`,
		feature,
		level,
		pointer,
		message: `${feature} is ${level} in ${target}: Because reasons for ${feature}.`
	};
}

describe('ownerOf', () => {
	it('finds the innermost block, page or question and the property below it', () => {
		expect(ownerOf(SURVEY, '/blocks/0/pages/0/items/0/choiceOrder')).toEqual({
			id: 'q1',
			type: 'question',
			properties: ['choiceOrder']
		});
		expect(ownerOf(SURVEY, '/blocks/0/pages/0/items/1/label/en')).toEqual({
			id: 'q2',
			type: 'question',
			properties: ['label.en', 'label']
		});
		expect(ownerOf(SURVEY, '/blocks/0/pages/0/title')).toMatchObject({ id: 'p1', type: 'page' });
		expect(ownerOf(SURVEY, '/blocks/0')).toMatchObject({ id: 'b1', type: 'block', properties: [] });
	});

	it('falls back to the survey for top-level and unknown pointers', () => {
		expect(ownerOf(SURVEY, '/settings/backNavigation')).toEqual({
			id: SURVEY_ID,
			type: 'survey',
			properties: ['settings.backNavigation', 'settings']
		});
		expect(ownerOf(SURVEY, '')).toMatchObject({ id: SURVEY_ID, properties: [] });
		expect(ownerOf(SURVEY, '/blocks/9/pages/0')).toMatchObject({ id: SURVEY_ID });
		expect(ownerOf(SURVEY, '/blocks/0/pages/7/items/0')).toMatchObject({ id: 'b1', type: 'block' });
		expect(ownerOf(null, '/blocks/0')).toMatchObject({ id: SURVEY_ID });
		expect(ownerOf('junk', '/x~1y/z~0')).toMatchObject({ properties: ['x/y.z~', 'x/y'] });
	});
});

describe('exportBadges', () => {
	it('maps approximated and unsupported features to badges on their card', () => {
		const diags = [
			xd('SingleQuestion.choiceOrder=shuffle', 'approximated', '/blocks/0/pages/0/items/0/choiceOrder'),
			xd('SingleQuestion.choiceList', 'lowered', '/blocks/0/pages/0/items/0/choiceList'),
			xd('Survey.version', 'unsupported', '/version'),
			xd('Page.title', 'unsupported', '/blocks/0/pages/0/title')
		];
		const badges = exportBadges(SURVEY, diags, 'lss');
		expect([...badges.keys()].sort()).toEqual([SURVEY_ID, 'p1', 'q1'].sort());
		expect(badges.get('q1')).toEqual([
			{
				level: 'approximated',
				label: 'Approximated in LimeSurvey',
				reasons: ['Because reasons for SingleQuestion.choiceOrder=shuffle.'],
				pointer: '/blocks/0/pages/0/items/0/choiceOrder',
				features: ['SingleQuestion.choiceOrder=shuffle']
			}
		]);
		expect(badges.get('p1')?.[0]).toMatchObject({ level: 'unsupported', label: 'Unsupported in LimeSurvey' });
		expect(badges.has('q2')).toBe(false); // lowered: behaviour kept, no badge
	});

	it('gives one badge per level, unsupported first, collecting distinct reasons', () => {
		const diags = [
			xd('A.x', 'approximated', '/blocks/0/pages/0/items/1/x'),
			xd('A.y', 'unsupported', '/blocks/0/pages/0/items/1/y'),
			xd('A.z', 'approximated', '/blocks/0/pages/0/items/1/z'),
			xd('A.z', 'approximated', '/blocks/0/pages/0/items/1/z')
		];
		const q2 = exportBadges(SURVEY, diags, 'xlsform').get('q2')!;
		expect(q2.map((b) => b.level)).toEqual(['unsupported', 'approximated']);
		expect(q2[0].label).toBe('Unsupported in XLSForm');
		expect(q2[1].reasons).toHaveLength(2);
		expect(q2[1].features).toEqual(['A.x', 'A.z']);
	});

	it('ignores errors, info and missing levels', () => {
		const err: ExportDiagnostic = { ...xd('', null, ''), severity: 'error', code: 'lss.error.invalid_survey' };
		expect(exportBadges(SURVEY, [err, xd('B.n', 'native', '/x')], 'lss').size).toBe(0);
	});

	it('uses the capability note as the reason', () => {
		expect(reasonOf(xd('Survey.version', 'unsupported', '/version'))).toBe('Because reasons for Survey.version.');
		const odd = { ...xd('X', 'unsupported', ''), message: 'plain text' };
		expect(reasonOf(odd)).toBe('plain text');
	});
});

describe('strip items and counts', () => {
	const validation = [
		{ severity: 'warning' as const, code: 'w', message: 'Hmm', pointer: '/blocks/0/pages/0/items/1/label' },
		{ severity: 'error' as const, code: 'e', message: 'Bad', pointer: '/settings/backNavigation' },
		{ severity: 'info' as const, code: 'i', message: 'FYI', pointer: '' }
	];
	const exported = [
		xd('Survey.version', 'unsupported', '/version'),
		xd('$missingStates', 'approximated', ''),
		xd('Lowered.thing', 'lowered', '/blocks/0')
	];

	it('orders errors, warnings, export issues, info, and says where each is', () => {
		const items = stripItems(SURVEY, validation, exported);
		expect(items.map((i) => i.kind)).toEqual(['error', 'warning', 'export', 'export', 'info']);
		expect(items[0].where).toBe('Survey · settings.backNavigation');
		expect(items[1].where).toBe('Question q2 · label');
		expect(items[1].owner.id).toBe('q2');
		expect(items[2]).toMatchObject({ level: 'unsupported', where: 'Survey · version', code: 'Survey.version' });
		expect(items[3].where).toBe('Whole survey');
	});

	it('counts and describes them for the live region', () => {
		const c = countItems(stripItems(SURVEY, validation, exported));
		expect(c).toEqual({ errors: 1, warnings: 1, exportIssues: 2 });
		expect(countsText(c, 'lss')).toBe('1 error, 1 warning, 2 export issues (LimeSurvey)');
		expect(countsText({ errors: 0, warnings: 2, exportIssues: 0 }, 'none')).toBe('0 errors, 2 warnings');
	});

	it('an export error (nothing exportable) is an export issue', () => {
		const err: ExportDiagnostic = {
			...xd('', null, '/blocks/0/pages/0/items/0'),
			severity: 'error',
			code: 'lss.error.invalid_survey',
			message: 'survey did not parse'
		};
		const [item] = stripItems(SURVEY, [], [err]);
		expect(item).toMatchObject({ kind: 'export', level: 'error', message: 'survey did not parse' });
		expect(item.owner.id).toBe('q1');
	});
});
