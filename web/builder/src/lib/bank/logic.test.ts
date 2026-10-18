import { describe, expect, it } from 'vitest';
import { outlineFromSurvey } from '../model/outline';
import {
	addedObjectId,
	describeDestination,
	destinationAtSelection,
	destinationFromGap,
	exportFileName,
	fragmentItems,
	fragmentVariables,
	hasNewerVersion,
	insertNotice,
	insertOp,
	insertedVersion,
	itemLines,
	labelDiff,
	noticeShownOnce,
	ownSources,
	parseTags,
	provenanceLabel
} from './logic';

const SURVEY = {
	id: 's',
	metadata: { languages: ['en'] },
	blocks: [
		{
			id: 'b1',
			title: 'Intro',
			pages: [
				{ id: 'p1', title: { en: 'First' }, items: [{ id: 'qa', type: 'text', label: 'A' }, { id: 'qb', type: 'text', label: 'B' }] },
				{ id: 'p2', items: [{ id: 'qc', type: 'text', label: 'C' }] }
			]
		},
		{
			id: 'phq2_block',
			title: 'PHQ-2',
			source: { bank: 'phq2', version: 1, library: 'bundled', item: 'phq2_block' },
			pages: [{ id: 'phq2_page', items: [{ id: 'phq2', type: 'matrix', label: 'Over…', rows: [{ id: 'q1', label: 'r1' }], choices: [{ value: 0, label: 'No' }] }] }]
		}
	],
	flow: [
		{ type: 'block', id: 'n1', block: 'b1' },
		{ type: 'block', id: 'n2', block: 'phq2_block' }
	]
};
const roots = outlineFromSurvey(SURVEY);

describe('sources in a survey', () => {
	it('lists the objects with their own source and the highest inserted version', () => {
		expect(ownSources(SURVEY)).toEqual([{ id: 'phq2_block', type: 'block', source: SURVEY.blocks[1].source }]);
		expect(insertedVersion(SURVEY, 'phq2')).toBe(1);
		expect(insertedVersion(SURVEY, 'gad7')).toBeNull();
		expect(hasNewerVersion({ id: 'phq2', version: 2 }, SURVEY)).toBe(true);
		expect(hasNewerVersion({ id: 'phq2', version: 1 }, SURVEY)).toBe(false);
		expect(ownSources(null)).toEqual([]);
	});
});

