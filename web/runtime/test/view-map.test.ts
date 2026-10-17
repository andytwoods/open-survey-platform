import type { RenderedText } from '@osp/engine';
import { describe, expect, it } from 'vitest';
import { paragraphs } from '../src/lib/view-map';

const txt = (text: string) => ({ kind: 'text' as const, text });
const val = (text: string) => ({ kind: 'value' as const, text });

describe('ending body paragraphs (EN1)', () => {
	it('splits researcher text at blank lines and keeps single line breaks', () => {
		const body: RenderedText = [txt('Thanks, '), val('Ann'), txt('.\n\nYour code is\nC1AB2.\n \n')];
		expect(paragraphs(body)).toEqual([[txt('Thanks, '), val('Ann'), txt('.')], [txt('Your code is\nC1AB2.')]]);
	});

	it('never splits a piped value, and drops empty paragraphs', () => {
		expect(paragraphs([val('a\n\nb')])).toEqual([[val('a\n\nb')]]);
		expect(paragraphs([txt('\n\n')])).toEqual([]);
		expect(paragraphs(null)).toEqual([]);
	});
});
