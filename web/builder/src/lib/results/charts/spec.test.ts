import { compile } from 'vega-lite';
import { describe, expect, it } from 'vitest';
import { FIXTURE_CARDS } from './fixtures';
import { entryOptions, galleryEntries } from './gallery';
import { chartsFor, splitsFor } from './menu';
import { suppressCard } from '../export/model';
import { buildSpec, defaultSpec } from './spec';
import { LIGHT_TOKENS, likertPalette, luminance, OKABE_ITO, sequentialPalette, themeConfig } from './theme';
import type { Card, ChartChoice } from './types';

type Json = Record<string, unknown>;

/** Compile with Vega-Lite, collecting every warning (a warning fails the check). */
function compileStrict(spec: unknown): { warnings: string[]; vega: Json } {
	const warnings: string[] = [];
	const logger = {
		level: () => logger,
		warn: (...a: unknown[]) => (warnings.push(a.join(' ')), logger),
		info: () => logger,
		debug: () => logger,
		error: (...a: unknown[]) => {
			throw new Error(a.join(' '));
		}
	};
	const out = compile(spec as Parameters<typeof compile>[0], { logger: logger as never });
	return { warnings, vega: out.spec as unknown as Json };
}

/** Every inline data row in a spec (any depth). */
function rows(spec: unknown): Json[] {
	const out: Json[] = [];
	const walk = (v: unknown) => {
		if (Array.isArray(v)) return v.forEach(walk);
		if (v && typeof v === 'object') {
			const o = v as Json;
			if (o.data && typeof o.data === 'object' && Array.isArray((o.data as Json).values)) out.push(...((o.data as Json).values as Json[]));
			for (const [k, x] of Object.entries(o)) if (k !== 'data') walk(x);
		}
	};
	walk(spec);
	return out;
}

const entries = galleryEntries();

describe('every gallery chart', () => {
	it('covers every chart choice in the menu table', () => {
		const choices = new Set(entries.map((e) => e.choice));
		const all: ChartChoice[] = ['bars', 'bars-sorted', 'donut', 'multi-pct', 'multi-counts', 'dot', 'histogram', 'values', 'box', 'cumulative', 'periods', 'likert', 'stacked100', 'heatmap', 'grouped', 'states'];
		expect([...choices].sort()).toEqual([...all].sort());
		const splits = new Set(entries.filter((e) => e.split).map((e) => e.split));
		expect([...splits].sort()).toEqual(['grouped', 'multiples', 'stacked']);
	});

	for (const e of entries) {
		it(`${e.id}: compiles without warnings and matches its snapshot`, () => {
			const spec = buildSpec(e.card, e.choice, entryOptions(e));
			const { warnings, vega } = compileStrict(spec);
			expect(warnings).toEqual([]);
			expect(vega.marks ?? vega.layout).toBeTruthy();
			// The export theme compiles too (fixed colours, no container width needed).
			expect(compileStrict(buildSpec(e.card, e.choice, entryOptions(e, { theme: 'export', width: 400 }))).warnings).toEqual([]);
			expect(spec).toMatchSnapshot();
		});
	}
});

