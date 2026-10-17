import { describe, expect, it } from 'vitest';
import { compile } from 'vega-lite';
import fixture from '../fixtures/results.json';
import type { Card, HiddenCell } from '../charts/types';
import type { ResultsResponse } from '../types';
import { crc32, utf8 } from './bytes';
import { figureSpec, physicalSvg } from './figure';
import {
	autoCaption,
	cardCsv,
	csvField,
	cssWidth,
	describeN,
	fileName,
	fileStem,
	manifest,
	pixelHeight,
	pixelWidth,
	smallCells,
	suppressCard,
	wrapText
} from './model';
import { pixelsPerMetre, pngInfo, withDpi } from './png';
import { figureChoice } from './run';
import { readZip, zipStore } from './zip';

// Figure export, the pure parts (task V4): sizes, PNG pHYs, ZIP, suppression, captions,
// CSV, manifest, and the export spec. Cards are V1's real answers (fixtures/results.json).

const plain = fixture.plain as unknown as ResultsResponse;
const split = fixture.split as unknown as ResultsResponse;
const card = (q: string, r = plain) => r.cards.find((c) => c.question === q)! as Card;
const FILTERS = ['Version 1', 'Complete responses only', 'Denominator: answered'];

/** A 1 × 1 RGBA PNG, as a browser canvas would make it (no pHYs). */
const PNG_1PX = Uint8Array.from(
	atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='),
	(c) => c.charCodeAt(0)
);

type Json = Record<string, unknown>;

/** Every datum of every `data.values` in a spec. */
function values(spec: unknown): Json[] {
	const out: Json[] = [];
	const walk = (n: unknown) => {
		if (Array.isArray(n)) return n.forEach(walk);
		if (!n || typeof n !== 'object') return;
		const o = n as Json;
		const d = o.data as { values?: Json[] } | undefined;
		if (d?.values) out.push(...d.values);
		for (const v of Object.values(o)) if (v && typeof v === 'object' && v !== d) walk(v);
	};
	walk(spec);
	return out;
}

describe('sizes', () => {
	it('turns millimetres into final-size CSS px and PNG pixels', () => {
		expect(cssWidth(85)).toBe(321);
		expect(cssWidth(180)).toBe(680);
		expect(pixelWidth(85, 150)).toBe(502);
		expect(pixelWidth(85, 300)).toBe(1004);
		expect(pixelWidth(85, 600)).toBe(2008);
		expect(pixelWidth(180, 300)).toBe(2126);
		expect(pixelHeight(321, 200, 1004)).toBe(626);
	});
});

describe('PNG DPI metadata', () => {
	it('computes CRC-32 like zlib', () => {
		expect(crc32(utf8('123456789'))).toBe(0xcbf43926);
		expect(crc32(utf8('1234'), utf8('56789'))).toBe(0xcbf43926);
	});

	it('writes a pHYs chunk right after IHDR, in pixels per metre, with a valid CRC', () => {
		expect(pngInfo(PNG_1PX)).toMatchObject({ width: 1, height: 1, dpi: null, chunks: ['IHDR', 'IDAT', 'IEND'] });
		for (const dpi of [150, 300, 600]) {
			const out = withDpi(PNG_1PX, dpi);
			const info = pngInfo(out);
			expect(info).toMatchObject({ width: 1, height: 1, dpi, chunks: ['IHDR', 'pHYs', 'IDAT', 'IEND'] });
			const at = 8 + 25; // after the signature and IHDR
			const dv = new DataView(out.buffer, out.byteOffset);
			expect(dv.getUint32(at)).toBe(9);
			expect(dv.getUint32(at + 8)).toBe(pixelsPerMetre(dpi));
			expect(dv.getUint32(at + 12)).toBe(pixelsPerMetre(dpi));
			expect(out[at + 16]).toBe(1);
			expect(dv.getUint32(at + 17)).toBe(crc32(out.subarray(at + 4, at + 17)));
		}
		expect(pixelsPerMetre(300)).toBe(11811);
	});

	it('replaces an existing pHYs and refuses bytes that are not a PNG', () => {
		const twice = withDpi(withDpi(PNG_1PX, 150), 600);
		expect(pngInfo(twice).chunks).toEqual(['IHDR', 'pHYs', 'IDAT', 'IEND']);
		expect(pngInfo(twice).dpi).toBe(600);
		expect(() => withDpi(utf8('GIF89a, not a png at all, really'), 300)).toThrow('not a PNG');
		expect(() => withDpi(PNG_1PX, 0)).toThrow();
	});
});

