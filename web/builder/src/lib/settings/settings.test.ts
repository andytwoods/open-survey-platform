import { describe, expect, it } from 'vitest';
import fixture from '../properties/fixtures/property-schemas.json';
import type { PropertySchemasDoc } from '../properties/types';
import { SAVE_MODES, localCopyOf, saveModeOf } from './explanations';
import {
	consentOp,
	consentWith,
	languagesOp,
	missingConsentLanguages,
	retentionOf,
	retentionValue,
	setText,
	subsetSchema,
	textExact
} from './model';

const KINDS = [
	{ kind: 'days-after-close', label: '', description: '', field: 'days' as const },
	{ kind: 'after-date', label: '', description: '', field: 'until' as const },
	{ kind: 'indefinite', label: '', description: '', field: null }
];

describe('save mode explanations', () => {
	it('spell out the trade-offs of each mode', () => {
		expect(SAVE_MODES['end-only'].tradeOffs.join(' ')).toMatch(/Drop-outs are invisible/);
		expect(SAVE_MODES['end-only'].tradeOffs.join(' ')).toMatch(/Refreshing/);
		expect(SAVE_MODES['every-page'].tradeOffs.join(' ')).toMatch(/Drop-outs are visible/);
	});
	it('read the mode with the model defaults', () => {
		expect(saveModeOf({})).toBe('every-page');
		expect(saveModeOf({ settings: { saveMode: 'end-only' } })).toBe('end-only');
		expect(localCopyOf({ settings: { localCopy: 'memory' } })).toBe('memory');
		expect(localCopyOf(null)).toBe('browser');
	});
});

describe('retention', () => {
	it('builds only complete values', () => {
		expect(retentionValue({ kind: 'indefinite', days: '', until: '' }, KINDS)).toEqual({ kind: 'indefinite' });
		expect(retentionValue({ kind: 'days-after-close', days: '', until: '' }, KINDS)).toBeNull();
		expect(retentionValue({ kind: 'days-after-close', days: ' 30 ', until: '' }, KINDS)).toEqual({
			kind: 'days-after-close',
			days: 30
		});
		expect(retentionValue({ kind: 'after-date', days: '', until: '2027-01-31' }, KINDS)).toEqual({
			kind: 'after-date',
			until: '2027-01-31'
		});
		expect(retentionValue({ kind: 'nope', days: '', until: '' }, KINDS)).toBeNull();
	});
	it('reads the survey value', () => {
		expect(retentionOf({})).toBeNull();
		expect(retentionOf({ settings: { retention: { kind: 'days-after-close', days: 7 } } })).toEqual({
			kind: 'days-after-close',
			days: '7',
			until: ''
		});
	});
});

describe('languages', () => {
	it('sends the default only when it is one of the languages', () => {
		expect(languagesOp(['en', 'de'], 'de')).toEqual({
			op: 'set_languages',
			params: { languages: ['en', 'de'], default_language: 'de' }
		});
		expect(languagesOp(['en'], 'de', true).params).toEqual({ languages: ['en'], cascade: true });
	});
});

describe('translatable text', () => {
	it('keeps a plain string for the default language and makes a map for others', () => {
		expect(setText('Hi', 'en', 'en', 'Hello')).toBe('Hello');
		expect(setText('Hi', 'de', 'en', 'Hallo')).toEqual({ en: 'Hi', de: 'Hallo' });
		expect(setText({ en: 'Hi', de: 'Hallo' }, 'de', 'en', '')).toEqual({ en: 'Hi' });
		expect(setText(undefined, 'en', 'en', '')).toBeUndefined();
	});
	it('reads exactly one language, no fallback', () => {
		expect(textExact('Hi', 'en', 'en')).toBe('Hi');
		expect(textExact('Hi', 'de', 'en')).toBe('');
		expect(textExact({ de: 'Hallo' }, 'de', 'en')).toBe('Hallo');
	});
});

describe('consent', () => {
	it('replaces the whole object through set_consent', () => {
		const c = consentWith({ text: 'Agree?' }, 'countDeclines', true);
		expect(consentOp(c)).toEqual({ op: 'set_consent', params: { consent: { text: 'Agree?', countDeclines: true } } });
		expect(consentWith(c, 'countDeclines', undefined)).toEqual({ text: 'Agree?' });
		expect(consentOp(null).params).toEqual({ consent: null });
	});
	it('lists languages with missing consent text', () => {
		const c = { text: { en: 'Agree?' }, agreeLabel: { en: 'Yes', de: 'Ja' } };
		expect(missingConsentLanguages(c, ['en', 'de'], 'en')).toEqual(['de']);
		expect(missingConsentLanguages(null, ['en', 'de'], 'en')).toEqual([]);
	});
});

describe('settings sections from the property schema', () => {
	it('narrow the survey schema to the settings fields, in one group', () => {
		const doc = fixture as unknown as PropertySchemasDoc;
		const survey = doc.schemas.find((s) => s.entity === 'survey')!;
		const sub = subsetSchema(survey, ['settings.saveMode', 'settings.localCopy', 'nope'], 'Saving', 'X');
		expect(Object.keys(sub.properties)).toEqual(['settings.saveMode', 'settings.localCopy']);
		expect(Object.values(sub.properties).every((p) => p.group === 'Saving')).toBe(true);
		expect(sub.properties['settings.saveMode']!.options!.map((o) => o.value)).toEqual(['every-page', 'end-only']);
	});
});
