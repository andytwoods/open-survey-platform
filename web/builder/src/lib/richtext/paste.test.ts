// @vitest-environment jsdom
import { generateJSON, getSchema } from '@tiptap/core';
import { Fragment, Slice, type Schema } from '@tiptap/pm/model';
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { fromDoc, type PmNode } from './convert';
import type { Level } from './levels';
import { cleanPastedHtml, describeReport, emptyReport, type PasteReport } from './paste';
import { pasteTransform, schemaExtensions } from './tiptap';

// Paste cleaning (planning/rich-text.md §6) end to end: hand-written samples in the style
// of Word, Google Docs, a web page and Outlook (fixtures/paste/*.html) go through the
// cleaning pass, then through the level's ProseMirror schema (as a real paste does), then
// through the slice pass (pipes to chips, inline flattening); the result must be the tree in
// the fixture's .json, and the report must say what was lost.

const DIR = join(dirname(fileURLToPath(import.meta.url)), 'fixtures', 'paste');

interface Fixture {
	level: Level;
	report: PasteReport;
	status: string | null;
	blocks: unknown[];
}

/** What the editor would hold after pasting `html` into an empty field of `level`. */
function paste(html: string, level: Level, pipes = true): { tree: ReturnType<typeof fromDoc>; report: PasteReport } {
	const { html: cleaned, report } = cleanPastedHtml(html, level);
	const extensions = schemaExtensions(level);
	const schema: Schema = getSchema(extensions);
	const json = generateJSON(cleaned, extensions) as PmNode;
	const doc = schema.nodeFromJSON(json);
	const slice = pasteTransform(new Slice(doc.content, 0, 0), schema, level, pipes);
	// An inline slice (the flattened one-line case) lands inside the field's paragraph.
	const content = slice.content.firstChild?.isInline ? Fragment.from(schema.nodes.paragraph!.create(null, slice.content)) : slice.content;
	return { tree: fromDoc(doc.copy(content).toJSON() as PmNode), report };
}

describe('paste fixtures', () => {
	const names = readdirSync(DIR)
		.filter((f) => f.endsWith('.html'))
		.map((f) => f.slice(0, -5));
	expect(names.length).toBeGreaterThan(0);

	for (const name of names) {
		it(`${name}.html pastes as ${name}.json`, () => {
			const html = readFileSync(join(DIR, `${name}.html`), 'utf8');
			const expected = JSON.parse(readFileSync(join(DIR, `${name}.json`), 'utf8')) as Fixture;
			const { tree, report } = paste(html, expected.level);
			expect(tree.blocks).toEqual(expected.blocks);
			expect(report).toEqual(expected.report);
			expect(describeReport(report)).toBe(expected.status);
		});
	}
});

describe('paste rules', () => {
	it('a clean paste reports nothing and shows no status', () => {
		const { report } = paste('<p>Plain <strong>bold</strong></p>', 'stem');
		expect(report).toEqual(emptyReport());
		expect(describeReport(report)).toBeNull();
	});

	it('scripts and styles never reach the document', () => {
		const { tree } = paste('<p>x</p><script>document.title = "pwned"</script><style>p{color:red}</style>', 'block');
		expect(tree.blocks).toEqual([{ type: 'p', content: [{ text: 'x' }] }]);
		expect(document.title).not.toBe('pwned');
	});

	it('leaves ${id} as text where pipes are not allowed (consent)', () => {
		const { tree } = paste('<p>Hello ${name}</p>', 'block', false);
		expect(tree.blocks).toEqual([{ type: 'p', content: [{ text: 'Hello ${name}' }] }]);
	});

	it('plain-text lines paste as paragraphs in a stem and as breaks in an inline field', () => {
		// ProseMirror's own text parser makes a paragraph per line; the slice pass flattens.
		const html = '<p>one</p><p>two ${x}</p>';
		expect(paste(html, 'stem').tree.blocks).toEqual([
			{ type: 'p', content: [{ text: 'one' }] },
			{ type: 'p', content: [{ text: 'two ' }, { pipe: 'x' }] }
		]);
		expect(paste(html, 'inline').tree.blocks).toEqual([{ type: 'p', content: [{ text: 'one' }, { br: true }, { text: 'two ' }, { pipe: 'x' }] }]);
	});

	it('a heading in a stem is lowered to a paragraph; a list in an inline field to one line', () => {
		expect(paste('<h1>Big</h1>', 'stem').tree.blocks).toEqual([{ type: 'p', content: [{ text: 'Big' }] }]);
		const inline = paste('<ul><li>a</li><li>b</li></ul>', 'inline');
		expect(inline.tree.blocks).toEqual([{ type: 'p', content: [{ text: 'a' }, { br: true }, { text: 'b' }] }]);
		expect(inline.report.merged).toBe(1);
	});

	it('describes what was removed in plain words', () => {
		expect(describeReport({ ...emptyReport(), images: 2, styles: true })).toBe('Formatting simplified: colours and fonts and 2 images removed');
		expect(describeReport({ ...emptyReport(), links: 1 })).toBe('Formatting simplified: 1 link removed: not https');
		expect(describeReport({ ...emptyReport(), underline: 3 })).toBe('Formatting simplified: underline removed');
	});
});
