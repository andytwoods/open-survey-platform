import { describe, expect, it } from 'vitest';
import { SurveyStore } from '../sync/survey-store.svelte';
import { failure, type EditResult, type Invocation, type Result, type SurveyDoc, type SurveyTransport } from '../sync/transport';
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

/** A server that accepts `replace_survey` unless the survey has `"bad": true` (422). */
class Server implements SurveyTransport {
	doc: SurveyDoc = { metadata: { title: { en: 'T' } }, blocks: [] };
	revision = 1;
	ops: Invocation[][] = [];
	async load(): Promise<Result<{ id: string; title: string; revision: number; survey: SurveyDoc }>> {
		return { kind: 'ok', data: { id: 's', title: 'T', revision: this.revision, survey: structuredClone(this.doc) } };
	}
	async applyOps(_id: string, body: { ops: Invocation[]; baseRevision: number }): Promise<Result<EditResult>> {
		this.ops.push(body.ops);
		if (body.baseRevision !== this.revision) return failure(409, { currentRevision: this.revision });
		const survey = body.ops[0].params!.survey as SurveyDoc;
		if (survey.bad) {
			return failure(422, {
				message: 'Rejected.',
				diagnostics: [{ severity: 'error', code: 'spec.bad', message: 'Not allowed', pointer: '/bad' }]
			});
		}
		this.doc = structuredClone(survey);
		this.revision++;
		return {
			kind: 'ok',
			data: {
				revision: this.revision,
				patch: [{ op: 'replace', path: '', value: survey }],
				diagnostics: [],
				transactionId: `t${this.revision}`
			}
		};
	}
	async undo(): Promise<Result<EditResult>> {
		return failure(500, {});
	}
	async redo(): Promise<Result<EditResult>> {
		return failure(500, {});
	}
}

async function setup() {
	const server = new Server();
	const store = new SurveyStore({ transport: server, sleep: async () => {} });
	await store.load('s');
	return { server, store, draft: new JsonDraft(store) };
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
		expect(server.ops).toHaveLength(0);
		expect(store.survey).toEqual(before);
		expect(store.revision).toBe(1);
		expect(draft.dirty).toBe(true);
	});

	it('a rejected Apply keeps the text, places diagnostics and leaves the draft', async () => {
		const { store, draft } = await setup();
		const text = formatJson({ ...store.survey, bad: true });
		draft.edit(text);
		expect(await draft.apply()).toBe('rejected');
		expect(store.revision).toBe(1);
		expect(store.survey).not.toHaveProperty('bad');
		expect(draft.text).toBe(text);
		expect(draft.current).toHaveLength(1);
		expect(draft.current[0].position?.line).toBeGreaterThan(1);
		draft.edit(text + ' ');
		expect(draft.current).toHaveLength(0); // the diagnostics described the old text
	});

	it('a valid Apply sends one replace_survey and re-syncs', async () => {
		const { server, store, draft } = await setup();
		draft.edit(formatJson({ ...store.survey, metadata: { title: { en: 'New' } } }));
		expect(await draft.apply()).toBe('applied');
		expect(server.ops).toEqual([[{ op: 'replace_survey', params: { survey: expect.any(Object) } }]]);
		expect(store.revision).toBe(2);
		expect((store.survey as { metadata: unknown }).metadata).toEqual({ title: { en: 'New' } });
		expect(draft.dirty).toBe(false);
		expect(draft.baseRevision).toBe(2);
	});

	it('unchanged JSON (even reformatted) sends nothing', async () => {
		const { server, store, draft } = await setup();
		draft.edit(JSON.stringify(store.survey));
		expect(await draft.apply()).toBe('unchanged');
		expect(server.ops).toHaveLength(0);
		expect(draft.dirty).toBe(false);
	});

	it('warns when the survey changed on the server while editing; revert discards', async () => {
		const { server, store, draft } = await setup();
		draft.edit(formatJson({ ...store.survey, x: 1 }));
		server.doc = { ...server.doc, other: true };
		server.revision = 5;
		await store.reload();
		expect(draft.stale).toBe(true);
		draft.sync(); // local edits are kept
		expect(draft.text).toContain('"x": 1');
		expect(await draft.apply()).toBe('stale');
		expect(server.ops).toHaveLength(0);
		draft.revert();
		expect(draft.dirty).toBe(false);
		expect(draft.stale).toBe(false);
		expect(draft.text).toContain('"other": true');
	});

	it('Apply anyway overwrites a newer revision', async () => {
		const { server, store, draft } = await setup();
		draft.edit(formatJson({ ...store.survey, x: 1 }));
		server.revision = 4;
		await store.reload();
		expect(await draft.apply({ force: true })).toBe('applied');
		expect(server.doc).toHaveProperty('x', 1);
	});

	it('follows the store while there are no local edits', async () => {
		const { server, store, draft } = await setup();
		server.doc = { ...server.doc, y: 2 };
		server.revision = 3;
		await store.reload();
		draft.sync();
		expect(draft.text).toContain('"y": 2');
		expect(draft.baseRevision).toBe(3);
	});
});
