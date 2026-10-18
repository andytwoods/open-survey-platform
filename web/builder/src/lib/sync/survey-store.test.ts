import { applyTransaction, type Json } from '@osp/ops';
import { SPEC_VERSION } from '@osp/spec';
import { describe, expect, it } from 'vitest';
import { memoryTransport, type MemoryTransport } from './memory-transport';
import { SurveyStore } from './survey-store.svelte';
import { TextBuffer, type Timers } from './text-buffer';
import { failure, type Invocation, type Result, type SaveRequest, type SaveResult, type SurveyDoc, type SurveyTransport } from './transport';

const doc = (): SurveyDoc => ({
	specVersion: SPEC_VERSION,
	id: 'survey',
	metadata: { title: { en: 'T' }, languages: ['en'], defaultLanguage: 'en' },
	blocks: [{ id: 'b1', pages: [{ id: 'p1', items: [{ id: 'intro', type: 'note', label: { en: '' } }] }] }],
	flow: [{ type: 'block', id: 'n1', block: 'b1' }]
});

const title = (t: string): Invocation => ({ op: 'set_title', params: { title: { en: t } } });
const pageTitle = (t: string): Invocation => ({ op: 'set_property', params: { target: 'p1', property: 'title', value: { en: t } } });
const intro = (t: string): Invocation => ({ op: 'set_property', params: { target: 'intro', property: 'label', value: { en: t } } });
const bad: Invocation = { op: 'delete_question', params: { id: 'nope' } };

const titleOf = (s: SurveyDoc | null) => ((s?.metadata as { title: { en: string } }).title.en);
const pageTitleOf = (s: SurveyDoc | null) =>
	(((s?.blocks as { pages: { title?: { en: string } }[] }[])[0].pages[0].title ?? { en: undefined }).en);

/** A memory server with switches for the network: offline answers, lost responses, holds. */
class Server implements SurveyTransport {
	readonly mem: MemoryTransport = memoryTransport({ id: 's1', title: 'T', survey: doc(), revision: 3 });
	loads = 0;
	/** The next N saves fail before reaching the server. */
	offline = 0;
	/** The next N saves land, but their answer is lost. */
	lose = 0;
	/** Answers to give instead of the server's, next first. */
	scripted: Result<SaveResult>[] = [];
	/** Saves wait for this before going through. */
	hold: Promise<void> | null = null;
	/** Diagnostics the server adds to every answer (to tell its diagnostics from ours). */
	extra: SaveResult['diagnostics'] = [];

	get saves(): SaveRequest[] {
		return this.mem.saves;
	}
	sent: SaveRequest[] = [];

	/** Someone else saves `ops` (another tab, another client). */
	elsewhere(ops: Invocation[]) {
		const d = this.mem.draft;
		const tx = applyTransaction({ survey: d.survey as Json, revision: d.revision }, ops, d.revision);
		expect(tx.status).toBe('ok');
		this.mem.draft = { ...d, survey: tx.draft.survey as SurveyDoc, revision: d.revision + 1 };
	}

	async load(id: string) {
		this.loads++;
		return this.mem.load(id);
	}

	async saveDraft(id: string, body: SaveRequest): Promise<Result<SaveResult>> {
		this.sent.push(structuredClone(body));
		if (this.hold) await this.hold;
		if (this.offline > 0) {
			this.offline--;
			return { kind: 'offline', message: 'down' };
		}
		const s = this.scripted.shift();
		if (s) return s;
		const r = await this.mem.saveDraft(id, body);
		if (this.lose > 0) {
			this.lose--;
			return { kind: 'offline', message: 'response lost' };
		}
		if (r.kind === 'ok') return { kind: 'ok', data: { ...r.data, diagnostics: [...r.data.diagnostics, ...this.extra] } };
		return r;
	}
}

let txnCounter = 0;
async function setup() {
	const server = new Server();
	const sleeps: number[] = [];
	const store = new SurveyStore({
		transport: server,
		newTransactionId: () => `tx${++txnCounter}`,
		sleep: async (ms) => {
			sleeps.push(ms);
		},
		retryDelays: [10, 20]
	});
	expect(await store.load('s1')).toBe(true);
	return { server, store, sleeps };
}

function held(server: Server): () => void {
	let release: () => void = () => {};
	server.hold = new Promise<void>((r) => (release = r));
	return () => {
		server.hold = null;
		release();
	};
}