describe('destinations', () => {
	it('inserts at the selection by kind', () => {
		expect(destinationAtSelection('question', roots, SURVEY, 'qa')).toEqual({ kind: 'question', page: 'p1', index: 1 });
		expect(destinationAtSelection('question', roots, SURVEY, 'p2')).toEqual({ kind: 'question', page: 'p2' });
		expect(destinationAtSelection('question', roots, SURVEY, 'b1')).toEqual({ kind: 'question', page: 'p2' });
		expect(destinationAtSelection('question', roots, SURVEY, null)).toEqual({ kind: 'question', page: 'phq2_page' });
		expect(destinationAtSelection('page', roots, SURVEY, 'qa')).toEqual({ kind: 'page', block: 'b1', index: 1 });
		expect(destinationAtSelection('page', roots, SURVEY, 'b1')).toEqual({ kind: 'page', block: 'b1' });
		expect(destinationAtSelection('page', roots, SURVEY, null)).toEqual({ kind: 'page', block: 'phq2_block' });
		expect(destinationAtSelection('block', roots, SURVEY, 'qc')).toEqual({ kind: 'block', index: 1, flow: { after: 'n1' } });
		expect(destinationAtSelection('block', roots, SURVEY, null)).toEqual({ kind: 'block', flow: { after: 'n2' } });
		expect(destinationAtSelection('question', [], {}, null)).toBeNull();
		expect(destinationAtSelection('page', [], {}, null)).toBeNull();
		expect(destinationAtSelection('block', [], {}, null)).toEqual({ kind: 'block', flow: {} });
	});

	it('maps a drop gap between questions to each kind', () => {
		const gap = { parent: 'p1', slot: 1 };
		expect(destinationFromGap('question', roots, SURVEY, gap)).toEqual({ kind: 'question', page: 'p1', index: 1 });
		expect(destinationFromGap('page', roots, SURVEY, gap)).toEqual({ kind: 'page', block: 'b1', index: 1 });
		expect(destinationFromGap('page', roots, SURVEY, { parent: 'p1', slot: 0 })).toEqual({ kind: 'page', block: 'b1', index: 0 });
		expect(destinationFromGap('block', roots, SURVEY, { parent: 'p1', slot: 0 })).toEqual({ kind: 'block', index: 0, flow: {} });
		expect(destinationFromGap('block', roots, SURVEY, gap)).toEqual({ kind: 'block', index: 1, flow: { after: 'n1' } });
		expect(destinationFromGap('block', roots, SURVEY, { parent: 'p2', slot: 0 })).toEqual({ kind: 'block', index: 1, flow: { after: 'n1' } });
		expect(destinationFromGap('question', roots, SURVEY, { parent: 'nope', slot: 0 })).toBeNull();
		expect(destinationFromGap('question', roots, SURVEY, { parent: null, slot: 0 })).toBeNull();
		expect(destinationFromGap('block', roots, SURVEY, { parent: null, slot: 2 })).toEqual({ kind: 'block', index: 2, flow: { after: 'n2' } });
	});

	it('describes where an item would go', () => {
		expect(describeDestination(roots, 'PHQ-9', { kind: 'question', page: 'p1', index: 1 })).toBe('Insert PHQ-9 between A and B on First');
		expect(describeDestination(roots, 'PHQ-9', { kind: 'question', page: 'p1', index: 0 })).toBe('Insert PHQ-9 at the start of First');
		expect(describeDestination(roots, 'PHQ-9', { kind: 'question', page: 'p1' })).toBe('Insert PHQ-9 at the end of First');
		expect(describeDestination(roots, 'X', { kind: 'page', block: 'b1', index: 1 })).toBe('Insert X as a page after First in Intro');
		expect(describeDestination(roots, 'X', { kind: 'page', block: 'b1', index: 0 })).toBe('Insert X as the first page of Intro');
		expect(describeDestination(roots, 'X', { kind: 'block', index: 1, flow: {} })).toBe('Insert X as a new block after Intro');
		expect(describeDestination(roots, 'X', { kind: 'block', index: 0, flow: {} })).toBe('Insert X as a new block before Intro');
		expect(describeDestination(roots, 'X', { kind: 'block', flow: {} })).toBe('Insert X as a new block at the end');
	});
});

describe('the insert op and its result', () => {
	const item = {
		summary: { id: 'phq2', source: 'bundled' as const },
		document: { fragment: { choiceLists: [], variables: [], block: { id: 'phq2_block', pages: [] } } },
		version: 1,
		checksum: 'sha256:' + 'a'.repeat(64)
	};
	it('builds flat params by kind and carries the checksum', () => {
		const op = insertOp(item.summary, item as never, { kind: 'block', index: 1, flow: { after: 'n1' } });
		expect(op).toEqual({
			op: 'insert_bank_item',
			params: {
				fragment: item.document.fragment,
				source: { bank: 'phq2', version: 1, library: 'bundled', checksum: item.checksum },
				index: 1,
				flow: { after: 'n1' }
			}
		});
		const q = insertOp(item.summary, { ...item, checksum: null } as never, { kind: 'question', page: 'p1' });
		expect(q.params).toEqual({ fragment: item.document.fragment, source: { bank: 'phq2', version: 1, library: 'bundled' }, page: 'p1' });
	});
	it('finds the added object in the patch', () => {
		const patch = [
			{ op: 'add', path: '/choiceLists/-', value: { id: 'cl' } },
			{ op: 'add', path: '/blocks/2', value: { id: 'phq2_block' } },
			{ op: 'add', path: '/flow/2', value: { id: 'n3' } }
		];
		expect(addedObjectId(patch, 'block')).toBe('phq2_block');
		expect(addedObjectId(patch, 'page')).toBeUndefined();
		expect(addedObjectId([{ op: 'add', path: '/blocks/0/pages/1/items/-', value: { id: 'q9' } }], 'question')).toBe('q9');
	});
});

