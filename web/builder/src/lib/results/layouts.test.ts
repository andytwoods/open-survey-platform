import { describe, expect, it } from 'vitest';
import fixture from './fixtures/results.json';
import {
	chartNotices,
	emptyState,
	fromDay,
	fromSettings,
	inOrder,
	layoutError,
	moved,
	sameLayout,
	toDay,
	toSettings,
	type PageState
} from './layouts';
import { cardRequests, toQuery } from './model';
import type { Card, LayoutSettings, ResultsResponse } from './types';

// Saved layouts (task V5b): page state <-> LayoutSettings (V5a's closed schema), the
// display order, unsuitable chart ids and error messages. The fixture is the real API's
// answer for V1's hand-checked survey.

const plain = fixture.plain as unknown as ResultsResponse;
const questions = plain.cards.map((c) => c.question);
const LATEST = 3;

function full(): PageState {
	const s = emptyState(LATEST);
	s.filters = {
		versions: [1, 2],
		status: 'all',
		from: '2026-01-05',
		to: '2026-02-28',
		condition: { variable: 'arm', levels: ['b'] },
		answers: [{ question: 'fruit', codes: ['1', '3'] }],
		split: { kind: 'question', id: 'sat', excludeMissing: true },
		denominator: 'shown',
		intervals: true,
		language: 'de'
	};
	s.cards = {
		chosen: { fruit: 'donut', age: 'box' },
		layouts: { fruit: 'multiples' },
		bins: { when: { unit: 'week' }, age: { width: 5 } },
		hidden: { why: true }
	};
	s.captions = { fruit: 'Figure 1. Fruit.' };
	s.order = ['grid', 'fruit'];
	s.showNotes = true;
	s.theme = { kind: 'library', id: 'th1' };
	s.exports = { widthMm: 180, dpi: 600, k: 5, bundle: 'png' };
	s.live = true;
	return s;
}