describe('SurveyStore: local edits', () => {
	it('shows an edit at once, then saves it as a patch against the server revision', async () => {
		const { server, store } = await setup();
		const release = held(server);
		const out = await store.submit([title('Mood')]);
		expect(out.status).toBe('applied');
		expect(titleOf(store.survey)).toBe('Mood'); // before the server answered
		expect(store.saveState).toBe('saving');
		expect(store.revision).toBe(3);
		expect(out.status === 'applied' && out.result.patch).toEqual([{ op: 'replace', path: '/metadata/title/en', value: 'Mood' }]);
		release();
		await store.settled();
		expect(store.saveState).toBe('saved');
		expect(store.revision).toBe(4);
		expect(server.mem.draft.survey).toEqual(store.survey);
		expect(server.sent[0]).toEqual({
			baseRevision: 3,
			patch: [{ op: 'replace', path: '/metadata/title/en', value: 'Mood' }],
			ops: [title('Mood')],
			transactionId: expect.any(String)
		});
	});

	it('saves queued gestures one at a time, each on the latest revision', async () => {
		const { server, store } = await setup();
		await Promise.all([store.submit([title('A')]), store.submit([pageTitle('P')])]);
		await store.settled();
		expect(server.sent.map((b) => b.baseRevision)).toEqual([3, 4]);
		expect(titleOf(server.mem.draft.survey)).toBe('A');
		expect(pageTitleOf(server.mem.draft.survey)).toBe('P');
		expect(store.revision).toBe(5);
	});

	it('counts every edit at once, never down (what e2e waits on after "saved")', async () => {
		const { store } = await setup();
		expect(store.edits).toBe(0);
		await store.submit([title('A')]);
		expect(store.edits).toBe(1);
		await store.submit([bad], { quiet: ['op.not_found'] });
		await store.undo();
		expect(store.edits).toBe(3);
		await store.settled();
		expect(store.pending).toBe(0);
	});

	it('an edit that changes nothing is not saved and is not an undo step', async () => {
		const { server, store } = await setup();
		const out = await store.submit([title('T')]);
		expect(out).toMatchObject({ status: 'applied', result: { patch: [], transactionId: null } });
		await store.settled();
		expect(server.sent).toHaveLength(0);
		expect(store.canUndo).toBe(false);
	});

	it('shows the local validator diagnostics at once and the server diagnostics once saved', async () => {
		const { server, store } = await setup();
		server.extra = [{ severity: 'warning', code: 'server.only', message: 'from the server', pointer: '' }];
		const release = held(server);
		await store.submit([intro('Hello ${nope}')]);
		expect(store.diagnostics.map((d) => d.code)).toContain('ref.unknown');
		expect(store.diagnostics.map((d) => d.code)).not.toContain('server.only');
		release();
		await store.settled();
		expect(store.diagnostics.map((d) => d.code)).toEqual(expect.arrayContaining(['ref.unknown', 'server.only']));
	});
});

describe('SurveyStore: local rejection', () => {
	it('surfaces the ops diagnostics, changes nothing and sends nothing', async () => {
		const { server, store } = await setup();
		const before = store.survey;
		const out = await store.submit([title('A'), bad]);
		expect(out.status).toBe('rejected');
		expect(store.survey).toBe(before);
		expect(store.rejection?.diagnostics[0]).toMatchObject({ code: 'op.not_found' });
		expect(store.canUndo).toBe(false);
		await store.settled();
		expect(server.sent).toHaveLength(0);
		// The next good edit clears it.
		await store.submit([title('A')]);
		expect(store.rejection).toBeNull();
	});

	it('a quiet code is returned to the caller but not surfaced', async () => {
		const { store } = await setup();
		const out = await store.submit([bad], { quiet: ['op.not_found'] });
		expect(out).toMatchObject({ status: 'rejected', diagnostics: [{ code: 'op.not_found' }] });
		expect(store.rejection).toBeNull();
		await store.submit([bad], { quiet: ['op.other'] });
		expect(store.rejection).not.toBeNull();
	});
});