describe('chartsFor', () => {
	const ids = (c: Card) => chartsFor(c).choices.map((x) => x.id);
	it('offers the plan table per question type, default first', () => {
		expect(ids(FIXTURE_CARDS.single)).toEqual(['bars', 'bars-sorted', 'donut', 'table']);
		expect(ids(FIXTURE_CARDS.multi)).toEqual(['multi-pct', 'multi-counts', 'dot', 'table']);
		expect(ids(FIXTURE_CARDS.integer)).toEqual(['histogram', 'box', 'cumulative', 'table']);
		expect(ids(FIXTURE_CARDS.sliderValues)).toEqual(['values', 'box', 'cumulative', 'table']);
		expect(ids(FIXTURE_CARDS.sliderBins)).toEqual(['histogram', 'box', 'cumulative', 'table']);
		expect(ids(FIXTURE_CARDS.date)).toEqual(['periods', 'table']);
		expect(chartsFor(FIXTURE_CARDS.date).binUnits).toEqual(['day', 'week', 'month', 'year']);
		expect(ids(FIXTURE_CARDS.matrixOrdered)).toEqual(['likert', 'stacked100', 'heatmap', 'table']);
		expect(ids(FIXTURE_CARDS.matrixUnordered)).toEqual(['grouped', 'heatmap', 'table']);
		expect(ids(FIXTURE_CARDS.text)).toEqual(['states', 'table']);
		expect(chartsFor(FIXTURE_CARDS.note)).toMatchObject({ default: 'hidden', choices: [{ id: 'hidden' }, { id: 'heading' }] });
		expect(chartsFor(FIXTURE_CARDS.single).default).toBe('bars');
	});
	it('offers split layouts only for split cards, never stacking multiple choice', () => {
		expect(chartsFor(FIXTURE_CARDS.single).splits).toEqual([]);
		expect(chartsFor(FIXTURE_CARDS.singleSplit).splits).toEqual(['grouped', 'stacked', 'multiples']);
		expect(splitsFor(FIXTURE_CARDS.multiSplit, 'multi-pct')).toEqual(['grouped', 'multiples']);
		expect(splitsFor(FIXTURE_CARDS.matrixSplit, 'likert')).toEqual(['multiples']);
	});
});

