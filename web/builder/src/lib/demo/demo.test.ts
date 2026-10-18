import { describe, expect, it } from 'vitest';
import { createDemoBackend, DEMO_UNAVAILABLE_CODE, type DemoData } from './backend';
import { applyTransaction, type Json } from '@osp/ops';
import { previewPlan } from '../preview/compile';
import { SurveyStore } from '../sync/survey-store.svelte';
import { MemorySurveyTransport } from './memory-transport';
import { DEMO_SURVEY_ID, demoDraft, demoStudy } from './study';

type Doc = { blocks: { pages: { items: { id: string; required?: boolean; showIf?: unknown }[] }[] }[] };
const question = (survey: unknown, id: string) =>
	(survey as Doc).blocks.flatMap((b) => b.pages.flatMap((p) => p.items)).find((q) => q.id === id)!;

const ok = <T>(r: { kind: string; data?: T }): T => {
	expect(r.kind).toBe('ok');
	return r.data as T;
};

describe('the demo study', () => {
	it('validates and compiles in the browser, with its own theme', () => {
		const t = new MemorySurveyTransport(demoDraft());
		expect(t.diagnostics()).toEqual([]);
		const c = previewPlan(demoStudy(), null);
		expect(c.diagnostics).toEqual([]);
		expect(c.plan?.languages).toEqual(['en', 'de']);
		expect((c.plan as unknown as { theme: { preset: string } }).theme.preset).toBe('warm');
		expect(c.plan?.survey.seedVersion).toBe('draft');
		expect(c.conditions['items.how_take.showIf']).toBe('cups > 0');
		expect(c.conditions['flow.br_age.if']).toBe('age < 18');
	});
});

describe('MemorySurveyTransport', () => {
	const edit = { op: 'set_property', params: { target: 'age', property: 'required', value: false } };
	/** The PUT …/draft body the builder sends for `ops` on the draft at `revision`. */
	const save = (survey: unknown, revision: number, transactionId: string) => {
		const tx = applyTransaction({ survey: survey as Json, revision }, [edit], revision);
		return { baseRevision: revision, patch: tx.patch as never, ops: [edit], transactionId };
	};

	it('takes a JSON Patch draft save (planning/client-edits.md §3), with replay', async () => {
		const changes: number[] = [];
		const t = new MemorySurveyTransport(demoDraft(), { onChange: (d) => changes.push(d.revision) });
		const loaded = ok(await t.load(DEMO_SURVEY_ID));
		expect(loaded.revision).toBe(1);
		expect(question(loaded.survey, 'age').required).toBe(true);
		const body = save(loaded.survey, 1, 'txn1');
		const r = ok(await t.saveDraft(DEMO_SURVEY_ID, body));
		expect(r).toMatchObject({ revision: 2, transactionId: 'txn1', diagnostics: [] });
		expect(question(t.draft.survey, 'age').required).toBe(false);
		// A retried request with the same id is not applied twice.
		expect(ok(await t.saveDraft(DEMO_SURVEY_ID, body)).replayed).toBe(true);
		expect(t.draft.revision).toBe(2);
		expect(changes).toEqual([2]);
	});

	it('refuses a stale base, a patch that does not apply, an invalid result and an unknown survey', async () => {
		const t = new MemorySurveyTransport(demoDraft());
		const req = (patch: unknown[], baseRevision = 1) => ({ baseRevision, patch: patch as never, ops: [], transactionId: 'x' });
		expect(await t.saveDraft(DEMO_SURVEY_ID, req([], 0))).toMatchObject({ kind: 'conflict', currentRevision: 1 });
		expect((await t.saveDraft(DEMO_SURVEY_ID, req([{ op: 'remove', path: '/nope' }]))).kind).toBe('rejected');
		expect((await t.saveDraft(DEMO_SURVEY_ID, req([{ op: 'replace', path: '/blocks', value: 3 }]))).kind).toBe('rejected');
		expect((await t.load('other')).kind).toBe('error');
		expect((await t.saveDraft('other', req([]))).kind).toBe('error');
		expect(t.draft.revision).toBe(1);
		expect(t.draft.survey).toEqual(demoStudy());
	});

	it('backs the builder store: local edits, undo and redo are saved as drafts', async () => {
		const t = new MemorySurveyTransport(demoDraft());
		const store = new SurveyStore({ transport: t });
		await store.load(DEMO_SURVEY_ID);
		await store.submit([edit]);
		await store.settled();
		expect(question(t.draft.survey, 'age').required).toBe(false);
		await store.undo();
		await store.settled();
		expect(t.draft.survey).toEqual(demoStudy());
		await store.redo();
		await store.settled();
		expect(t.draft.revision).toBe(4);
		expect(question(t.draft.survey, 'age').required).toBe(false);
	});
});