describe('SurveyStore: the server refuses a save (422)', () => {
	it('rolls the change back, keeps later edits and shows the diagnostics', async () => {
		const { server, store } = await setup();
		const refused = failure(422, {
			message: 'The survey would hold text the model refuses.',
			diagnostics: [{ severity: 'error', code: 'op.invalid_text', message: 'the edit would add: x', pointer: '/metadata/title/en' }]
		});
		server.scripted = [refused as Result<SaveResult>];
		const release = held(server);
		await store.submit([title('Refused')]);
		await store.submit([pageTitle('Kept')]);
		expect(titleOf(store.survey)).toBe('Refused');
		release();
		await store.settled();
		expect(titleOf(store.survey)).toBe('T');
		expect(pageTitleOf(store.survey)).toBe('Kept');
		expect(store.rejection).toMatchObject({ message: 'The survey would hold text the model refuses.', diagnostics: [{ code: 'op.invalid_text' }] });
		expect(server.mem.draft.survey).toEqual(store.survey);
		expect(store.undoStack).toHaveLength(1); // only the kept edit can be undone
		await store.undo();
		await store.settled();
		expect(pageTitleOf(server.mem.draft.survey)).toBeUndefined();
	});

	it('a non-retryable error rolls back too, and says so', async () => {
		const { server, store } = await setup();
		server.scripted = [failure(500, { code: 'error', message: 'Server broke.' }) as Result<SaveResult>];
		await store.submit([title('Lost')]);
		await store.settled();
		expect(titleOf(store.survey)).toBe('T');
		expect(store.error).toBe('Server broke.');
		expect(store.canUndo).toBe(false);
	});
});

describe('SurveyStore: conflict (409)', () => {
	it('refetches, rebases the pending ops onto the newer draft and saves', async () => {
		const { server, store } = await setup();
		server.elsewhere([pageTitle('Elsewhere')]); // revision 4
		await store.submit([title('Mine')]);
		await store.settled();
		expect(server.sent.map((b) => b.baseRevision)).toEqual([3, 4]);
		expect(server.sent[0].transactionId).toBe(server.sent[1].transactionId);
		expect(titleOf(store.survey)).toBe('Mine');
		expect(pageTitleOf(store.survey)).toBe('Elsewhere');
		expect(server.mem.draft.survey).toEqual(store.survey);
		expect(store.revision).toBe(5);
		expect(store.conflict).toBeNull();
		expect(store.saveState).toBe('saved');
		// Undo takes back our change only.
		await store.undo();
		await store.settled();
		expect(titleOf(server.mem.draft.survey)).toBe('T');
		expect(pageTitleOf(server.mem.draft.survey)).toBe('Elsewhere');
	});

	it('shows the conflict banner and the latest draft when the pending ops no longer apply', async () => {
		const { server, store } = await setup();
		const latest = doc();
		(latest.blocks as { pages: { items: { id: string }[] }[] }[])[0].pages[0].items[0].id = 'renamed';
		server.mem.draft = { ...server.mem.draft, survey: latest, revision: 4 };
		await store.submit([intro('Mine')]);
		await store.submit([title('Also mine')]);
		await store.settled();
		expect(store.conflict?.message).toMatch(/changed elsewhere/);
		expect(store.rejection?.diagnostics[0]).toMatchObject({ code: 'op.not_found' });
		expect(store.saveState).toBe('conflict');
		expect(store.survey).toEqual(latest);
		expect(store.revision).toBe(4);
		expect(store.canUndo).toBe(false);
		store.dismissConflict();
		expect(store.saveState).toBe('saved');
	});
});

