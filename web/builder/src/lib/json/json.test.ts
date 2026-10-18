import { describe, expect, it } from 'vitest';
import { SPEC_VERSION } from '@osp/spec';
import { memoryTransport } from '../sync/memory-transport';
import { SurveyStore } from '../sync/survey-store.svelte';
import type { SurveyDoc } from '../sync/transport';
import { JsonDraft, jsonEqual, placeDiagnostics } from './json-draft.svelte';
import { formatJson, locate, parseJson, positionAt } from './source';

describe('parseJson', () => {
	it('parses valid JSON and maps pointers to spans', () => {
		const text = '{\n  "a": [1, {"b~/c": "x"}],\n  "n": null\n}';
		const r = parseJson(text);
		expect(r.ok).toBe(true);
		if (!r.ok) return;
		expect(r.value).toEqual({ a: [1, { 'b~/c': 'x' }], n: null });
		const at = (p: string) => {
			const s = r.spans.get(p)!;
			return text.slice(s.from, s.to);
		};
		expect(at('')).toBe(text);
		expect(at('/a/0')).toBe('1');
		expect(at('/a/1/b~0~1c')).toBe('"b~/c": "x"');
		expect(at('/n')).toBe('"n": null');
	});

	it('reports the first syntax error with line and column, never throws', () => {
		const bad = '{\n  "a": 1,\n  "b": }\n';
		const r = parseJson(bad);
		expect(r.ok).toBe(false);
		if (r.ok) return;
		expect(r.position).toEqual({ line: 3, col: 8 });
		expect(r.message).toMatch(/Expected a value/);
		for (const t of ['', '{', '{"a":1,}', '[1 2]', '"\\x"', '{"a":1} x', '-', 'tru', '"a\nb"']) {
			expect(parseJson(t).ok).toBe(false);
		}
		expect(parseJson('['.repeat(5000)).ok).toBe(false);
		for (const t of ['0', '-1.5e3', '"\\u00e9"', 'true', ' [ ] ', '{"a":{}}']) expect(parseJson(t).ok).toBe(true);
	});

	it('locates a pointer, or its nearest ancestor', () => {
		const text = formatJson({ blocks: [{ id: 'b1', pages: [] }] });
		const r = parseJson(text);
		if (!r.ok) throw new Error('bad');
		expect(text.slice(locate(r.spans, '/blocks/0/id')!.from)).toMatch(/^"id": "b1"/);
		expect(locate(r.spans, '/blocks/0/missing/deep')).toEqual(r.spans.get('/blocks/0'));
		expect(positionAt('ab\ncd', 4)).toEqual({ line: 2, col: 2 });
	});

	it('compares JSON structurally', () => {
		expect(jsonEqual({ a: [1, { b: 2 }], c: null }, { c: null, a: [1, { b: 2 }] })).toBe(true);
		expect(jsonEqual({ a: 1 }, { a: 1, b: undefined })).toBe(false);
		expect(jsonEqual([1], { 0: 1 })).toBe(false);
	});

	it('places server diagnostics by pointer', () => {
		const text = formatJson({ a: { b: 1 } });
		const [d, root] = placeDiagnostics(text, [
			{ severity: 'error', code: 'x', message: 'm', pointer: '/a/b' },
			{ severity: 'error', code: 'y', message: 'n', pointer: '' }
		]);
		expect(d.position).toEqual({ line: 3, col: 5 });
		expect(root.position).toEqual({ line: 1, col: 1 });
		expect(placeDiagnostics('{', [{ severity: 'error', code: 'x', message: 'm', pointer: '/a' }])[0].span).toBeNull();
	});
});


const doc = (): SurveyDoc => ({
	specVersion: SPEC_VERSION,
	id: 'survey',
	metadata: { title: { en: 'T' }, languages: ['en'], defaultLanguage: 'en' },
	blocks: [{ id: 'b1', pages: [{ id: 'p1', items: [{ id: 'intro', type: 'note', label: { en: '' } }] }] }],
	flow: [{ type: 'block', id: 'n1', block: 'b1' }]
});

const titled = (s: SurveyDoc | null, en: string): SurveyDoc => ({
	...(s as SurveyDoc),
	metadata: { ...((s as SurveyDoc).metadata as object), title: { en } }
});

