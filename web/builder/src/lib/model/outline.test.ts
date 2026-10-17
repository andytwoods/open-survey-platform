import { describe, expect, it } from 'vitest';
import { applyPatch } from '../sync/json-patch';
import { SelectionStore } from '../selection.svelte';
import {
	addedQuestionId,
	allIds,
	findObject,
	outlineFromSurvey,
	pointerOf,
	pointerWithin,
	surveyTitle,
	targetPage,
	textIn,
	withText
} from './outline';

const doc = {
	specVersion: '0.1',
	id: 'survey',
	metadata: { title: { en: 'Sleep', de: 'Schlaf' }, languages: ['en', 'de'], defaultLanguage: 'en' },
	blocks: [
		{
			id: 'b1',
			title: 'Intro',
			pages: [
				{ id: 'p1', title: { en: 'Welcome' }, items: [{ id: 'intro', type: 'note', label: { en: '' } }] },
				{ id: 'p2', items: [{ id: 'q1', type: 'single', label: { de: 'Nur Deutsch' } }] }
			]
		},
		{
			id: 'b2',
			pages: [
				{
					id: 'p3',
					items: [
						{ id: 'q2', type: 'integer', label: 'Hours' },
						{ id: 'q3', type: 'matrix', label: 'Grid', rows: [{ id: 'r1', label: 'R1' }] },
						{ id: 'q4', type: 'slider', label: 'Pain' }
					]
				}
			]
		}
	]
};

describe('outlineFromSurvey', () => {
	it('projects blocks → pages → questions with display labels', () => {
		const tree = outlineFromSurvey(doc);
		expect(tree.map((b) => [b.id, b.label])).toEqual([
			['b1', 'Intro'],
			['b2', 'b2']
		]);
		const [p1, p2] = tree[0].children!;
		expect(p1).toMatchObject({ id: 'p1', type: 'page', label: 'Welcome' });
		expect(p2.label).toBe('p2');
		expect(p1.children![0]).toMatchObject({ id: 'intro', label: '(intro)', family: 'note' });
		expect(p2.children![0]).toMatchObject({ label: 'Nur Deutsch', family: 'choice', questionType: 'single' });
		expect(tree[1].children![0].children![0]).toMatchObject({ label: 'Hours', family: 'number' });
		expect(tree[1].children![0].children![1]).toMatchObject({ label: 'Grid', family: 'matrix' });
		expect(tree[1].children![0].children![2]).toMatchObject({ label: 'Pain', family: 'scale' });
		expect(surveyTitle(doc)).toBe('Sleep');
	});

	it.each([null, 42, 'x', [], { blocks: 'no' }, { blocks: [null, { id: 3 }, { id: 'b', pages: [{}] }] }])(
		'never throws on malformed input %j',
		(bad) => {
			expect(() => outlineFromSurvey(bad)).not.toThrow();
		}
	);
});

describe('text helpers', () => {
	it('reads and writes one language, keeping the others', () => {
		expect(textIn({ en: 'a', de: 'b' }, 'de')).toBe('b');
		expect(textIn({ de: 'b' }, 'en')).toBe('b');
		expect(textIn('plain', 'en')).toBe('plain');
		expect(textIn(undefined, 'en')).toBe('');
		expect(withText({ en: 'a', de: 'b' }, 'en', 'z')).toEqual({ en: 'z', de: 'b' });
		expect(withText('plain', 'en', 'z')).toBe('z');
		expect(withText(undefined, 'en', 'z')).toEqual({ en: 'z' });
	});
});

describe('targets and lookups', () => {
	const tree = outlineFromSurvey(doc);
	it('picks the page to add a question to', () => {
		expect(targetPage(tree, 'p2')).toBe('p2');
		expect(targetPage(tree, 'q1')).toBe('p2');
		expect(targetPage(tree, 'b1')).toBe('p2');
		expect(targetPage(tree, null)).toBe('p3');
		expect(targetPage([], null)).toBeUndefined();
	});
	it('finds raw objects and every id', () => {
		expect(findObject(doc, 'q2')).toMatchObject({ type: 'integer' });
		expect(findObject(doc, 'p3')).toMatchObject({ id: 'p3' });
		expect(findObject(doc, 'nope')).toBeUndefined();
		expect(allIds(tree).has('q2')).toBe(true);
	});
	it('finds the question an add_question patch added', () => {
		expect(
			addedQuestionId([{ op: 'add', path: '/blocks/0/pages/0/items/1', value: { id: 'q9', type: 'text' } }])
		).toBe('q9');
		expect(addedQuestionId([{ op: 'replace', path: '/blocks/0/pages/0/items/1/label', value: 'x' }])).toBeUndefined();
	});
});

describe('pointers', () => {
	it('locates objects and matches diagnostics inside them', () => {
		expect(pointerOf(doc, 'b2')).toBe('/blocks/1');
		expect(pointerOf(doc, 'p2')).toBe('/blocks/0/pages/1');
		expect(pointerOf(doc, 'q2')).toBe('/blocks/1/pages/0/items/0');
		expect(pointerOf(doc, 'nope')).toBeUndefined();
		expect(pointerOf(null, 'x')).toBeUndefined();
		expect(pointerWithin('/blocks/0/pages/1/items/0/label', '/blocks/0/pages/1')).toBe(true);
		expect(pointerWithin('/blocks/0/pages/10', '/blocks/0/pages/1')).toBe(false);
	});
});

describe('selection survives patches', () => {
	it('keeps the selected id when a patch changes the tree around it', () => {
		const selection = new SelectionStore();
		selection.select('q1');
		const next = applyPatch(doc, [
			{ op: 'add', path: '/blocks/0/pages/1/items/0', value: { id: 'q0', type: 'text', label: 'New' } },
			{ op: 'replace', path: '/blocks/0/pages/1/items/1/label', value: { en: 'Renamed' } }
		]);
		const tree = outlineFromSurvey(next);
		expect(allIds(tree).has(selection.id!)).toBe(true);
		expect(selection.id).toBe('q1');
		expect(tree[0].children![1].children!.map((q) => q.label)).toEqual(['New', 'Renamed']);
	});
});