describe('page state <-> layout settings', () => {
	it('round-trips every part the layout holds', () => {
		const s = full();
		const settings = toSettings(s, LATEST, questions);
		const back = fromSettings(settings, LATEST);
		expect(back.filters).toEqual(s.filters);
		expect(back.cards).toEqual(s.cards);
		expect(back.captions).toEqual(s.captions);
		expect(back.showNotes).toBe(true);
		expect(back.theme).toEqual(s.theme);
		expect(back.exports).toEqual(s.exports);
		expect(back.live).toBe(true);
		// The order comes back as the full display order the layout listed.
		expect(back.order).toEqual(inOrder(plain.cards, s.order).map((c) => c.question));
		expect(back.order.slice(0, 3)).toEqual(['grid', 'fruit', 'sat']);
		expect(sameLayout(back, s, LATEST, questions)).toBe(true);
		expect(toSettings(back, LATEST, questions)).toEqual(settings);
	});

	it('writes the schema V5a accepts: query, cards in display order, nothing else', () => {
		const settings = toSettings(full(), LATEST, questions);
		expect(Object.keys(settings).sort()).toEqual(['cards', 'export', 'live', 'query', 'schemaVersion', 'showNotes', 'theme']);
		expect(settings.live).toBe(true);
		expect(settings.schemaVersion).toBe('osp-results-layout/0.1');
		expect(settings.theme).toEqual({ kind: 'library', id: 'th1' });
		expect(settings.export).toEqual({ widthMm: 180, dpi: 600, hideCountsBelow: 5, bundle: 'png' });
		expect(settings.query).toEqual({
			versions: [1, 2],
			status: 'all',
			submittedFrom: '2026-01-05T00:00:00Z',
			submittedTo: '2026-03-01T00:00:00Z',
			filters: [{ question: 'fruit', in: ['1', '3'] }],
			condition: { variable: 'arm', in: ['b'] },
			split: { question: 'sat', condition: null, excludeMissing: true },
			denominator: 'shown',
			intervals: true,
			language: 'de'
		});
		expect(settings.cards!.map((c) => c.question)).toEqual(['grid', 'fruit', ...questions.filter((q) => q !== 'grid' && q !== 'fruit')]);
		expect(settings.cards!.find((c) => c.question === 'fruit')).toEqual({
			question: 'fruit',
			chart: 'donut',
			splitLayout: 'multiples',
			hidden: false,
			bins: null,
			caption: 'Figure 1. Fruit.'
		});
		expect(settings.cards!.find((c) => c.question === 'why')!.hidden).toBe(true);
		expect(settings.cards!.find((c) => c.question === 'when')!.bins).toEqual({ unit: 'week' });
		expect(settings.cards!.find((c) => c.question === 'sl')).toEqual({
			question: 'sl',
			chart: null,
			splitLayout: null,
			hidden: false,
			bins: null,
			caption: null
		});
		// Settings only: no counts, labels or response ids anywhere.
		expect(JSON.stringify(settings)).not.toMatch(/"(count|n|pct|groups|label|responses)":/);
	});

	it('reads the normalised form the server returns (nulls, numbers as codes)', () => {
		const stored = {
			schemaVersion: 'osp-results-layout/0.1',
			query: {
				versions: null,
				status: 'complete',
				submittedFrom: null,
				submittedTo: '2026-02-01T00:00:00Z',
				filters: [{ question: 'fruit', in: [1, 2] }],
				condition: null,
				split: { question: null, condition: 'arm', excludeMissing: false },
				denominator: 'answered',
				intervals: false,
				language: null
			},
			cards: [
				{ question: 'when', chart: null, splitLayout: null, hidden: false, bins: { width: null, count: null, unit: 'month' }, caption: null },
				{ question: 'big', chart: 'histogram', splitLayout: null, hidden: false, bins: { width: null, count: 12, unit: null }, caption: '' }
			],
			showNotes: false
		} as LayoutSettings;
		const s = fromSettings(stored, LATEST);
		expect(s.filters.versions).toEqual([LATEST]);
		expect(s.filters.to).toBe('2026-01-31');
		expect(s.filters.answers).toEqual([{ question: 'fruit', codes: ['1', '2'] }]);
		expect(s.filters.split).toEqual({ kind: 'condition', id: 'arm' });
		expect(s.cards.bins).toEqual({ big: { count: 12 } }); // per month is the default
		expect(s.captions).toEqual({ big: '' });
		expect(s.order).toEqual(['when', 'big']);
		// The query it opens with: the server's own form of these filters.
		expect(toQuery(s.filters)).toEqual({
			status: 'complete',
			denominator: 'answered',
			intervals: false,
			versions: [LATEST],
			submittedTo: '2026-02-01T00:00:00Z',
			filters: [{ question: 'fruit', in: ['1', '2'] }],
			split: { condition: 'arm', excludeMissing: false }
		});
		expect(cardRequests(plain.cards, s.cards.bins)!.find((c) => c.question === 'big')).toEqual({ question: 'big', bins: { count: 12 } });
	});

	it('a layout on the latest version follows the latest; no settings give the defaults', () => {
		const s = emptyState(LATEST);
		expect(toSettings(s, LATEST, questions).query!.versions).toBeNull();
		s.filters.versions = [];
		expect(toSettings(s, LATEST).query!.versions).toBeNull();
		s.filters.versions = [2];
		expect(toSettings(s, LATEST).query!.versions).toEqual([2]);
		expect(fromSettings(null, LATEST)).toEqual(emptyState(LATEST));
		expect(fromSettings({ schemaVersion: 'osp-results-layout/0.1', showNotes: false, live: false }, LATEST)).toEqual(emptyState(LATEST));
	});

	it('live (LV3) is a layout setting: off for layouts saved before it, a change is unsaved', () => {
		const pre = { schemaVersion: 'osp-results-layout/0.1', showNotes: false } as LayoutSettings; // saved before LV3
		expect(fromSettings(pre, LATEST).live).toBe(false);
		expect(fromSettings({ ...pre, live: true }, LATEST).live).toBe(true);
		expect(fromSettings({ ...pre, live: 'yes' as unknown as boolean }, LATEST).live).toBe(false);
		const base = emptyState(LATEST);
		expect(toSettings(base, LATEST).live).toBe(false);
		const lab = structuredClone(base);
		lab.live = true;
		expect(toSettings(lab, LATEST).live).toBe(true);
		expect(sameLayout(lab, base, LATEST, questions)).toBe(false);
	});

	it('the defaults and an unchanged layout are not "unsaved"; a change is', () => {
		const base = emptyState(LATEST);
		const now = structuredClone(base);
		expect(sameLayout(now, base, LATEST, questions)).toBe(true);
		now.cards.bins.when = { unit: 'month' }; // back to the default period
		expect(sameLayout(now, base, LATEST, questions)).toBe(true);
		now.order = [...questions]; // moved and moved back
		expect(sameLayout(now, base, LATEST, questions)).toBe(true);
		now.cards.hidden.fruit = true;
		expect(sameLayout(now, base, LATEST, questions)).toBe(false);
		const moved1 = structuredClone(base);
		moved1.order = moved(questions, 'grid', 0);
		expect(sameLayout(moved1, base, LATEST, questions)).toBe(false);
		const cap = structuredClone(base);
		cap.captions.age = 'x'.repeat(3000);
		expect(toSettings(cap, LATEST).cards![0].caption).toHaveLength(2000);
	});

	it('theme and export parts (V6): references only, defaults for anything missing or wrong', () => {
		const pre = { schemaVersion: 'osp-results-layout/0.1', showNotes: false } as LayoutSettings; // saved before V6
		expect(fromSettings(pre, LATEST).theme).toEqual({ kind: 'app' });
		expect(fromSettings(pre, LATEST).exports).toEqual({ widthMm: 85, dpi: 300, k: null, bundle: 'all' });
		const read = (theme: unknown, exp: unknown) => fromSettings({ ...pre, theme, export: exp } as LayoutSettings, LATEST);
		expect(read({ kind: 'survey', id: null }, null).theme).toEqual({ kind: 'survey' });
		expect(read({ kind: 'preset', id: 'warm' }, null).theme).toEqual({ kind: 'preset', id: 'warm' });
		expect(read({ kind: 'library', id: 'bad id' }, null).theme).toEqual({ kind: 'app' });
		expect(read({ kind: 'rainbow' }, null).theme).toEqual({ kind: 'app' });
		expect(read(null, { widthMm: 120, dpi: 150, hideCountsBelow: 3, bundle: 'svg' }).exports).toEqual({ widthMm: 120, dpi: 150, k: 3, bundle: 'svg' });
		expect(read(null, { widthMm: 9, dpi: 72, hideCountsBelow: 1, bundle: 'pdf' }).exports).toEqual({ widthMm: 85, dpi: 300, k: null, bundle: 'all' });
		// Writing clamps to what the server accepts.
		const s = emptyState(LATEST);
		s.exports = { widthMm: 9999, dpi: 72, k: 1, bundle: 'zip' as never };
		expect(toSettings(s, LATEST).export).toEqual({ widthMm: 500, dpi: 300, hideCountsBelow: 2, bundle: 'all' });
		s.theme = { kind: 'survey' };
		expect(toSettings(s, LATEST).theme).toEqual({ kind: 'survey', id: null });
		// Never a theme document.
		s.theme = { kind: 'preset', id: 'warm' };
		expect(JSON.stringify(toSettings(s, LATEST))).not.toContain('colours');
		// A theme or export change is an unsaved change.
		const base = emptyState(LATEST);
		const themed = structuredClone(base);
		themed.theme = { kind: 'preset', id: 'warm' };
		expect(sameLayout(themed, base, LATEST, questions)).toBe(false);
		const bundled = structuredClone(base);
		bundled.exports.bundle = 'svg';
		expect(sameLayout(bundled, base, LATEST, questions)).toBe(false);
	});

	it('date bounds survive the trip as whole days', () => {
		expect(fromDay('2026-01-05T00:00:00Z')).toBe('2026-01-05');
		expect(toDay('2026-03-01T00:00:00Z')).toBe('2026-02-28');
		expect(toDay('2024-03-01T00:00:00Z')).toBe('2024-02-29');
		expect(fromDay('nonsense')).toBe('');
		expect(toDay(null)).toBe('');
	});
});