describe('createDemoBackend', () => {
	const data: DemoData = {
		version: 1,
		get: { '/api/health': { status: 'ok' }, '/api/me': { userId: 'u', memberships: [{ tenantId: 'lab' }] } },
		bankList: {
			items: [
				{ id: 'gad2', title: 'Generalized Anxiety Disorder-2', kind: 'block', tags: ['anxiety'] },
				{ id: 'phq2', title: 'Patient Health Questionnaire-2', kind: 'block', tags: ['depression'] }
			]
		},
		bankItems: { gad2: { id: 'gad2' } },
		presets: {}
	};
	const backend = () => createDemoBackend({ data, transport: new MemorySurveyTransport(demoDraft()) });
	const call = async (b: ReturnType<typeof backend>, method: string, path: string, body?: unknown) => {
		const res = await b(
			new Request(`http://demo.test${path}`, { method, body: body === undefined ? undefined : JSON.stringify(body) })
		);
		return { status: res.status, body: res.status === 204 ? null : await res.json() };
	};

	it('answers the survey, draft saves and metadata in the page', async () => {
		const b = backend();
		expect(await call(b, 'GET', '/api/health')).toEqual({ status: 200, body: { status: 'ok' } });
		const list = await call(b, 'GET', '/api/surveys');
		expect(list.body).toEqual([expect.objectContaining({ id: DEMO_SURVEY_ID, tenantId: 'lab', title: 'Coffee and focus' })]);
		const s = await call(b, 'GET', `/api/surveys/${DEMO_SURVEY_ID}`);
		expect(s.body).toMatchObject({ revision: 1, diagnostics: [], publishedVersions: 0 });
		const draft = s.body.survey;
		const tx = applyTransaction({ survey: draft, revision: 1 }, [{ op: 'set_property', params: { target: 'age', property: 'required', value: false } }], 1);
		const put = { baseRevision: 1, patch: tx.patch, ops: [{ op: 'set_property', params: {} }], transactionId: 't1' };
		const e = await call(b, 'PUT', `/api/surveys/${DEMO_SURVEY_ID}/draft`, put);
		expect(e).toMatchObject({ status: 200, body: { revision: 2, transactionId: 't1', diagnostics: [] } });
		expect((await call(b, 'PUT', `/api/surveys/${DEMO_SURVEY_ID}/draft`, { ...put, transactionId: 't2' })).status).toBe(409);
		const bad = await call(b, 'PUT', `/api/surveys/${DEMO_SURVEY_ID}/draft`, { ...put, baseRevision: 2, patch: [{ op: 'remove', path: '/x' }], transactionId: 't3' });
		expect(bad).toMatchObject({ status: 422, body: { diagnostics: [{ code: 'op.patch' }] } });
		const bank = await call(b, 'GET', '/api/bank?q=anxiety');
		expect(bank.body.items.map((i: { id: string }) => i.id)).toEqual(['gad2']);
		expect(bank.body).toMatchObject({ total: 1, canManage: false, canShare: false });
		expect((await call(b, 'GET', '/api/bank/gad2')).status).toBe(200);
		expect((await call(b, 'GET', '/api/bank/nope')).status).toBe(404);
		expect((await call(b, 'GET', '/api/surveys/other')).status).toBe(404);
	});

	it('says "not available in the demo" for what needs a server', async () => {
		const b = backend();
		for (const [method, path] of [
			['POST', `/api/surveys/${DEMO_SURVEY_ID}/publish`],
			// The builder applies edits, undo and redo, and compiles Preview, itself (CE5).
			['POST', `/api/surveys/${DEMO_SURVEY_ID}/ops`],
			['POST', `/api/surveys/${DEMO_SURVEY_ID}/preview-plan`],
			['POST', '/api/meta/expressions/parse'],
			['POST', `/api/surveys/${DEMO_SURVEY_ID}/results/query`],
			['POST', '/api/surveys/import'],
			['POST', '/api/surveys'],
			['POST', '/api/bank'],
			['POST', '/api/themes'],
			['GET', `/api/surveys/${DEMO_SURVEY_ID}/export-check?target=xlsform`]
		]) {
			const r = await call(b, method, path, method === 'POST' ? {} : undefined);
			expect(r.status, path).toBe(501);
			expect(r.body.code).toBe(DEMO_UNAVAILABLE_CODE);
			expect(r.body.message).toMatch(/Not available in the demo/);
		}
	});
});
