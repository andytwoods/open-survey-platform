import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import fixture from './fixtures/property-schemas.json';
import {
	EDITOR_KINDS,
	diagnosticsFor,
	enumOptions,
	externalSummary,
	fallbackText,
	getAt,
	groupProperties,
	isMissingTranslation,
	opAddress,
	parseNumber,
	propertyPointer,
	setPropertyOp,
	textValue,
	withTranslation
} from './logic';
import type { PropertySchemasDoc, PropertySpec } from './types';

const doc = fixture as unknown as PropertySchemasDoc;
const schema = (type: string) => doc.schemas.find((s) => s.type === type)!;

describe('fixture (GET /api/meta/property-schemas)', () => {
	it('has a field editor for every kind (completeness guard)', () => {
		for (const kind of doc.kinds) expect(EDITOR_KINDS).toContain(kind);
		for (const s of doc.schemas)
			for (const spec of Object.values(s.properties)) expect(EDITOR_KINDS).toContain(spec.kind);
	});

	it('matches the osp-spec YAML files (regenerate with fixtures/regenerate.py)', () => {
		const dir = fileURLToPath(new URL('../../../../../python/osp-spec/src/osp_spec/properties/', import.meta.url));
		const files = readdirSync(dir).filter((f) => f.endsWith('.yaml'));
		expect(doc.schemas.map((s) => s.type).sort()).toEqual(files.map((f) => f.replace('.yaml', '')).sort());
		for (const f of files) {
			const yaml = readFileSync(dir + f, 'utf8');
			const body = yaml.split(/^properties:\s*$/m)[1].split(/^\S/m)[0];
			const keys = [...body.matchAll(/^ {2}([A-Za-z_.]+):\s*$/gm)].map((m) => m[1]);
			expect(Object.keys(schema(f.replace('.yaml', '')).properties)).toEqual(keys);
		}
	});
});

describe('grouping', () => {
	it('orders groups as the schema document lists them, skipping empty ones', () => {
		const groups = groupProperties(schema('single'), doc.groups);
		expect(groups.map((g) => g.name)).toEqual(['Basics', 'Choices', 'Logic', 'Validation', 'Advanced']);
		expect(groups[0].entries.map((e) => e.key)).toEqual(['label', 'help']);
		expect(groupProperties(schema('note'), doc.groups).map((g) => g.name)).toEqual(['Basics', 'Logic']);
	});

	it('puts unknown groups last and tolerates junk', () => {
		const s = {
			type: 'x',
			entity: 'question' as const,
			label: {},
			properties: {
				a: { kind: 'text', label: {}, group: 'Zeta' },
				b: { kind: 'text', label: {}, group: 'Basics' },
				c: null as unknown as PropertySpec
			}
		} as const;
		expect(groupProperties(s as never, ['Basics']).map((g) => g.name)).toEqual(['Basics', 'Zeta']);
	});
});

describe('addressing set_property', () => {
	it('uses the id for questions, pages and blocks', () => {
		expect(opAddress('question', { id: 'q1' }, 'label')).toEqual({ target: 'q1', property: 'label' });
		expect(opAddress('block', { id: 'b1' }, 'title')).toEqual({ target: 'b1', property: 'title' });
		expect(opAddress('page', {}, 'title')).toBeNull();
		expect(opAddress('page', null, 'title')).toBeNull();
	});

	it('maps survey keys onto the /metadata and /settings pseudo-targets', () => {
		expect(opAddress('survey', {}, 'metadata.title')).toEqual({ target: '/metadata', property: 'title' });
		expect(opAddress('survey', {}, 'settings.backNavigation')).toEqual({
			target: '/settings',
			property: 'backNavigation'
		});
		expect(opAddress('survey', {}, 'flow')).toBeNull();
	});

	it('builds set and unset ops', () => {
		const a = { target: 'q1', property: 'required' };
		expect(setPropertyOp(a, true)).toEqual({ op: 'set_property', params: { target: 'q1', property: 'required', value: true } });
		expect(setPropertyOp(a, undefined)).toEqual({ op: 'set_property', params: { target: 'q1', property: 'required', unset: true } });
	});
});