describe('ZIP', () => {
	it('stores entries with CRCs and a central directory that reads back', () => {
		const files = [
			{ name: 'fruit.svg', data: utf8('<svg/>') },
			{ name: 'fruit.png', data: PNG_1PX },
			{ name: 'Größe.csv', data: utf8('a,b\r\n') },
			{ name: 'manifest.json', data: utf8('{}') }
		];
		const zip = zipStore(files, new Date(2026, 9, 17, 12, 30, 10));
		const dv = new DataView(zip.buffer);
		expect(dv.getUint32(0, true)).toBe(0x04034b50);
		expect(dv.getUint16(8, true)).toBe(0); // stored
		expect(dv.getUint32(zip.length - 22, true)).toBe(0x06054b50);
		expect(dv.getUint16(zip.length - 12, true)).toBe(4);
		const back = readZip(zip);
		expect(back.map((e) => e.name)).toEqual(files.map((f) => f.name));
		expect([...back[1].data]).toEqual([...PNG_1PX]);
		expect(() => zipStore([files[0], files[0]])).toThrow('duplicate');
	});
});

describe('suppression ("Hide counts below k")', () => {
	it('hides 1 … k-1, keeps zeros, nulls the share and counts what it hid', () => {
		const { card: s, hidden } = suppressCard(card('fruit'), 3);
		expect(hidden).toBe(2); // apple 2, banana 1; cherry 0 stays a zero
		const cells = s.groups![0].cells as HiddenCell[];
		expect(cells.map((c) => [c.key, c.hidden ?? false, c.pct])).toEqual([
			['apple', true, null],
			['banana', true, null],
			['cherry', false, 0]
		]);
		expect(suppressCard(card('fruit'), null).card).toBe(card('fruit'));
		expect(card('fruit').groups![0].cells[0].pct).not.toBeNull(); // the original is untouched
	});

	it('reaches grid rows and split groups', () => {
		const grid = suppressCard(card('grid'), 5);
		expect(grid.hidden).toBeGreaterThan(0);
		expect(grid.card.rows!.every((r) => r.groups.every((g) => g.cells.every((c) => c.count === 0 || (c as HiddenCell).hidden)))).toBe(true);
		const fruit = suppressCard(card('fruit', split), 5);
		expect(fruit.card.groups!.length).toBe(3);
	});

	it('counts shown cells under 5 for the warning', () => {
		expect(smallCells(card('fruit'))).toBe(2);
		expect(smallCells(suppressCard(card('fruit'), 5).card)).toBe(0);
		expect(smallCells(suppressCard(card('fruit'), 2).card)).toBe(1); // apple 2 still shown
	});

	it('draws hidden cells as a label with no count or share, distinct from a zero', () => {
		const { spec, hidden } = figureSpec(card('fruit'), {
			chart: 'bars',
			denominator: 'answered',
			intervals: false,
			widthMm: 85,
			caption: 'c',
			k: 5
		});
		expect(hidden).toBe(2);
		const rows = values(spec).filter((d) => 'key' in d);
		const byKey = Object.fromEntries(rows.map((d) => [d.key, d]));
		expect(byKey.apple).toMatchObject({ count: null, p: null, text: 'n<5', countText: 'n<5', hidden: true });
		expect(byKey.cherry).toMatchObject({ count: 0, p: 0, text: '0%' });
		expect(JSON.stringify(spec)).toContain('"invalid":"show"');
		expect(compile(spec as never).spec).toBeTruthy();
	});
});

describe('captions', () => {
	it('name the question, variable, versions, filters, split, denominator and n', () => {
		expect(autoCaption(card('fruit'), { filters: FILTERS, k: null, hiddenCells: 0 })).toBe(
			'Fruit? (fruit). Version 1; Complete responses only; Denominator: answered. n = 3 responses.'
		);
		const sf = card('fruit', split);
		const text = autoCaption(sf, { filters: [...FILTERS.slice(0, 2), 'Split by condition arm', FILTERS[2]], k: 5, hiddenCells: 4 });
		expect(text).toContain('Split by condition arm');
		expect(text).toContain('n = 2 (a), 1 (b), 0 (No condition) responses.');
		expect(text).toContain('Counts below 5 hidden (shown as "n<5"; 4 cells).');
		expect(describeN(card('grid'))).toMatch(/^n per row /);
	});

	it('wrap at spaces and are drawn under the figure', () => {
		expect(wrapText('aaa bbb ccc ddd', 7)).toEqual(['aaa bbb', 'ccc ddd']);
		const caption = 'Fruit? (fruit). Version 1; Complete responses only; Denominator: answered. n = 3 responses.';
		const { spec } = figureSpec(card('fruit'), { chart: 'donut', denominator: 'answered', intervals: false, widthMm: 85, caption, k: null });
		const title = (spec as unknown as Json).title as Json;
		expect(title).toMatchObject({ orient: 'bottom', anchor: 'start', fontSize: 11 });
		expect((title.text as string[]).join(' ')).toBe(caption);
		expect(((spec as unknown as Json).usermeta as Json).osp).toMatchObject({ caption, widthMm: 85, hideCountsBelow: null });
	});
});