describe('SurveyStore: undo/redo', () => {
	it('a multi-op gesture is one transaction and one undo; undo and redo are saved as drafts', async () => {
		const { server, store } = await setup();
		await store.submit([title('A'), pageTitle('P')]);
		expect(store.undoStack).toHaveLength(1);
		const out = await store.undo();
		expect(out.status).toBe('applied');
		expect(titleOf(store.survey)).toBe('T'); // at once
		expect(pageTitleOf(store.survey)).toBeUndefined();
		expect(store.canUndo).toBe(false);
		expect(store.canRedo).toBe(true);
		await store.settled();
		expect(server.sent).toHaveLength(2);
		expect(server.sent[1].ops.map((o) => o.op)).toEqual(['set_property', 'set_title']);
		expect(server.mem.draft.survey).toEqual(doc());
		await store.redo();
		expect(titleOf(store.survey)).toBe('A');
		expect(store.canUndo).toBe(true);
		expect(store.canRedo).toBe(false);
		await store.settled();
		expect(server.mem.draft.revision).toBe(6);
		expect(titleOf(server.mem.draft.survey)).toBe('A');
	});

	it('undoes in reverse order and a new edit clears redo', async () => {
		const { store } = await setup();
		await store.submit([title('1')]);
		await store.submit([title('2')]);
		await store.undo();
		expect(titleOf(store.survey)).toBe('1');
		expect(store.canRedo).toBe(true);
		await store.submit([pageTitle('P')]);
		expect(store.canRedo).toBe(false);
		expect(store.undoStack).toHaveLength(2);
		await store.undo();
		await store.undo();
		expect(titleOf(store.survey)).toBe('T');
		expect(pageTitleOf(store.survey)).toBeUndefined();
	});

	it('undo with nothing to undo is dropped without a request', async () => {
		const { server, store } = await setup();
		expect((await store.undo()).status).toBe('dropped');
		expect((await store.redo()).status).toBe('dropped');
		expect(server.sent).toHaveLength(0);
	});

	it('undo flushes text buffers first, so it undoes the typed text', async () => {
		const { store } = await setup();
		const buf = new TextBuffer((v) => void store.submit([title(v)]), {
			onDirty: (d) => store.markDirty(d)
		});
		const off = store.registerBuffer(buf);
		buf.input('typed');
		expect(store.saveState).toBe('saving');
		await store.undo();
		expect(titleOf(store.survey)).toBe('T');
		expect(store.canRedo).toBe(true);
		off();
	});

	it('the history is per store (per page load)', async () => {
		const { server, store } = await setup();
		await store.submit([title('A')]);
		await store.settled();
		const again = new SurveyStore({ transport: server });
		await again.load('s1');
		expect(titleOf(again.survey)).toBe('A');
		expect(again.canUndo).toBe(false);
	});
});

describe('SurveyStore: offline', () => {
	it('retries with backoff under the same transaction id', async () => {
		const { server, store, sleeps } = await setup();
		server.offline = 2;
		await store.submit([title('A')]);
		await store.settled();
		expect(sleeps).toEqual([10, 20]);
		expect(new Set(server.sent.map((b) => b.transactionId)).size).toBe(1);
		expect(store.offline).toBe(false);
		expect(titleOf(server.mem.draft.survey)).toBe('A');
	});

	it('a retry of a save that had landed is replayed, not applied twice', async () => {
		const { server, store } = await setup();
		server.lose = 1;
		await store.submit([title('A')]);
		await store.settled();
		expect(server.sent).toHaveLength(2);
		expect(server.mem.draft.revision).toBe(4);
		expect(store.revision).toBe(4);
		expect(titleOf(store.survey)).toBe('A');
		expect(store.saveState).toBe('saved');
	});

	it('reports offline while waiting, with the edit shown and queued', async () => {
		const server = new Server();
		let release: () => void = () => {};
		const store = new SurveyStore({
			transport: server,
			sleep: () => new Promise<void>((r) => (release = r))
		});
		await store.load('s1');
		server.offline = 1;
		await store.submit([title('A')]);
		await new Promise((r) => setTimeout(r, 0));
		expect(store.saveState).toBe('offline');
		expect(titleOf(store.survey)).toBe('A');
		await store.submit([pageTitle('P')]); // still editable while offline
		expect(store.pending).toBe(2);
		release();
		await store.settled();
		expect(store.saveState).toBe('saved');
		expect(pageTitleOf(server.mem.draft.survey)).toBe('P');
	});
});

