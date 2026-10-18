/**
 * Rich text (planning/rich-text.md, task RT2): the TypeScript normalisation agrees with
 * Python on the shared cases, rendering keeps formatting and fills pipes, and `toHtml` /
 * `toPlain` flatten blocks the way the traces and accessible names need.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
	answer,
	charCount,
	isRichText,
	normaliseText,
	plainTextOf,
	start,
	toBlocks,
	toHtml,
	toPlain,
	valueText,
	view,
	withChecksum,
	type RichBlock,
	type Plan,
	type RenderedText,
	type RichText
} from '../src/index.ts';
import { REPO } from './fixture-runner.ts';
import { makePlan, q } from './helpers.ts';

interface Case {
	name: string;
	input: unknown;
	output: unknown;
}
const CASES = (JSON.parse(readFileSync(join(REPO, 'python/osp-spec/tests/cases/richtext-normalise.json'), 'utf8')) as { cases: Case[] })
	.cases;

describe('normaliseText (shared cases with osp_spec.richtext.normalise_text)', () => {
	for (const c of CASES) {
		it(c.name, () => {
			const before = JSON.stringify(c.input);
			expect(normaliseText(c.input)).toEqual(c.output);
			expect(JSON.stringify(c.input)).toBe(before); // never mutates its input
		});
	}
});

const TREE: RichText = {
	type: 'rich',
	blocks: [
		{ type: 'h', level: 1, content: [{ text: 'Before you start' }] },
		{
			type: 'p',
			content: [
				{ text: 'Hello ' },
				{ pipe: 'name' },
				{ text: '!', marks: ['b'] },
				{ br: true },
				{ text: 'Read the ' },
				{ text: 'sheet', href: 'https://example.org/s' },
				{ text: ' now', href: 'https://example.org/s', marks: ['i'] }
			]
		},
		{ type: 'ul', items: [[{ text: 'one', lang: 'fr' }], [{ text: 'two' }]] },
		{ type: 'ol', items: [[{ text: 'first' }]] }
	]
};

describe('plainTextOf / charCount', () => {
	it('flattens blocks, lists, breaks and pipes like osp_spec.richtext.to_plain', () => {
		expect(plainTextOf(TREE)).toBe('Before you start\n\nHello ${name}!\nRead the sheet now\n\n- one\n- two\n\n1. first');
		expect(plainTextOf('plain')).toBe('plain');
		expect(plainTextOf(null)).toBe('');
		expect(charCount('abc ${name} d')).toBe(6);
		expect(charCount(TREE)).toBe('Before you start'.length + 'Hello !Read the sheet now'.length + 'onetwofirst'.length);
		expect(isRichText(TREE)).toBe(true);
		expect(isRichText({ en: 'x' })).toBe(false);
	});
});

describe('rendering rich blocks', () => {
	const plan: Plan = withChecksum(
		makePlan({
			pages: {
				p1: [q('name', 'text'), { ...q('note', 'note'), label: { en: TREE.blocks as RichBlock[] } }]
			}
		})
	);

	it('fills pipes inside formatting and keeps marks, links, breaks and language spans', () => {
		let s = start(plan, { sessionSeed: 1, clock: () => 1 });
		s = answer(s, 'name', 'Ann & <Co>');
		const label = view(s).items[1]!.label;
		expect(label[0]).toEqual({ type: 'h', level: 1, content: [{ kind: 'text', text: 'Before you start' }] });
		const para = label[1]!;
		expect(para.type === 'p' && para.content[1]).toEqual({ kind: 'value', text: 'Ann & <Co>' });
		expect(para.type === 'p' && para.content[3]).toEqual({ kind: 'br' });
		expect(toHtml(label)).toBe(
			'<h3>Before you start</h3>' +
				'<p>Hello Ann &amp; &lt;Co&gt;<strong>!</strong><br>Read the ' +
				'<a href="https://example.org/s" target="_blank" rel="noopener noreferrer">sheet<em> now</em></a></p>' +
				'<ul><li><span lang="fr">one</span></li><li>two</li></ul><ol><li>first</li></ol>'
		);
		expect(toPlain(label)).toBe('Before you start\n\nHello Ann & <Co>!\nRead the sheet now\n\none\ntwo\n\nfirst');
	});

	it('renders a plain string as one paragraph with no wrapper (traces unchanged)', () => {
		const s = start(plan, { sessionSeed: 1, clock: () => 1 });
		const label = view(s).items[0]!.label;
		expect(label).toEqual([{ type: 'p', content: [{ kind: 'text', text: 'name' }] }]);
		expect(toHtml(label)).toBe('name');
		expect(toPlain(label)).toBe('name');
		expect(toBlocks(['a ', { pipe: 'x' }])).toEqual([{ type: 'p', content: [{ text: 'a ' }, { pipe: 'x' }] }]);
		expect(toBlocks([])).toEqual([{ type: 'p', content: [] }]);
	});

	it('escapes values but writes researcher text as it is, and a hook message is a value', () => {
		const text: RenderedText = [{ type: 'p', content: [{ kind: 'text', text: 'a > b' }, { kind: 'value', text: '<x>' }] }];
		expect(toHtml(text)).toBe('a > b&lt;x&gt;');
		expect(toHtml(valueText('<img>'))).toBe('&lt;img&gt;');
		expect(toHtml(null)).toBe('');
		expect(toPlain(null)).toBe('');
	});
});