describe('values and diagnostics', () => {
	it('reads dotted keys (own keys only)', () => {
		expect(getAt({ metadata: { title: 'T' } }, 'metadata.title')).toBe('T');
		expect(getAt({ metadata: null }, 'metadata.title')).toBeUndefined();
		expect(getAt({}, 'constructor')).toBeUndefined();
	});

	it('matches diagnostics at or below a property pointer', () => {
		const d = (pointer: string) => ({ severity: 'error', code: 'c', message: 'm', pointer });
		const all = [d('/blocks/0/pages/1/items/2/label'), d('/blocks/0/pages/1/items/2/label/de'), d('/blocks/0/pages/1/items/2/labelX'), d('/metadata/title')];
		expect(diagnosticsFor(all, '/blocks/0/pages/1/items/2', 'label')).toHaveLength(2);
		expect(diagnosticsFor(all, '', 'metadata.title')).toHaveLength(1);
		expect(propertyPointer('', 'a/b.c~d')).toBe('/a~1b/c~0d');
		expect(diagnosticsFor(undefined, '', 'x')).toEqual([]);
		expect(diagnosticsFor([null as never, { pointer: 3 } as never], '', 'x')).toEqual([]);
	});
});

describe('translatable text', () => {
	it('sets one language of a map and unsets an emptied map', () => {
		expect(withTranslation({ en: 'Hi', de: 'Hallo' }, 'de', 'en', 'Servus')).toEqual({ en: 'Hi', de: 'Servus' });
		expect(withTranslation({ en: 'Hi', de: 'Hallo' }, 'de', 'en', '')).toEqual({ en: 'Hi' });
		expect(withTranslation({ en: 'Hi' }, 'en', 'en', '')).toBeUndefined();
	});

	it('keeps a plain string plain in the default language and adds a map for others', () => {
		expect(withTranslation('Hi', 'en', 'en', 'Hello')).toBe('Hello');
		expect(withTranslation('Hi', 'de', 'en', 'Hallo')).toEqual({ en: 'Hi', de: 'Hallo' });
		expect(withTranslation('Hi', 'de', 'en', '')).toBe('Hi');
		expect(withTranslation(undefined, 'en', 'en', 'New')).toEqual({ en: 'New' });
		expect(withTranslation(undefined, 'en', 'en', '')).toBeUndefined();
	});

	it('flags a missing translation only when another language has text', () => {
		expect(isMissingTranslation({ en: 'Hi' }, 'de')).toBe(true);
		expect(isMissingTranslation({ en: 'Hi', de: '' }, 'de')).toBe(true);
		expect(isMissingTranslation({ en: 'Hi' }, 'en')).toBe(false);
		expect(isMissingTranslation('Hi', 'de')).toBe(false);
		expect(isMissingTranslation(undefined, 'de')).toBe(false);
		expect(fallbackText({ fr: 'Salut', en: 'Hi' }, 'en')).toBe('Hi');
	});

	it('commits plain text for non-translatable fields', () => {
		const spec = { kind: 'text', label: {}, group: 'Advanced' } as PropertySpec;
		expect(textValue(spec, 'old', 'en', 'en', 'age')).toBe('age');
		expect(textValue(spec, 'old', 'en', 'en', '')).toBeUndefined();
	});
});

describe('numbers, enums, external editors', () => {
	it('parses numbers', () => {
		expect(parseNumber(' 4.5 ')).toBe(4.5);
		expect(parseNumber('')).toBeUndefined();
		expect(parseNumber('abc')).toBeNull();
		expect(parseNumber('Infinity')).toBeNull();
	});

	it('lists schema options and optionsFrom values', () => {
		const order = schema('single').properties.choiceOrder;
		expect(enumOptions(order, {}, 'en')).toEqual([
			{ value: 'fixed', label: 'As listed' },
			{ value: 'shuffle', label: 'Shuffle per participant' }
		]);
		const lang = schema('survey').properties['metadata.defaultLanguage'];
		expect(enumOptions(lang, { metadata: { languages: ['en', 'de', 'en', 7] } }, 'en').map((o) => o.value)).toEqual(['en', 'de']);
		expect(enumOptions(lang, {}, 'en')).toEqual([]);
	});

	it('summarises choicelists and conditions without throwing', () => {
		expect(externalSummary('choicelist', [{ value: 1, label: 'A' }, { value: 2, label: 'B' }])).toBe('2 choices');
		expect(externalSummary('choicelist', undefined)).toBe('No choices');
		expect(externalSummary('condition', undefined)).toBe('No condition');
		expect(typeof externalSummary('condition', { kind: 'nonsense' })).toBe('string');
	});
});