describe('SurveyStore: errors', () => {
	it('a 401 on load calls onUnauthenticated', async () => {
		let unauth = 0;
		const store = new SurveyStore({
			transport: {
				load: async () => failure(401, { code: 'auth', message: 'Sign in first.' }),
				saveDraft: async () => failure(401, {})
			},
			onUnauthenticated: () => unauth++
		});
		expect(await store.load('x')).toBe(false);
		expect(store.error).toBe('Sign in first.');
		expect(unauth).toBe(1);
	});

	it('a 401 on a save keeps the edit queued and stops sending until resume()', async () => {
		let unauth = 0;
		let signedIn = false;
		const sent: string[] = [];
		const store = new SurveyStore({
			transport: {
				load: async () => ({ kind: 'ok', data: { id: 's', title: 'T', revision: 1, survey: doc() } }),
				saveDraft: async (_id, body) => {
					sent.push(body.transactionId);
					if (!signedIn) return failure(401, { code: 'auth', message: 'Sign in first.' });
					return { kind: 'ok', data: { revision: 2, diagnostics: [], transactionId: body.transactionId } };
				}
			},
			newTransactionId: () => 'txn-1',
			onUnauthenticated: () => unauth++
		});
		await store.load('s');
		expect((await store.submit([title('A')])).status).toBe('applied');
		await store.settledOrPaused();
		expect(store.paused).toBe(true);
		expect(store.pending).toBe(1);
		expect(store.unsaved).toBe(true);
		expect(store.saveState).toBe('signed-out');
		expect(unauth).toBe(1);
		expect(sent).toEqual(['txn-1']);

		signedIn = true;
		store.resume();
		await store.settled();
		// The same transaction id is retried, so a save that did land is a no-op.
		expect(sent).toEqual(['txn-1', 'txn-1']);
		expect(store.pending).toBe(0);
		expect(store.saveState).toBe('saved');
	});
});

describe('memoryTransport', () => {
	it('answers like PUT /draft: conflict, refused patch, refused text, no-op, replay', async () => {
		const t = memoryTransport({ id: 's', title: 'T', survey: doc(), revision: 0 });
		const req = (patch: SaveRequest['patch'], baseRevision = 0, transactionId = 'a'): SaveRequest => ({ baseRevision, patch, ops: [], transactionId });
		expect((await t.saveDraft('s', req([{ op: 'remove', path: '/nope' }]))).kind).toBe('rejected');
		const link = { type: 'rich', blocks: [{ type: 'p', content: [{ text: 'x', href: 'javascript:alert(1)' }] }] };
		const r = await t.saveDraft('s', req([{ op: 'replace', path: '/blocks/0/pages/0/items/0/label', value: link }]));
		expect(r.kind === 'rejected' && r.diagnostics[0].code).toBe('op.invalid_text');
		expect((await t.saveDraft('s', req([{ op: 'replace', path: '/blocks', value: 1 }]))).kind).toBe('rejected');
		const same = await t.saveDraft('s', req([{ op: 'replace', path: '/metadata/title/en', value: 'T' }]));
		expect(same).toMatchObject({ kind: 'ok', data: { revision: 0, transactionId: null } });
		const ok = await t.saveDraft('s', req([{ op: 'replace', path: '/metadata/title/en', value: 'U' }]));
		expect(ok).toMatchObject({ kind: 'ok', data: { revision: 1, transactionId: 'a' } });
		expect(await t.saveDraft('s', req([{ op: 'replace', path: '/metadata/title/en', value: 'U' }]))).toMatchObject({
			kind: 'ok',
			data: { revision: 1, replayed: true }
		});
		expect((await t.saveDraft('s', req([], 0, 'b'))).kind).toBe('conflict');
		expect(t.saves).toHaveLength(7);
	});
});

describe('TextBuffer', () => {
	function fakeTimers() {
		const pending = new Map<number, () => void>();
		let n = 0;
		const timers: Timers = {
			set: (fn) => {
				pending.set(++n, fn);
				return n;
			},
			clear: (h) => pending.delete(h as number)
		};
		return { timers, fire: () => [...pending.values()].forEach((f) => f()), pending };
	}

	it('commits once after the pause, with the latest value', () => {
		const t = fakeTimers();
		const commits: string[] = [];
		const b = new TextBuffer((v) => commits.push(v), { timers: t.timers });
		b.input('a');
		b.input('ab');
		b.input('abc');
		expect(t.pending.size).toBe(1);
		t.fire();
		expect(commits).toEqual(['abc']);
		expect(b.dirty).toBe(false);
	});

	it('flush commits now; cancel drops; flush with nothing is a no-op', () => {
		const t = fakeTimers();
		const commits: string[] = [];
		const dirty: boolean[] = [];
		const b = new TextBuffer((v) => commits.push(v), { timers: t.timers, onDirty: (d) => dirty.push(d) });
		b.flush();
		b.input('x');
		b.flush();
		b.input('y');
		b.cancel();
		t.fire();
		expect(commits).toEqual(['x']);
		expect(dirty).toEqual([true, false, true, false]);
	});
});
