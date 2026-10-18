import { describe, expect, it } from 'vitest';
import { createDemoBackend, DEMO_UNAVAILABLE_CODE, type DemoData } from './backend';
import { parseExpression, printExpression, references } from './expressions';
import { MemorySurveyTransport } from './memory-transport';
import { compileDraft } from './plan';
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
		const c = compileDraft(demoStudy());
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

	it('applies ops with @osp/ops: patch, revision, undo, redo', async () => {
		const changes: number[] = [];
		const t = new MemorySurveyTransport(demoDraft(), { onChange: (d) => changes.push(d.revision) });
		const loaded = ok(await t.load(DEMO_SURVEY_ID));
		expect(loaded.revision).toBe(1);
		expect(question(loaded.survey, 'age').required).toBe(true);

		const r = ok(await t.applyOps(DEMO_SURVEY_ID, { ops: [edit], baseRevision: 1, transactionId: 'txn1' }));
		expect(r.revision).toBe(2);
		expect(r.transactionId).toBe('txn1');
		expect(r.patch.length).toBeGreaterThan(0);
		expect(question(t.draft.survey, 'age').required).toBe(false);

		// A retried request with the same id is not applied twice.
		const again = ok(await t.applyOps(DEMO_SURVEY_ID, { ops: [edit], baseRevision: 1, transactionId: 'txn1' }));
		expect(again.replayed).toBe(true);
		expect(t.draft.revision).toBe(2);

		const u = ok(await t.undo(DEMO_SURVEY_ID, { transactionId: 'txn1', baseRevision: 2 }));
		expect(u.transactionId).toMatch(/^u:/);
		expect(question(t.draft.survey, 'age').required).toBe(true);
		expect(t.draft.survey).toEqual(demoStudy());

		// An undo can't be undone (redo it), and only an undo can be redone.
		expect((await t.undo(DEMO_SURVEY_ID, { transactionId: u.transactionId!, baseRevision: 3 })).kind).toBe('rejected');
		expect((await t.redo(DEMO_SURVEY_ID, { transactionId: 'txn1', baseRevision: 3 })).kind).toBe('rejected');
		const rd = ok(await t.redo(DEMO_SURVEY_ID, { transactionId: u.transactionId!, baseRevision: 3 }));
		expect(rd.transactionId).toMatch(/^r:/);
		expect(question(t.draft.survey, 'age').required).toBe(false);
		expect(changes).toEqual([2, 3, 4]);
	});

	it('refuses a stale base, a bad op and an unknown survey without changing anything', async () => {
		const t = new MemorySurveyTransport(demoDraft());
		const stale = await t.applyOps(DEMO_SURVEY_ID, { ops: [edit], baseRevision: 0, transactionId: 'a' });
		expect(stale).toMatchObject({ kind: 'conflict', currentRevision: 1 });
		const bad = await t.applyOps(DEMO_SURVEY_ID, {
			ops: [{ op: 'set_property', params: { target: 'nope', property: 'required', value: true } }],
			baseRevision: 1,
			transactionId: 'b'
		});
		expect(bad.kind).toBe('rejected');
		expect((await t.applyOps(DEMO_SURVEY_ID, { ops: [{ op: 'no_such_op' }], baseRevision: 1, transactionId: 'c' })).kind).toBe('rejected');
		expect((await t.load('other')).kind).toBe('error');
		expect((await t.undo(DEMO_SURVEY_ID, { transactionId: 'never', baseRevision: 1 })).kind).toBe('error');
		expect(t.draft.revision).toBe(1);
		expect(t.draft.survey).toEqual(demoStudy());
	});

	it('takes a JSON Patch draft save (planning/client-edits.md §3)', () => {
		const t = new MemorySurveyTransport(demoDraft());
		const r = t.putDraft(DEMO_SURVEY_ID, {
			baseRevision: 1,
			patch: [{ op: 'replace', path: '/metadata/license', value: 'CC-BY-4.0' }]
		});
		expect(ok(r).revision).toBe(2);
		expect(t.putDraft(DEMO_SURVEY_ID, { baseRevision: 1, patch: [] }).kind).toBe('conflict');
		expect(t.putDraft(DEMO_SURVEY_ID, { baseRevision: 2, patch: [{ op: 'remove', path: '/nope' }] }).kind).toBe('rejected');
		expect(t.putDraft(DEMO_SURVEY_ID, { baseRevision: 2, patch: [{ op: 'replace', path: '/blocks', value: 3 }] }).kind).toBe(
			'rejected'
		);
		expect(t.draft.revision).toBe(2);
	});
});

describe('expressions', () => {
	it('parses, checks in place and prints', () => {
		const p = parseExpression('cups > 2', demoStudy(), 'how_take', null);
		expect(p.ok).toBe(true);
		expect(p.text).toBe('cups > 2');
		expect(p.references).toEqual(['cups']);
		expect(p.diagnostics).toEqual([]);
		const fwd = parseExpression('tips == "x"', demoStudy(), 'age', null);
		expect(fwd.diagnostics.map((d) => d.code)).toContain('ref.forward');
		const bad = parseExpression('cups >', null);
		expect(bad.ok).toBe(false);
		expect(bad.diagnostics[0].start).not.toBeNull();
		expect(printExpression(p.ast).text).toBe('cups > 2');
		expect(printExpression({ kind: 'nonsense' }).text).toBeNull();
		expect(references({ kind: 'and', args: [{ kind: 'ref', id: 'a' }, { kind: 'ref', id: 'a' }] })).toEqual(['a']);
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

	it('answers the survey, edits, preview and metadata in the page', async () => {
		const b = backend();
		expect(await call(b, 'GET', '/api/health')).toEqual({ status: 200, body: { status: 'ok' } });
		const list = await call(b, 'GET', '/api/surveys');
		expect(list.body).toEqual([expect.objectContaining({ id: DEMO_SURVEY_ID, tenantId: 'lab', title: 'Coffee and focus' })]);
		const s = await call(b, 'GET', `/api/surveys/${DEMO_SURVEY_ID}`);
		expect(s.body).toMatchObject({ revision: 1, diagnostics: [], publishedVersions: 0 });
		const e = await call(b, 'POST', `/api/surveys/${DEMO_SURVEY_ID}/ops`, {
			ops: [{ op: 'set_property', params: { target: 'age', property: 'required', value: false } }],
			baseRevision: 1,
			transactionId: 't1'
		});
		expect(e).toMatchObject({ status: 200, body: { revision: 2, transactionId: 't1' } });
		expect((await call(b, 'POST', `/api/surveys/${DEMO_SURVEY_ID}/ops`, { ops: [], baseRevision: 0, transactionId: 't2' })).status).toBe(
			409
		);
		const u = await call(b, 'POST', `/api/surveys/${DEMO_SURVEY_ID}/undo`, { transactionId: 't1', baseRevision: 2 });
		expect(u).toMatchObject({ status: 200, body: { revision: 3 } });
		const pv = await call(b, 'POST', `/api/surveys/${DEMO_SURVEY_ID}/preview-plan`);
		expect(pv.body).toMatchObject({ surveyId: DEMO_SURVEY_ID, revision: 3, diagnostics: [] });
		expect(pv.body.plan.checksum).toMatch(/^sha256:/);
		const parsed = await call(b, 'POST', '/api/meta/expressions/parse', { text: 'age >= 18', surveyId: DEMO_SURVEY_ID, target: 'drinks_coffee' });
		expect(parsed.body).toMatchObject({ ok: true, text: 'age >= 18' });
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