async function setup() {
	const server = memoryTransport({ id: 's', title: 'T', survey: doc(), revision: 1 });
	const store = new SurveyStore({ transport: server, sleep: async () => {} });
	await store.load('s');
	/** Someone else saves a new title. */
	const elsewhere = (en: string) => {
		server.draft = { ...server.draft, survey: titled(server.draft.survey, en), revision: server.draft.revision + 1 };
	};
	return { server, store, draft: new JsonDraft(store), elsewhere };
}

describe('JsonDraft', () => {
	it('invalid JSON is never sent and the draft is untouched', async () => {
		const { server, store, draft } = await setup();
		const before = structuredClone(store.survey);
		draft.edit('{"metadata": ');
		expect(await draft.apply()).toBe('invalid');
		expect(draft.syntaxError?.position.line).toBe(1);
		draft.edit('[1, 2]');
		expect(await draft.apply()).toBe('invalid');
		await store.settled();
		expect(server.saves).toHaveLength(0);
		expect(store.survey).toEqual(before);
		expect(store.revision).toBe(1);
		expect(draft.dirty).toBe(true);
	});

	it('a rejected Apply keeps the text, places diagnostics and leaves the draft', async () => {
		const { server, store, draft } = await setup();
		const text = formatJson({ ...store.survey, blocks: 'not a list' });
		draft.edit(text);
		expect(await draft.apply()).toBe('rejected');
		await store.settled();
		expect(server.saves).toHaveLength(0);
		expect(store.survey?.blocks).toEqual(doc().blocks);
		expect(draft.text).toBe(text);
		expect(draft.current.length).toBeGreaterThan(0);
		expect(draft.current.some((d) => (d.position?.line ?? 0) > 1)).toBe(true);
		draft.edit(text + ' ');
		expect(draft.current).toHaveLength(0); // the diagnostics described the old text
	});

	it('a valid Apply is one replace_survey, saved, and re-syncs', async () => {
		const { server, store, draft } = await setup();
		draft.edit(formatJson(titled(store.survey, 'New')));
		expect(await draft.apply()).toBe('applied');
		expect(draft.dirty).toBe(false);
		await store.settled();
		expect(server.saves.map((s) => s.ops.map((o) => o.op))).toEqual([['replace_survey']]);
		expect(store.revision).toBe(2);
		expect(server.draft.survey).toEqual(titled(doc(), 'New'));
		expect(draft.baseRevision).toBe(2);
	});

	it('unchanged JSON (even reformatted) sends nothing', async () => {
		const { server, store, draft } = await setup();
		draft.edit(JSON.stringify(store.survey));
		expect(await draft.apply()).toBe('unchanged');
		await store.settled();
		expect(server.saves).toHaveLength(0);
		expect(draft.dirty).toBe(false);
	});

	it('warns when the survey changed on the server while editing; revert discards', async () => {
		const { server, store, draft, elsewhere } = await setup();
		draft.edit(formatJson(titled(store.survey, 'Mine')));
		elsewhere('Other');
		await store.reload();
		expect(draft.stale).toBe(true);
		draft.sync(); // local edits are kept
		expect(draft.text).toContain('"Mine"');
		expect(await draft.apply()).toBe('stale');
		expect(server.saves).toHaveLength(0);
		draft.revert();
		expect(draft.dirty).toBe(false);
		expect(draft.stale).toBe(false);
		expect(draft.text).toContain('"Other"');
	});

	it('an edit made elsewhere in the builder also makes the JSON stale', async () => {
		const { store, draft } = await setup();
		draft.edit(formatJson(titled(store.survey, 'Mine')));
		await store.submit([{ op: 'set_property', params: { target: 'p1', property: 'title', value: { en: 'P' } } }]);
		expect(draft.stale).toBe(true);
	});

	it('Apply anyway overwrites a newer revision', async () => {
		const { server, store, draft, elsewhere } = await setup();
		draft.edit(formatJson(titled(store.survey, 'Mine')));
		elsewhere('Other');
		await store.reload();
		expect(await draft.apply({ force: true })).toBe('applied');
		await store.settled();
		expect(server.draft.survey).toEqual(titled(doc(), 'Mine'));
	});

	it('follows the store while there are no local edits', async () => {
		const { store, draft, elsewhere } = await setup();
		elsewhere('Followed');
		await store.reload();
		draft.sync();
		expect(draft.text).toContain('"Followed"');
		expect(draft.baseRevision).toBe(2);
	});
});