describe('buildSpec semantics', () => {
	it('keeps the declared option order for bars and sorts by count for sorted bars', () => {
		const sortOf = (s: unknown) => ((s as Json).layer as Json[])[0] as Json;
		const declared = ((sortOf(buildSpec(FIXTURE_CARDS.single, 'bars')).encoding as Json).y as Json).sort;
		expect(declared).toEqual(['Bus', 'Train', 'Bicycle', 'Car', 'On foot']);
		const sorted = ((sortOf(buildSpec(FIXTURE_CARDS.single, 'bars-sorted')).encoding as Json).y as Json).sort;
		expect(sorted).toEqual(['Car', 'Bus', 'Train', 'Bicycle', 'On foot']);
	});

	it('labels multiple choice as % of respondents that can sum over 100 %', () => {
		const s = JSON.stringify(buildSpec(FIXTURE_CARDS.multi, 'multi-pct'));
		expect(s).toContain('% of answered responses (can sum > 100 %) (n = 140)');
		const total = rows(buildSpec(FIXTURE_CARDS.multi, 'multi-pct')).reduce((a, d) => a + Number(d.p), 0);
		expect(total).toBeGreaterThan(1);
	});

	it('uses V1 shares, not recomputed ones, and shows the denominator', () => {
		const data = rows(buildSpec(FIXTURE_CARDS.single, 'bars', { denominator: 'shown' }));
		expect(data[0]).toMatchObject({ label: 'Bus', count: 42, p: FIXTURE_CARDS.single.groups![0].cells[0].pct! / 100 });
		expect(JSON.stringify(buildSpec(FIXTURE_CARDS.single, 'bars', { denominator: 'shown' }))).toContain('% of shown responses (n = 160)');
	});

	it('draws histograms on V1 shared bin edges, edges on the axis', () => {
		const s = buildSpec(FIXTURE_CARDS.integer, 'histogram') as unknown as Json;
		const x = (s.encoding as Json).x as Json;
		expect((x.axis as Json).values).toEqual(FIXTURE_CARDS.integer.binEdges);
		expect(x.scale).toMatchObject({ domain: [15, 70], nice: false });
		// Split histograms are small multiples on the same edges.
		const split = buildSpec(FIXTURE_CARDS.integerSplit, 'histogram') as unknown as Json;
		expect(split.facet).toBeTruthy();
		expect((((split.spec as Json).encoding as Json).x as Json).axis).toMatchObject({ values: FIXTURE_CARDS.integer.binEdges });
	});

	it('draws box plots from V1 quartiles with no raw points', () => {
		const data = rows(buildSpec(FIXTURE_CARDS.integer, 'box'));
		expect(data).toEqual([expect.objectContaining({ min: 18, q1: 26, median: 32, q3: 41.5, max: 69 })]);
		const marks = JSON.stringify(buildSpec(FIXTURE_CARDS.integer, 'box'));
		expect(marks).not.toContain('"boxplot"');
		expect(marks).not.toContain('meanCi');
		const withCi = rows(buildSpec(FIXTURE_CARDS.integer, 'box', { intervals: true }));
		expect(withCi[0]).toMatchObject({ mean: 34.6, ciLo: 32.9, ciHi: 36.3 });
	});

	it('cumulative distribution ends at 100 % per group', () => {
		const data = rows(buildSpec(FIXTURE_CARDS.integerSplit, 'cumulative'));
		for (const g of ['Control (n = 76)', 'Treatment (n = 72)']) {
			const pts = data.filter((d) => d.groupLabel === g);
			expect(pts[0]).toMatchObject({ x: 15, cum: 0 });
			expect(pts.at(-1)).toMatchObject({ x: 70, cum: 1 });
		}
	});

	it('centres the neutral category of a diverging Likert bar', () => {
		const data = rows(buildSpec(FIXTURE_CARDS.matrixOrdered, 'likert'));
		for (const row of new Set(data.map((d) => d.row))) {
			const segs = data.filter((d) => d.row === row);
			const neutral = segs.find((d) => d.label === 'Neither agree nor disagree')!;
			expect(Number(neutral.x0) + Number(neutral.x1)).toBeCloseTo(0, 10);
			expect(Number(segs.at(-1)!.x1) - Number(segs[0].x0)).toBeCloseTo(1, 10);
		}
		// 100 % stacked starts at 0.
		const stacked = rows(buildSpec(FIXTURE_CARDS.matrixOrdered, 'stacked100'));
		expect(stacked[0].x0).toBe(0);
	});

	it('gives each matrix row its own n', () => {
		const labels = new Set(rows(buildSpec(FIXTURE_CARDS.matrixOrdered, 'heatmap')).map((d) => d.rowLabel));
		expect([...labels]).toEqual(['The survey was easy to complete\nn = 120', 'I would recommend it to a friend\nn = 120', 'I would take part again\nn = 120']);
	});

	it('draws Wilson intervals only when asked and when V1 sent them', () => {
		expect(JSON.stringify(buildSpec(FIXTURE_CARDS.single, 'bars'))).not.toContain('"ciLo","type"');
		const s = buildSpec(FIXTURE_CARDS.single, 'bars', { intervals: true }) as unknown as Json;
		expect((s.layer as Json[]).map((l) => (l.mark as Json).type)).toEqual(['bar', 'rule', 'text']);
		expect(rows(s)[0].ciLo).toBeCloseTo(FIXTURE_CARDS.single.groups![0].cells[0].ci![0] / 100, 10);
	});

	it('split variants: grouped, stacked and small multiples', () => {
		const grouped = buildSpec(FIXTURE_CARDS.singleSplit, 'bars', { split: 'grouped' }) as unknown as Json;
		expect(JSON.stringify(grouped)).toContain('"yOffset"');
		const stacked = rows(buildSpec(FIXTURE_CARDS.singleSplit, 'bars', { split: 'stacked' }));
		const ctl = stacked.filter((d) => d.groupLabel === 'Control (n = 74)');
		expect(Number(ctl.at(-1)!.x1)).toBeCloseTo(1, 10);
		const multiples = buildSpec(FIXTURE_CARDS.singleSplit, 'bars', { split: 'multiples' }) as unknown as Json;
		expect(multiples.facet).toMatchObject({ row: { field: 'groupLabel', sort: ['Control (n = 74)', 'Treatment (n = 70)', 'No value (n = 16)'] } });
		// A layout the chart can't do falls back to its first.
		expect((buildSpec(FIXTURE_CARDS.multiSplit, 'multi-pct', { split: 'stacked' }) as unknown as Json).usermeta).toMatchObject({ osp: { split: 'grouped' } });
	});

	it('per-version facets: one panel per version', () => {
		const s = buildSpec(FIXTURE_CARDS.facets, 'bars') as unknown as Json;
		expect((s.vconcat as Json[]).map((v) => (v.title as Json).text)).toEqual(['Version 2', 'Version 3']);
	});

	it('says so when there are no answers, and refuses non-charts or mismatched types', () => {
		expect(JSON.stringify(buildSpec(FIXTURE_CARDS.empty, 'bars'))).toContain('No answers to show.');
		expect(() => buildSpec(FIXTURE_CARDS.single, 'table')).toThrow(/not a chart/);
		expect(() => buildSpec(FIXTURE_CARDS.single, 'histogram')).toThrow(/does not fit/);
		expect(defaultSpec(FIXTURE_CARDS.note)).toBeNull();
		expect(defaultSpec(FIXTURE_CARDS.matrixUnordered)).toMatchObject({ usermeta: { osp: { chart: 'grouped' } } });
	});

	it('never relies on colour alone: coloured charts have direct text labels', () => {
		for (const e of entries) {
			const s = JSON.stringify(buildSpec(e.card, e.choice, entryOptions(e)));
			if (s.includes('"color":{"field"') && !s.includes('"strokeDash"') && e.choice !== 'heatmap') {
				expect(s, e.id).toContain('"mark":{"type":"text"');
			}
		}
	});
});

