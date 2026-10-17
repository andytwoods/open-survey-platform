import { describe, expect, it } from 'vitest';
import { negotiateLanguage, stringsFor } from '../src/lib/messages';
import { fragmentPointer } from '../src/lib/storage';

describe('language negotiation (R4-4)', () => {
	const cases: Array<[string[], string[], string, string]> = [
		[['de-DE', 'en-US'], ['en', 'de'], 'en', 'de'], // WebKit reports de-DE
		[['de'], ['en', 'de'], 'en', 'de'],
		[['fr-FR', 'de-AT'], ['en', 'de'], 'en', 'de'], // the second preference matches
		[['fr-FR'], ['en', 'de'], 'de', 'de'], // nothing matches: the plan default
		[['EN_gb'], ['en', 'de'], 'de', 'en'], // case and underscore
		[['pt-BR'], ['pt-PT', 'en'], 'en', 'pt-PT'], // same primary language
		[['pt-PT'], ['pt', 'pt-PT'], 'pt', 'pt-PT'], // exact beats primary
		[[], ['en', 'de'], 'de', 'de'],
		[['', ' '], ['en'], 'en', 'en']
	];
	for (const [prefs, available, fallback, want] of cases) {
		it(`${JSON.stringify(prefs)} with ${available.join('/')} → ${want}`, () => {
			expect(negotiateLanguage(prefs, available, fallback)).toBe(want);
		});
	}

	it('app strings by plan language: de has its own table, others fall back to English', () => {
		expect(stringsFor('de').next).toBe('Weiter');
		expect(stringsFor('de-CH').back).toBe('Zurück');
		expect(stringsFor('fr').next).toBe('Next');
		expect(Object.keys(stringsFor('de')).sort()).toEqual(Object.keys(stringsFor('en')).sort());
	});
});

describe('fragment pointer (sessionStorage blocked too)', () => {
	it('keeps the session in the URL fragment, next to other fragment keys', () => {
		const loc = { hash: '#x=1', pathname: '/s/demo', search: '?a=b' };
		const urls: string[] = [];
		const p = fragmentPointer(loc, (u) => {
			urls.push(u);
			loc.hash = u.includes('#') ? u.slice(u.indexOf('#')) : '';
		});
		expect(p.get('demo')).toBeNull();
		p.set('demo', { sessionId: 's1', resumeToken: 'tok.en-1' });
		expect(urls.at(-1)).toBe('/s/demo?a=b#x=1&osp-session=s1.tok.en-1');
		expect(p.get('demo')).toEqual({ sessionId: 's1', resumeToken: 'tok.en-1' });
		p.clear('demo');
		expect(loc.hash).toBe('#x=1');
	});
});
