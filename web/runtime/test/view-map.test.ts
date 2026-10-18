import type { RenderedRun, RenderedText } from '@osp/engine';
import { describe, expect, it } from 'vitest';
import { paragraphs, plain, segs } from '../src/lib/view-map';

const txt = (text: string): RenderedRun => ({ kind: 'text', text });
const val = (text: string): RenderedRun => ({ kind: 'value', text });
const br: RenderedRun = { kind: 'br' };
const p = (...content: RenderedRun[]): RenderedText[number] => ({ type: 'p', content });

describe('ending body paragraphs (EN1)', () => {
	it('splits researcher text at blank lines and keeps single line breaks', () => {
		const body: RenderedText = [p(txt('Thanks, '), val('Ann'), txt('.\n\nYour code is\nC1AB2.\n \n'))];
		expect(paragraphs(body)).toEqual([p(txt('Thanks, '), val('Ann'), txt('.')), p(txt('Your code is\nC1AB2.'))]);
	});

	it('never splits a piped value, and drops empty paragraphs', () => {
		expect(paragraphs([p(val('a\n\nb'))])).toEqual([p(val('a\n\nb'))]);
		expect(paragraphs([p(txt('\n\n'))])).toEqual([]);
		expect(paragraphs(null)).toEqual([]);
	});

	it('keeps rich blocks as they are (RT2)', () => {
		const rich: RenderedText = [
			{ type: 'h', level: 1, content: [txt('Done')] },
			p(txt('a'), br, txt('b')),
			{ type: 'ul', items: [[txt('one')], [txt('two')]] }
		];
		expect(paragraphs(rich)).toEqual(rich);
	});
});

describe('engine text → widget text (RT2)', () => {
	it('maps a single paragraph to inline runs with marks, links and language', () => {
		const label: RenderedText = [
			p({ kind: 'text', text: 'Hi ', marks: ['b', 'i'], lang: 'fr' }, val('<x>'), br, { kind: 'text', text: 'doc', href: 'https://e.org' })
		];
		expect(segs(label)).toEqual([
			{ text: 'Hi ', strong: true, em: true, lang: 'fr' },
			{ text: '<x>' },
			{ br: true },
			{ text: 'doc', href: 'https://e.org' }
		]);
		expect(plain(label)).toBe('Hi <x>\ndoc');
	});

	it('maps several blocks to widget blocks', () => {
		const label: RenderedText = [{ type: 'h', level: 2, content: [txt('H')] }, { type: 'ol', items: [[val('v')]] }];
		expect(segs(label)).toEqual([
			{ type: 'h', level: 2, content: [{ text: 'H' }] },
			{ type: 'ol', items: [[{ text: 'v' }]] }
		]);
		expect(segs(null)).toEqual([]);
	});
});