describe('themes', () => {
	it('export theme: white background, Okabe-Ito, >= 8 pt text', () => {
		const c = themeConfig('export') as Json;
		expect(c.background).toBe('#ffffff');
		expect((c.range as Json).category).toEqual(OKABE_ITO);
		const sizes = JSON.stringify(c).match(/"(label|title)?[Ff]ontSize":\d+/g)!.map((m) => Number(m.split(':')[1]));
		expect(Math.min(...sizes)).toBeGreaterThanOrEqual(11);
	});
	it('app theme follows the tokens', () => {
		const dark = { bg: '#12151b', surface: '#191d25', border: '#333a48', borderStrong: '#7c8699', text: '#e6e9ef', textMuted: '#a9b1bf', accent: '#b7a6ff', font: 'system-ui' };
		const c = themeConfig('app', dark) as Json;
		expect(c.background).toBe('transparent');
		expect((c.axis as Json).labelColor).toBe('#a9b1bf');
		expect(((c.range as Json).category as string[])[0]).toBe('#b7a6ff');
		expect((c.range as Json).category).not.toContain('#000000');
	});
	it('sequential palettes run light to strong on a light background', () => {
		expect(luminance('#ffffff')).toBeCloseTo(1, 5);
		expect(luminance('#fff')).toBeCloseTo(1, 5);
		expect(luminance('rgb(255, 255, 255)')).toBeCloseTo(1, 5);
		expect(luminance('#12151b')).toBeLessThan(0.2);
		const light = sequentialPalette('app', LIGHT_TOKENS);
		expect(luminance(light[0])).toBeGreaterThan(luminance(light.at(-1)!));
	});
	it('Likert palettes are ordered with a grey neutral middle', () => {
		expect(likertPalette(5)).toHaveLength(5);
		expect(likertPalette(5)[2]).toBe('#d4d4d4');
		expect(likertPalette(4)).not.toContain('#d4d4d4');
		expect(likertPalette(7, 'app')).toHaveLength(7);
		expect(likertPalette(1)).toEqual(['#d4d4d4']);
	});
});

describe('hidden cells ("Hide counts below k", drawn on screen in presentation mode: LV4)', () => {
	it('a donut whose every answered option is hidden says so, instead of an empty ring with no accessible name', () => {
		const all = suppressCard(FIXTURE_CARDS.single, 1000).card;
		const spec = buildSpec(all, 'donut', { hiddenLabel: 'n<1000' });
		expect(compileStrict(spec).warnings).toEqual([]);
		expect(rows(spec)).toEqual([{ message: 'Every option has n<1000 responses: counts hidden.' }]);
		// Unsuppressed, the same card draws its slices, each labelled option and share.
		const slices = rows(buildSpec(FIXTURE_CARDS.single, 'donut')).filter((r) => 'slice' in r);
		expect(slices.length).toBeGreaterThan(0);
	});
});
