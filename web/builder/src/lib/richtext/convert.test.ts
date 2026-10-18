import type { InlineRun, RichBlock, RichText } from '@osp/engine';
import { describe, expect, it } from 'vitest';
import {
	asRich,
	canonical,
	fromDoc,
	isEmptyValue,
	isPipeRef,
	normalForm,
	pipesOf,
	plainToRich,
	sameValue,
	toDoc,
	type PmNode
} from './convert';
import type { Level } from './levels';

// The survey tree <-> ProseMirror JSON converters: round trips (property-based, with a
// seeded generator so a failure reproduces), plain-string parsing, lowering per level and
// the normal form a field commits (RT-D3). No DOM, no Tiptap.

/** A small deterministic PRNG (mulberry32), so each case is reproducible by its seed. */
function rng(seed: number) {
	let a = seed >>> 0;
	return () => {
		a = (a + 0x6d2b79f5) >>> 0;
		let t = a;
		t = Math.imul(t ^ (t >>> 15), t | 1);
		t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
	};
}

const WORDS = ['how', 'often', 'do', 'you', 'sleep', 'well', 'über', 'نوم', '😀', 'a b', '${not a pipe}', 'x'];
const pick = <T>(r: () => number, xs: readonly T[]): T => xs[Math.floor(r() * xs.length)]!;

/** A canonical run list: no empty text, adjacent equal formats merged. */
function genRuns(r: () => number, pipes = true): InlineRun[] {
	const n = Math.floor(r() * 5);
	const out: InlineRun[] = [];
	for (let i = 0; i < n; i++) {
		const k = r();
		if (k < 0.15) out.push({ br: true });
		else if (k < 0.3 && pipes) out.push({ pipe: pick(r, ['age', 'q1', '$language', 'm_r1', 'name_2']) });
		else {
			const run: InlineRun = { text: pick(r, WORDS) + (r() < 0.5 ? ' ' : '') };
			const marks = ([] as ('b' | 'i')[]).concat(r() < 0.4 ? ['b'] : [], r() < 0.4 ? ['i'] : []);
			if (marks.length) run.marks = marks;
			if (r() < 0.25) run.href = pick(r, ['https://example.org/a', 'https://example.org/b?x=1']);
			if (r() < 0.15) run.lang = pick(r, ['fr', 'de-CH']);
			out.push(run);
		}
	}
	return out;
}

function genTree(r: () => number, level: Level): RichText {
	const n = level === 'inline' ? 1 : 1 + Math.floor(r() * 4);
	const blocks: RichBlock[] = [];
	for (let i = 0; i < n; i++) {
		const k = r();
		if (level === 'block' && k < 0.25) blocks.push({ type: 'h', level: pick(r, [1, 2, 3] as const), content: genRuns(r) });
		else if (level !== 'inline' && k < 0.5) {
			const items: InlineRun[][] = [];
			const m = 1 + Math.floor(r() * 3);
			for (let j = 0; j < m; j++) items.push(genRuns(r));
			blocks.push({ type: pick(r, ['ul', 'ol'] as const), items });
		} else blocks.push({ type: 'p', content: genRuns(r) });
	}
	return { type: 'rich', blocks };
}

describe('round trips', () => {
	for (const level of ['block', 'stem', 'inline'] as const) {
		it(`fromDoc(toDoc(x)) is canonical(x) at level ${level} (300 seeded trees)`, () => {
			for (let seed = 1; seed <= 300; seed++) {
				const tree = genTree(rng(seed), level);
				const back = fromDoc(toDoc(tree, level));
				expect(back, `seed ${seed}`).toEqual(canonical(tree));
			}
		});
	}

	it('toDoc(fromDoc(d)) is d for the documents it produces', () => {
		for (let seed = 1; seed <= 100; seed++) {
			const doc = toDoc(genTree(rng(seed), 'block'), 'block');
			expect(toDoc(fromDoc(doc), 'block'), `seed ${seed}`).toEqual(doc);
		}
	});

	it('canonical is idempotent and merges equal neighbours, drops empties, orders marks', () => {
		const tree: RichText = {
			type: 'rich',
			blocks: [
				{
					type: 'p',
					content: [
						{ text: 'a', marks: ['i', 'b'] },
						{ text: '' },
						{ text: 'b', marks: ['b', 'i'] },
						{ text: 'c' },
						{ pipe: ' age ' },
						{ text: 'd', href: 'https://e.org' },
						{ text: 'e', href: 'https://e.org' }
					]
				}
			]
		};
		const c = canonical(tree);
		expect(c.blocks[0]).toEqual({
			type: 'p',
			content: [{ text: 'ab', marks: ['b', 'i'] }, { text: 'c' }, { pipe: 'age' }, { text: 'de', href: 'https://e.org' }]
		});
		expect(canonical(c)).toEqual(c);
	});
});

describe('plain strings', () => {
	it('parse pipes and newlines, leaving non-references as text', () => {
		expect(plainToRich('Hi ${name}, you are ${age}.\nOK ${not ok} ${$language} ${}').blocks).toEqual([
			{
				type: 'p',
				content: [
					{ text: 'Hi ' },
					{ pipe: 'name' },
					{ text: ', you are ' },
					{ pipe: 'age' },
					{ text: '.' },
					{ br: true },
					{ text: 'OK ${not ok} ' },
					{ pipe: '$language' },
					{ text: ' ${}' }
				]
			}
		]);
		expect(isPipeRef('q_1')).toBe(true);
		expect(isPipeRef('$position.index')).toBe(true);
		expect(isPipeRef('1q')).toBe(false);
		expect(isPipeRef('a b')).toBe(false);
		expect(isPipeRef('$')).toBe(false);
	});

	it('asRich tolerates anything', () => {
		expect(asRich(undefined).blocks).toEqual([]);
		expect(asRich(42).blocks).toEqual([]);
		expect(asRich({ type: 'rich', blocks: 'nope' }).blocks).toEqual([]);
		expect(asRich('x').blocks).toEqual([{ type: 'p', content: [{ text: 'x' }] }]);
	});
});

