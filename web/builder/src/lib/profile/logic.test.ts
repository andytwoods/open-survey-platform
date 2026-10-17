import { describe, expect, it } from 'vitest';
import fixture from '../properties/fixtures/property-schemas.json';
import type { PropertySchemasDoc } from '../properties/types';
import {
	emptyRow,
	localProblems,
	moveKey,
	optionsToText,
	parseCustomDefault,
	parseDefault,
	parseOptions,
	sameProfile,
	stockSchemas,
	toDraft,
	toProfile,
	type ProfileDocument
} from './logic';

const doc = fixture as unknown as PropertySchemasDoc;
const stock = stockSchemas(doc);

const PROFILE: ProfileDocument = {
	profileVersion: 'osp-panel-profile/0.1',
	hidden: ['*.constraintMessage', 'single.choiceOrder', 'single.label', 'nope.label'],
	order: { '*': ['required', 'label'], text: ['multiline', 'label'] },
	groups: { Logic: { en: 'Conditions' } },
	defaults: { single: { required: true }, text: { multiline: true } },
	custom: [
		{ key: 'construct', kind: 'text', label: { en: 'Construct' }, group: 'Basics', required: true },
		{ key: 'weight', kind: 'number', label: { en: 'Weight' }, default: 1, types: ['single', 'multi'] },
		{
			key: 'scale',
			kind: 'choice',
			label: { en: 'Scale' },
			options: [
				{ value: 'likert', label: { en: 'Likert' } },
				{ value: 'vas', label: { en: 'vas' } }
			]
		}
	]
};

describe('toDraft', () => {
	it('expands star refs to every type that has the key, skips required and unknown ones', () => {
		const d = toDraft(PROFILE, stock, 'en');
		expect(d.hidden.has('single.constraintMessage')).toBe(true);
		expect(d.hidden.has('integer.constraintMessage')).toBe(true);
		expect(d.hidden.has('note.constraintMessage')).toBe(false); // notes have none
		expect(d.hidden.has('single.choiceOrder')).toBe(true);
		expect(d.hidden.has('single.label')).toBe(false); // required stays visible
		expect([...d.hidden].some((r) => r.startsWith('nope.'))).toBe(false);
	});

	it('gives every type a full order: listed keys first, then the stock order', () => {
		const d = toDraft(PROFILE, stock, 'en');
		expect(d.order.single.slice(0, 2)).toEqual(['required', 'label']);
		expect(d.order.single).toHaveLength(Object.keys(stock.single.properties).length);
		expect(d.order.text.slice(0, 2)).toEqual(['multiline', 'label']);
		expect(d.order.page).toEqual(Object.keys(stock.page.properties)); // "*" keys it lacks are skipped
	});

	it('reads groups, defaults and custom rows in the editing language', () => {
		const d = toDraft(PROFILE, stock, 'en');
		expect(d.groups).toEqual({ Logic: 'Conditions' });
		expect(d.defaults).toEqual({ single: { required: 'true' }, text: { multiline: 'true' } });
		expect(d.custom.map((c) => c.key)).toEqual(['construct', 'weight', 'scale']);
		expect(d.custom[1]).toMatchObject({ kind: 'number', defaultText: '1', types: ['single', 'multi'], group: 'Advanced' });
		expect(d.custom[2].options).toEqual([
			{ value: 'likert', label: 'Likert' },
			{ value: 'vas', label: 'vas' }
		]);
		expect(d.custom[0].required).toBe(true);
	});

	it('an empty or null profile is the stock panel', () => {
		const d = toDraft(null, stock, 'en');
		expect(d.hidden.size).toBe(0);
		expect(d.custom).toEqual([]);
		expect(toProfile(d, stock, 'en')).toEqual({ profileVersion: 'osp-panel-profile/0.1' });
		expect(sameProfile(toProfile(d, stock, 'en'), null)).toBe(true);
	});
});