describe('export spec', () => {
	it('is the export theme at the final width, data embedded, and compiles cleanly', () => {
		for (const q of ['fruit', 'col', 'age', 'sl', 'when', 'grid', 'why']) {
			const c = card(q);
			const { chart, layout } = figureChoice(c, { get: () => undefined, layout: () => undefined });
			const { spec, widthPx } = figureSpec(c, { chart: chart!, layout, denominator: 'answered', intervals: false, widthMm: 85, caption: q, k: 5 });
			expect(widthPx).toBe(321);
			expect((spec as unknown as Json).config).toMatchObject({ background: '#ffffff' });
			expect(values(spec).length).toBeGreaterThan(0);
			const warnings: string[] = [];
			compile(spec as never, { logger: { warn: (...m: unknown[]) => warnings.push(m.join(' ')), level: () => 0, info: () => {}, debug: () => {}, error: () => {} } as never });
			expect(warnings, q).toEqual([]);
		}
	});

	it('sets the SVG size in millimetres, keeping the viewBox', () => {
		const svg = '<svg xmlns="http://www.w3.org/2000/svg" class="marks" width="321" height="200" viewBox="0 0 321 200"><text>x</text></svg>';
		expect(physicalSvg(svg, 85)).toContain('width="85mm" height="52.96mm" viewBox="0 0 321 200"');
		expect(physicalSvg('<svg width="10" height="5">', 20)).toContain('viewBox="0 0 10 5"');
	});

	it('falls back from the Table to the default chart', () => {
		const choice = figureChoice(card('fruit', split), { get: () => 'table', layout: () => 'stacked' });
		expect(choice).toEqual({ chart: 'bars', layout: 'stacked' });
		expect(figureChoice(card('fruit'), { get: () => 'donut', layout: () => 'stacked' })).toEqual({ chart: 'donut', layout: undefined });
	});
});

describe('CSV', () => {
	it('has counts, n, denominators, bin edges and hidden markers', () => {
		const csv = cardCsv(card('fruit'), { denominator: 'answered', k: null }).split('\r\n');
		expect(csv[0]).toBe(
			'question,variable,type,version,row,group,group_label,group_n,denominator,category,label,bin_lo,bin_hi,count,percent,ci_low,ci_high,hidden'
		);
		expect(csv[1]).toBe('fruit,fruit,single,1,,all,All responses,3,answered,apple,Apple,,,2,66.6667,,,');
		expect(csv.at(-1)).toBe('');
		const hidden = cardCsv(suppressCard(card('fruit'), 5).card, { denominator: 'answered', k: 5 }).split('\r\n');
		expect(hidden[1]).toBe('fruit,fruit,single,1,,all,All responses,3,answered,apple,Apple,,,,,,,<5');
		expect(hidden[3]).toBe('fruit,fruit,single,1,,all,All responses,3,answered,cherry,Cherry,,,0,0,,,');
		const age = cardCsv(card('age'), { denominator: 'answered', k: null }).split('\r\n');
		const [lo, hi] = [11, 12].map((i) => age[0].split(',')[i]);
		expect([lo, hi]).toEqual(['bin_lo', 'bin_hi']);
		expect(age[1].split(',').slice(11, 13).every((v) => v !== '')).toBe(true);
		const grid = cardCsv(card('grid'), { denominator: 'shown', k: null }).split('\r\n');
		expect(new Set(grid.slice(1, -1).map((l) => l.split(',')[4])).size).toBe(2); // one per row
	});

	it('quotes and defuses spreadsheet formulas', () => {
		expect(csvField('a,b')).toBe('"a,b"');
		expect(csvField('say "hi"')).toBe('"say ""hi"""');
		expect(csvField('=1+1')).toBe("'=1+1");
		expect(csvField(-3)).toBe('-3');
		expect(csvField(null)).toBe('');
	});
});

describe('file names and manifest', () => {
	it('uses the variable name, made safe', () => {
		expect(fileStem({ name: 'q1/../x y', question: 'q' })).toBe('q1_x_y');
		expect(fileName({ name: 'fruit', question: 'fruit' }, 'vega-lite')).toBe('fruit.vl.json');
		expect(fileName({ name: '', question: '' }, 'png')).toBe('question.png');
	});

	it('records where the figures came from, without values', () => {
		const m = manifest({
			response: plain,
			query: { status: 'complete', denominator: 'answered', intervals: false, versions: [1] },
			filters: FILTERS,
			k: 5,
			figures: [],
			exportedAt: '2026-10-17T13:00:00Z',
			platform: { name: 'osp', version: '1.2.3' },
			libraries: { vega: '6.4.0', vegaLite: '6.4.3', vegaEmbed: '7.3.0' },
			scope: 'page'
		});
		expect(m).toMatchObject({
			surveyId: 'fixture-survey',
			versions: [1],
			queryHash: 'aba46e5344bb917f',
			generatedAt: '2026-10-17T12:00:00Z',
			denominator: 'answered',
			split: null,
			suppression: { hideCountsBelow: 5, marker: 'n<5' },
			platform: { version: '1.2.3' },
			vega: { vegaLite: '6.4.3' }
		});
	});
});