describe('display order', () => {
	it('lists the layout order first, the rest in survey order, ignoring unknown ids', () => {
		const out = inOrder(plain.cards, ['why', 'gone', 'fruit', 'why']).map((c) => c.question);
		expect(out).toEqual(['why', 'fruit', ...questions.filter((q) => q !== 'why' && q !== 'fruit')]);
	});

	it('moves one card, clamped to the ends', () => {
		expect(moved(['a', 'b', 'c'], 'c', 0)).toEqual(['c', 'a', 'b']);
		expect(moved(['a', 'b', 'c'], 'a', 1)).toEqual(['b', 'a', 'c']);
		expect(moved(['a', 'b', 'c'], 'a', 99)).toEqual(['b', 'c', 'a']);
		expect(moved(['a', 'b', 'c'], 'x', 0)).toEqual(['a', 'b', 'c']);
	});
});

describe('unsuitable chart ids', () => {
	it('fall back to the type default with a notice; suitable ones say nothing', () => {
		const cards = plain.cards as Card[];
		const notes = chartNotices(cards, { fruit: 'donut', age: 'likert', why: 'sparkline', col: 'multi-counts' });
		expect(notes.map((n) => n.question)).toEqual(['age', 'why']);
		expect(notes[0].message).toBe(
			'Age?: the layout\'s chart “Diverging stacked bars” does not suit this question, so it shows Histogram instead.'
		);
		expect(notes[1].message).toContain('“sparkline”');
		expect(notes[1].message).toContain('so it shows Response states instead');
		expect(chartNotices(cards, {})).toEqual([]);
	});
});

describe('layout errors', () => {
	it('say what went wrong for 409, 422, 403, 404 and the network', () => {
		expect(layoutError(409, { message: 'dup' }, { name: 'Paper', action: 'saved' })).toBe(
			'There is already a layout called “Paper”. Choose another name.'
		);
		expect(
			layoutError(
				422,
				{ message: 'That is not a valid results layout.', diagnostics: [{ code: 'layout.schema', message: 'Extra inputs are not permitted', pointer: '/cards/0/colour' }] },
				{ action: 'saved' }
			)
		).toBe('The layout could not be saved: Extra inputs are not permitted (at /cards/0/colour).');
		expect(layoutError(422, { detail: [{ msg: 'Field required' }] }, { action: 'saved' })).toBe(
			'The layout could not be saved: Field required.'
		);
		expect(layoutError(422, undefined, { action: 'renamed' })).toBe('The layout could not be renamed: the server refused it.');
		expect(layoutError(403, undefined, { action: 'saved' })).toMatch(/owner or editor/);
		expect(layoutError(404, undefined, { action: 'saved' })).toMatch(/no longer exists/);
		expect(layoutError(0, { message: 'Failed to fetch' }, { action: 'deleted' })).toBe('The layout could not be deleted: Failed to fetch.');
		expect(layoutError(500, undefined, { action: 'saved' })).toBe('The layout could not be saved (error 500).');
	});
});
