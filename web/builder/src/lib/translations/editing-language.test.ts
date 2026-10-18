import { describe, expect, it } from 'vitest';
import {
	langFromSearch,
	languageOptions,
	rememberedLanguage,
	rememberedReferenceOpen,
	rememberLanguage,
	rememberReferenceOpen,
	resolveEditingLanguage,
	withLang
} from './editing-language';

function memory(): Storage {
	const m = new Map<string, string>();
	return {
		getItem: (k) => m.get(k) ?? null,
		setItem: (k, v) => void m.set(k, v),
		removeItem: (k) => void m.delete(k),
		clear: () => m.clear(),
		key: (i) => [...m.keys()][i] ?? null,
		get length() {
			return m.size;
		}
	};
}

describe('the URL form', () => {
	it('reads a well-formed tag and ignores junk', () => {
		expect(langFromSearch('?lang=de')).toBe('de');
		expect(langFromSearch('?x=1&lang=pt-BR')).toBe('pt-BR');
		expect(langFromSearch('')).toBeNull();
		expect(langFromSearch('?lang=')).toBeNull();
		expect(langFromSearch('?lang=<script>')).toBeNull();
		expect(langFromSearch('?lang=' + 'a'.repeat(40))).toBeNull();
	});

	it('sets, replaces and removes ?lang= without touching the rest', () => {
		expect(withLang('https://h/surveys/1?x=1#select=q1', 'de')).toBe('https://h/surveys/1?x=1&lang=de#select=q1');
		expect(withLang('https://h/surveys/1?lang=de', 'fr')).toBe('https://h/surveys/1?lang=fr');
		expect(withLang('https://h/surveys/1?lang=de&x=1', null)).toBe('https://h/surveys/1?x=1');
		expect(withLang('https://h/surveys/1', null)).toBe('https://h/surveys/1');
	});
});

describe('resolution', () => {
	it('edits the requested language only when the survey has it', () => {
		expect(resolveEditingLanguage('de', ['en', 'de'], 'en')).toBe('de');
		expect(resolveEditingLanguage('fr', ['en', 'de'], 'en')).toBe('en');
		expect(resolveEditingLanguage(null, ['en', 'de'], 'en')).toBe('en');
		expect(resolveEditingLanguage('de', [], 'en')).toBe('en');
	});

	it('lists the default first, marked', () => {
		expect(languageOptions(['de', 'en', 'fr'], 'en')).toEqual([
			{ value: 'en', label: 'en (default)' },
			{ value: 'de', label: 'de' },
			{ value: 'fr', label: 'fr' }
		]);
		expect(languageOptions(['de'], 'en')).toEqual([{ value: 'de', label: 'de' }]);
	});
});

describe('memory', () => {
	it('remembers a language per survey and forgets it on null', () => {
		const s = memory();
		rememberLanguage(s, 's1', 'de');
		expect(rememberedLanguage(s, 's1')).toBe('de');
		expect(rememberedLanguage(s, 's2')).toBeNull();
		rememberLanguage(s, 's1', null);
		expect(rememberedLanguage(s, 's1')).toBeNull();
		s.setItem('osp.editing-language.s3', 'not a tag!');
		expect(rememberedLanguage(s, 's3')).toBeNull();
	});

	it('survives a missing or throwing storage', () => {
		expect(rememberedLanguage(null, 's1')).toBeNull();
		expect(() => rememberLanguage(null, 's1', 'de')).not.toThrow();
		const broken = {
			getItem: () => {
				throw new Error('denied');
			},
			setItem: () => {
				throw new Error('full');
			}
		} as unknown as Storage;
		expect(rememberedLanguage(broken, 's1')).toBeNull();
		expect(() => rememberLanguage(broken, 's1', 'de')).not.toThrow();
		expect(rememberedReferenceOpen(broken)).toBe(true);
		expect(() => rememberReferenceOpen(broken, false)).not.toThrow();
	});

	it('remembers the reference strip collapsed, open by default', () => {
		const s = memory();
		expect(rememberedReferenceOpen(s)).toBe(true);
		rememberReferenceOpen(s, false);
		expect(rememberedReferenceOpen(s)).toBe(false);
		rememberReferenceOpen(s, true);
		expect(rememberedReferenceOpen(s)).toBe(true);
		expect(s.length).toBe(0);
	});
});