describe('normal form (what a field commits, RT-D3)', () => {
	it('is a plain string when there is no formatting, pipes written back, breaks as newlines', () => {
		expect(normalForm(plainToRich('Hi ${name}\nthere'))).toBe('Hi ${name}\nthere');
		expect(normalForm({ type: 'rich', blocks: [{ type: 'p', content: [] }] })).toBe('');
		expect(normalForm({ type: 'rich', blocks: [] })).toBe('');
		expect(normalForm(undefined)).toBe('');
		expect(normalForm('as is')).toBe('as is');
	});

	it('keeps the tree when any formatting is present, canonicalised', () => {
		const bold: RichText = { type: 'rich', blocks: [{ type: 'p', content: [{ text: 'a', marks: ['b'] }, { text: '' }] }] };
		expect(normalForm(bold)).toEqual({ type: 'rich', blocks: [{ type: 'p', content: [{ text: 'a', marks: ['b'] }] }] });
		const two: RichText = { type: 'rich', blocks: [{ type: 'p', content: [{ text: 'a' }] }, { type: 'p', content: [{ text: 'b' }] }] };
		expect(normalForm(two)).toEqual(two);
		const link: RichText = { type: 'rich', blocks: [{ type: 'p', content: [{ text: 'a', href: 'https://x.org' }] }] };
		expect(normalForm(link)).toEqual(link);
	});

	it('sameValue compares after normalising', () => {
		expect(sameValue('a ${b}', plainToRich('a ${b}'))).toBe(true);
		expect(sameValue('', { type: 'rich', blocks: [] })).toBe(true);
		expect(sameValue('a', 'b')).toBe(false);
	});
});

describe('lowering to a level', () => {
	const tree: RichText = {
		type: 'rich',
		blocks: [
			{ type: 'h', level: 2, content: [{ text: 'Title' }] },
			{ type: 'ul', items: [[{ text: 'one' }], [{ text: 'two', marks: ['b'] }]] },
			{ type: 'p', content: [{ text: 'end' }] }
		]
	};

	it('stem: headings become paragraphs, lists stay', () => {
		const doc = toDoc(tree, 'stem');
		expect(doc.content!.map((b) => b.type)).toEqual(['paragraph', 'bulletList', 'paragraph']);
	});

	it('inline: everything becomes one paragraph with breaks', () => {
		const doc = toDoc(tree, 'inline');
		expect(doc.content).toHaveLength(1);
		expect(fromDoc(doc).blocks).toEqual([
			{
				type: 'p',
				content: [{ text: 'Title' }, { br: true }, { text: 'one' }, { br: true }, { text: 'two', marks: ['b'] }, { br: true }, { text: 'end' }]
			}
		]);
	});

	it('block keeps everything and an empty value is one empty paragraph', () => {
		expect(toDoc(tree, 'block').content!.map((b) => b.type)).toEqual(['heading', 'bulletList', 'paragraph']);
		expect(toDoc('', 'block')).toEqual({ type: 'doc', content: [{ type: 'paragraph' }] });
	});

	it('fromDoc tolerates unknown nodes and malformed input', () => {
		const doc: PmNode = {
			type: 'doc',
			content: [
				{ type: 'mystery', content: [{ type: 'text', text: 'kept' }] },
				{ type: 'heading', attrs: { level: 9 }, content: [{ type: 'text', text: 'h' }] },
				{ type: 'bulletList', content: [{ type: 'listItem', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'a' }] }, { type: 'paragraph', content: [{ type: 'text', text: 'b' }] }] }] },
				{ type: 'paragraph', content: [{ type: 'pipe', attrs: { id: '' } }, { type: 'text', text: 'x', marks: [{ type: 'weird' }] }] }
			]
		};
		expect(fromDoc(doc).blocks).toEqual([
			{ type: 'p', content: [{ text: 'kept' }] },
			{ type: 'h', level: 1, content: [{ text: 'h' }] },
			{ type: 'ul', items: [[{ text: 'a' }, { br: true }, { text: 'b' }]] },
			{ type: 'p', content: [{ text: 'x' }] }
		]);
		expect(fromDoc({ type: 'doc' }).blocks).toEqual([{ type: 'p', content: [] }]);
	});
});

describe('inspection', () => {
	it('lists pipes and tells empty values', () => {
		expect(pipesOf('a ${x} ${y} ${x}')).toEqual(['x', 'y', 'x']);
		expect(pipesOf({ type: 'rich', blocks: [{ type: 'ol', items: [[{ pipe: 'z' }]] }] })).toEqual(['z']);
		expect(isEmptyValue('  ')).toBe(true);
		expect(isEmptyValue('${x}')).toBe(false);
		expect(isEmptyValue({ type: 'rich', blocks: [{ type: 'p', content: [{ br: true }] }] })).toBe(true);
		expect(isEmptyValue(undefined)).toBe(true);
	});
});