describe('toProfile', () => {
	it('round-trips a profile, compacting star refs and dropping stock orders', () => {
		const out = toProfile(toDraft(PROFILE, stock, 'en'), stock, 'en');
		expect(out.hidden).toEqual(['*.constraintMessage', 'single.choiceOrder']);
		expect(Object.keys(out.order ?? {}).sort()).toEqual(
			Object.keys(stock)
				.filter((t) => stock[t].properties.required || stock[t].properties.multiline)
				.sort()
		);
		expect(out.order?.text.slice(0, 2)).toEqual(['multiline', 'label']);
		expect(out.groups).toEqual({ Logic: { en: 'Conditions' } });
		expect(out.defaults).toEqual({ single: { required: true }, text: { multiline: true } });
		expect(out.custom?.[0]).toEqual({ key: 'construct', kind: 'text', label: { en: 'Construct' }, group: 'Basics', required: true });
		expect(out.custom?.[1]).toEqual({ key: 'weight', kind: 'number', label: { en: 'Weight' }, group: 'Advanced', default: 1, types: ['single', 'multi'] });
		expect(out.custom?.[2]).toMatchObject({ kind: 'choice', options: [{ value: 'likert', label: { en: 'Likert' } }, { value: 'vas', label: { en: 'vas' } }] });
		// Saving what came back changes nothing.
		expect(sameProfile(toProfile(toDraft(out, stock, 'en'), stock, 'en'), out)).toBe(true);
	});

	it('parses typed defaults by kind and drops ones that mean nothing', () => {
		const single = stock.single.properties;
		expect(parseDefault(single.required, 'true')).toBe(true);
		expect(parseDefault(single.required, 'yes')).toBeUndefined();
		expect(parseDefault(single.choiceOrder, 'shuffle')).toBe('shuffle');
		expect(parseDefault(single.label, 'Hi')).toBe('Hi');
		expect(parseDefault(stock.integer.properties.min, '7')).toBe(7);
		expect(parseDefault(stock.integer.properties.min, 'x')).toBeUndefined();
		expect(parseDefault(undefined, 'x')).toBeUndefined();
		const d = toDraft(null, stock, 'en');
		d.defaults = { single: { required: 'yes', choiceOrder: 'shuffle' }, page: { title: 'x' } };
		expect(toProfile(d, stock, 'en').defaults).toEqual({ single: { choiceOrder: 'shuffle' } });
	});

	it('parses custom defaults and options', () => {
		const row = { ...emptyRow(), kind: 'number' as const, defaultText: '2.5' };
		expect(parseCustomDefault(row)).toBe(2.5);
		expect(parseCustomDefault({ ...row, defaultText: 'x' })).toBeUndefined();
		expect(parseCustomDefault({ ...row, kind: 'bool', defaultText: 'false' })).toBe(false);
		const choice = { ...row, kind: 'choice' as const, options: parseOptions('a = Alpha\nb\n\n a = dup'), defaultText: 'b' };
		expect(choice.options).toEqual([
			{ value: 'a', label: 'Alpha' },
			{ value: 'b', label: 'b' }
		]);
		expect(parseCustomDefault(choice)).toBe('b');
		expect(parseCustomDefault({ ...choice, defaultText: 'c' })).toBeUndefined();
		expect(optionsToText(choice.options)).toBe('a = Alpha\nb');
	});
});

describe('localProblems and moveKey', () => {
	it('reports bad keys, duplicates, empty choices and unfit defaults', () => {
		const d = toDraft(null, stock, 'en');
		d.custom = [
			{ ...emptyRow(), key: 'Bad' },
			{ ...emptyRow(), key: 'k', kind: 'choice' },
			{ ...emptyRow(), key: 'k', kind: 'number', defaultText: 'x' }
		];
		const p = localProblems(d);
		expect(p).toHaveLength(4);
		expect(p[0]).toMatch(/Custom property 1: the key/);
		expect(p[1]).toMatch(/needs at least one option/);
		expect(p[2]).toMatch(/used twice/);
		expect(p[3]).toMatch(/does not fit a number/);
		expect(localProblems(toDraft(PROFILE, stock, 'en'))).toEqual([]);
	});

	it('moves a key one step and stays put at the ends', () => {
		expect(moveKey(['a', 'b', 'c'], 'b', -1)).toEqual(['b', 'a', 'c']);
		expect(moveKey(['a', 'b', 'c'], 'b', 1)).toEqual(['a', 'c', 'b']);
		expect(moveKey(['a', 'b', 'c'], 'a', -1)).toEqual(['a', 'b', 'c']);
		expect(moveKey(['a', 'b', 'c'], 'zz', 1)).toEqual(['a', 'b', 'c']);
	});
});