describe('previews and words', () => {
	it('flattens a fragment into preview items', () => {
		const doc = {
			fragment: {
				choiceLists: [{ id: 'cl', choices: [{ value: 0, label: { en: 'Never' } }, { value: 1, label: 'Often' }] }],
				variables: [{ id: 'tot', kind: 'computed', expr: {} }],
				block: {
					id: 'b',
					pages: [
						{ id: 'p', items: [{ id: 'm', type: 'matrix', label: 'Grid', choiceList: 'cl', rows: [{ id: 'r1', label: 'Row one' }] }] },
						{ id: 'p2', items: [{ id: 's', type: 'single', label: { de: 'Eins', en: 'One' }, choices: [{ value: 1, label: 'Yes' }] }] }
					]
				}
			}
		};
		expect(fragmentItems(doc, 'en')).toEqual([
			{ id: 'm', type: 'matrix', label: 'Grid', rows: ['Row one'], choices: ['Never', 'Often'] },
			{ id: 's', type: 'single', label: 'One', choices: ['Yes'] }
		]);
		expect(fragmentVariables(doc)).toEqual(['tot']);
		expect(fragmentItems({ fragment: { question: { id: 'q', type: 'text', label: 'T' } } })).toEqual([{ id: 'q', type: 'text', label: 'T' }]);
		expect(fragmentItems(null)).toEqual([]);
		expect(labelDiff(doc, { fragment: { block: { pages: [{ items: [{ id: 'x', type: 'text', label: 'New' }] }] } } })).toEqual({
			added: ['New'],
			removed: ['Grid', 'Row one', 'Eins']
		});
	});

	it('words the provenance line and the notices', () => {
		expect(provenanceLabel({ bank: 'phq9', version: 1, library: 'bundled' }, 'PHQ-9')).toBe('PHQ-9 · bundled · v1');
		expect(provenanceLabel({ bank: 'abc', version: 3, library: 'lab' }, null)).toBe('abc · my lab · v3');
		expect(insertNotice({ licenceClass: 'public-domain', title: 'PHQ-9' }, {})).toBeNull();
		expect(
			insertNotice({ licenceClass: 'free-noncommercial', title: 'SWLS' }, { licence: { holder: 'Ed Diener' }, citation: { text: 'Diener 1985' } })
		).toBe('SWLS (Ed Diener): free for non-commercial research only. Cite: Diener 1985');
		expect(insertNotice({ licenceClass: 'licensed-to-lab', title: 'BDI-II' }, {})).toMatch(/licensed to this lab/);
	});

	it('shows a notice once per survey and class', () => {
		const mem = new Map<string, string>();
		const storage = { getItem: (k: string) => mem.get(k) ?? null, setItem: (k: string, v: string) => void mem.set(k, v) };
		expect(noticeShownOnce('s1', 'free-noncommercial', storage)).toBe(false);
		expect(noticeShownOnce('s1', 'free-noncommercial', storage)).toBe(true);
		expect(noticeShownOnce('s2', 'free-noncommercial', storage)).toBe(false);
		expect(noticeShownOnce('s1', 'licensed-to-lab', storage)).toBe(false);
		expect(noticeShownOnce('s1', 'x', undefined)).toBe(false);
	});

	it('parses tags and item lines, names export files', () => {
		expect(parseTags(' depression, screener; phq ,depression\nx')).toEqual(['depression', 'screener', 'phq', 'x']);
		expect(parseTags('a'.repeat(50))).toEqual(['a'.repeat(40)]);
		expect(itemLines(' one \r\n\n two\n')).toEqual(['one', 'two']);
		expect(exportFileName({ abbreviation: 'PHQ-9', title: 'x', id: 'i', version: 2 })).toBe('PHQ-9-v2.osp-bank.json');
		expect(exportFileName({ abbreviation: null, title: 'Our scale!', id: 'i', version: 1 })).toBe('Our-scale-v1.osp-bank.json');
		expect(exportFileName({ abbreviation: '***', title: '', id: 'i', version: 1 })).toBe('bank-item-v1.osp-bank.json');
	});
});
