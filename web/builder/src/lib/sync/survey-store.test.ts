import { describe, expect, it } from 'vitest';
import { applyPatch, getAt, type PatchOperation } from './json-patch';
import { SurveyStore } from './survey-store.svelte';
import { TextBuffer, type Timers } from './text-buffer';
import { failure, type EditResult, type Invocation, type Result, type SurveyDoc, type SurveyTransport } from './transport';

/**
 * A scripted stand-in for osp-api. Ops: `set {path, value}` (RFC 6902 replace),
 * `expect {path, value}` (422 unless the value matches: lets a test make a replay fail)
 * and `bad` (always 422). Undo/redo reverse a transaction's patch like the real server.
 */
class FakeServer implements SurveyTransport {
	doc: SurveyDoc = { metadata: { title: { en: 'T' } }, a: 0, b: 0 };
	revision = 3;
	txns = new Map<string, { forward: PatchOperation[]; inverse: PatchOperation[]; revision: number }>();
	calls: { kind: string; body: unknown }[] = [];
	/** Queue of forced network failures (one per call). */
	offlineCalls = 0;
	#n = 0;

	edit(ops: PatchOperation[]) {
		// Someone else's edit.
		this.doc = applyPatch(this.doc, ops);
		this.revision++;
	}

	async load(): Promise<Result<{ id: string; title: string; revision: number; survey: SurveyDoc }>> {
		this.calls.push({ kind: 'load', body: null });
		return { kind: 'ok', data: { id: 's1', title: 'T', revision: this.revision, survey: structuredClone(this.doc) } };
	}

	#commit(forward: PatchOperation[], txn: string): EditResult {
		const inverse = forward
			.map((p) => ({ op: 'replace', path: p.path, value: getAt(this.doc, p.path) }))
			.reverse();
		this.doc = applyPatch(this.doc, forward);
		this.revision++;
		this.txns.set(txn, { forward, inverse, revision: this.revision });
		return { revision: this.revision, patch: forward, diagnostics: [], transactionId: txn };
	}

	async applyOps(
		_id: string,
		body: { ops: Invocation[]; baseRevision: number; transactionId: string }
	): Promise<Result<EditResult>> {
		this.calls.push({ kind: 'ops', body: structuredClone(body) });
		if (this.offlineCalls > 0) {
			this.offlineCalls--;
			return { kind: 'offline', message: 'down' };
		}
		const done = this.txns.get(body.transactionId);
		if (done && done.revision > body.baseRevision) {
			return {
				kind: 'ok',
				data: { revision: done.revision, patch: [], diagnostics: [], transactionId: body.transactionId, replayed: true }
			};
		}
		if (body.baseRevision !== this.revision) return failure(409, { message: 'stale', currentRevision: this.revision });
		const forward: PatchOperation[] = [];
		for (const [i, o] of body.ops.entries()) {
			const p = (o.params ?? {}) as { path: string; value: unknown };
			const reject = () =>
				failure(422, {
					message: 'The edit was rejected.',
					diagnostics: [{ code: 'op.invalid', message: `op ${i} invalid`, pointer: p.path ?? '', severity: 'error' }],
					failedIndex: i
				});
			if (o.op === 'bad') return reject();
			if (o.op === 'expect') {
				if (getAt(this.doc, p.path) !== p.value) return reject();
				continue;
			}
			forward.push({ op: 'replace', path: p.path, value: p.value });
		}
		return { kind: 'ok', data: this.#commit(forward, body.transactionId) };
	}

	#reverse(kind: 'undo' | 'redo', body: { transactionId: string; baseRevision: number }): Result<EditResult> {
		this.calls.push({ kind, body: structuredClone(body) });
		if (body.baseRevision !== this.revision) return failure(409, { message: 'stale', currentRevision: this.revision });
		const t = this.txns.get(body.transactionId);
		if (!t) return failure(404, { code: 'not_found', message: 'Transaction not found.' });
		return { kind: 'ok', data: this.#commit(t.inverse, `${kind[0]}:${++this.#n}`) };
	}
	async undo(_id: string, body: { transactionId: string; baseRevision: number }) {
		return this.#reverse('undo', body);
	}
	async redo(_id: string, body: { transactionId: string; baseRevision: number }) {
		return this.#reverse('redo', body);
	}
}

let txnCounter = 0;
async function setup() {
	const server = new FakeServer();
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

const set = (path: string, value: unknown): Invocation => ({ op: 'set', params: { path, value } });
const opsCalls = (s: FakeServer) => s.calls.filter((c) => c.kind === 'ops');

describe('SurveyStore: apply', () => {
	it('loads the draft and applies the server patch', async () => {
		const { server, store } = await setup();
		expect(store.revision).toBe(3);
		expect(store.saveState).toBe('saved');
		const p = store.submit([set('/a', 1)]);
		expect(store.saveState).toBe('saving');
		const out = await p;
		expect(out.status).toBe('applied');
		expect(store.survey).toEqual(server.doc);
		expect(store.revision).toBe(4);
		expect(store.saveState).toBe('saved');
		expect(opsCalls(server)[0].body).toMatchObject({ baseRevision: 3, transactionId: expect.any(String) });
	});

	it('sends queued gestures one at a time, each on the latest revision', async () => {
		const { server, store } = await setup();
		const outs = await Promise.all([store.submit([set('/a', 1)]), store.submit([set('/b', 2)])]);
		expect(outs.map((o) => o.status)).toEqual(['applied', 'applied']);
		expect(opsCalls(server).map((c) => (c.body as { baseRevision: number }).baseRevision)).toEqual([3, 4]);
		expect(store.survey).toMatchObject({ a: 1, b: 2 });
		expect(store.revision).toBe(5);
	});

	it('refetches when the patch does not apply to the local copy', async () => {
		const { server, store } = await setup();
		store.survey = { unrelated: true }; // local copy drifted
		await store.submit([set('/a', 7)]);
		expect(store.survey).toEqual(server.doc);
		expect(server.calls.filter((c) => c.kind === 'load')).toHaveLength(2);
	});
});

describe('SurveyStore: reject (422)', () => {
	it('surfaces diagnostics and changes nothing', async () => {
		const { server, store } = await setup();
		const before = store.survey;
		const out = await store.submit([set('/a', 1), { op: 'bad', params: { path: '/b' } }]);
		expect(out.status).toBe('rejected');
		expect(store.survey).toBe(before);
		expect(store.revision).toBe(3);
		expect(store.rejection?.diagnostics[0]).toMatchObject({ code: 'op.invalid', pointer: '/b' });
		expect(store.canUndo).toBe(false);
		expect(server.revision).toBe(3);
		// The next good edit clears it.
		await store.submit([set('/a', 1)]);
		expect(store.rejection).toBeNull();
	});

	it('a quiet code is returned to the caller but not surfaced', async () => {
		const { store } = await setup();
		const out = await store.submit([{ op: 'bad', params: { path: '/b' } }], { quiet: ['op.invalid'] });
		expect(out).toMatchObject({ status: 'rejected', diagnostics: [{ code: 'op.invalid' }] });
		expect(store.rejection).toBeNull();
		await store.submit([{ op: 'bad', params: { path: '/b' } }], { quiet: ['op.other'] });
		expect(store.rejection).not.toBeNull();
	});
});

describe('SurveyStore: conflict (409)', () => {
	it('refetches and replays pending ops that still validate', async () => {
		const { server, store } = await setup();
		server.edit([{ op: 'replace', path: '/b', value: 9 }]); // someone else, rev 4
		const out = await store.submit([set('/a', 1)]);
		expect(out.status).toBe('applied');
		const sent = opsCalls(server).map((c) => (c.body as { baseRevision: number; transactionId: string }));
		expect(sent.map((b) => b.baseRevision)).toEqual([3, 4]);
		expect(sent[0].transactionId).toBe(sent[1].transactionId);
		expect(store.survey).toMatchObject({ a: 1, b: 9 });
		expect(store.revision).toBe(5);
		expect(store.conflict).toBeNull();
		expect(store.saveState).toBe('saved');
	});

	it('shows the conflict banner when the replay no longer validates', async () => {
		const { server, store } = await setup();
		server.edit([{ op: 'replace', path: '/b', value: 9 }]);
		const first = store.submit([{ op: 'expect', params: { path: '/b', value: 0 } }, set('/a', 1)]);
		const second = store.submit([set('/a', 2)]);
		expect((await first).status).toBe('conflict');
		expect((await second).status).toBe('conflict');
		expect(store.conflict?.message).toMatch(/changed elsewhere/);
		expect(store.saveState).toBe('conflict');
		expect(store.survey).toMatchObject({ a: 0, b: 9 }); // the server's latest
		expect(store.revision).toBe(4);
		store.dismissConflict();
		expect(store.saveState).toBe('saved');
	});
});

describe('SurveyStore: undo/redo', () => {
	it('a multi-op gesture (drag, bulk paste) is one transaction and one undo', async () => {
		const { server, store } = await setup();
		await store.submit([set('/a', 1), set('/b', 2)]);
		expect(opsCalls(server)).toHaveLength(1);
		expect(store.undoStack).toHaveLength(1);
		const out = await store.undo();
		expect(out.status).toBe('applied');
		expect(server.calls.filter((c) => c.kind === 'undo')).toHaveLength(1);
		expect(store.survey).toMatchObject({ a: 0, b: 0 });
		expect(store.canUndo).toBe(false);
		expect(store.canRedo).toBe(true);
		await store.redo();
		expect(store.survey).toMatchObject({ a: 1, b: 2 });
		expect(store.canUndo).toBe(true);
		expect(store.canRedo).toBe(false);
	});

	it('undoes in reverse order and a new edit clears redo', async () => {
		const { server, store } = await setup();
		await store.submit([set('/a', 1)]);
		await store.submit([set('/a', 2)]);
		const ids = [...store.undoStack];
		await store.undo();
		expect(store.survey).toMatchObject({ a: 1 });
		const undone = server.calls
			.filter((c) => c.kind === 'undo')
			.map((c) => (c.body as { transactionId: string }).transactionId);
		expect(undone).toEqual([ids[1]]);
		expect(store.canRedo).toBe(true);
		await store.submit([set('/b', 5)]);
		expect(store.canRedo).toBe(false);
		expect(store.undoStack).toHaveLength(2);
	});

	it('undo with nothing to undo is dropped without a request', async () => {
		const { server, store } = await setup();
		expect((await store.undo()).status).toBe('dropped');
		expect(server.calls.filter((c) => c.kind === 'undo')).toHaveLength(0);
	});

	it('undo flushes text buffers first, so it undoes the typed text', async () => {
		const { store } = await setup();
		const buf = new TextBuffer((v) => void store.submit([set('/a', v)]), {
			onDirty: (d) => store.markDirty(d)
		});
		const off = store.registerBuffer(buf);
		buf.input('typed');
		expect(store.saveState).toBe('saving');
		await store.undo();
		expect(store.survey).toMatchObject({ a: 0 });
		expect(store.canRedo).toBe(true);
		off();
	});
});

describe('SurveyStore: offline', () => {
	it('retries with backoff under the same transaction id', async () => {
		const { server, store, sleeps } = await setup();
		server.offlineCalls = 2;
		const p = store.submit([set('/a', 1)]);
		const out = await p;
		expect(out.status).toBe('applied');
		expect(sleeps).toEqual([10, 20]);
		const ids = new Set(opsCalls(server).map((c) => (c.body as { transactionId: string }).transactionId));
		expect(ids.size).toBe(1);
		expect(store.offline).toBe(false);
		expect(store.survey).toMatchObject({ a: 1 });
	});

	it('a retry of a request that had landed refetches instead of applying twice', async () => {
		const { server, store } = await setup();
		// The first request lands but its response is lost.
		const real = server.applyOps.bind(server);
		let lost = true;
		server.applyOps = async (id, body) => {
			const r = await real(id, body);
			if (lost) {
				lost = false;
				return { kind: 'offline', message: 'response lost' };
			}
			return r;
		};
		const out = await store.submit([set('/a', 1)]);
		expect(out.status).toBe('applied');
		expect(out.status === 'applied' && out.result.replayed).toBe(true);
		expect(store.survey).toMatchObject({ a: 1 });
		expect(store.revision).toBe(server.revision);
	});

	it('reports offline while waiting', async () => {
		const server = new FakeServer();
		let release: () => void = () => {};
		const store = new SurveyStore({
			transport: server,
			sleep: () => new Promise<void>((r) => (release = r))
		});
		await store.load('s1');
		server.offlineCalls = 1;
		const p = store.submit([set('/a', 1)]);
		await new Promise((r) => setTimeout(r, 0));
		expect(store.saveState).toBe('offline');
		release();
		await p;
		expect(store.saveState).toBe('saved');
	});
});

describe('SurveyStore: errors', () => {
	it('a 401 calls onUnauthenticated', async () => {
		let unauth = 0;
		const store = new SurveyStore({
			transport: {
				load: async () => failure(401, { code: 'auth', message: 'Sign in first.' }),
				applyOps: async () => failure(401, {}),
				undo: async () => failure(401, {}),
				redo: async () => failure(401, {})
			},
			onUnauthenticated: () => unauth++
		});
		expect(await store.load('x')).toBe(false);
		expect(store.error).toBe('Sign in first.');
		expect(unauth).toBe(1);
	});

	it('a 401 on a write keeps the edit queued and stops sending until resume()', async () => {
		let unauth = 0;
		let signedIn = false;
		const sent: string[] = [];
		const store = new SurveyStore({
			transport: {
				load: async () => ({ kind: 'ok', data: { id: 's', title: 'T', revision: 1, survey: {} } }),
				applyOps: async (_id, body) => {
					sent.push(body.transactionId);
					if (!signedIn) return failure(401, { code: 'auth', message: 'Sign in first.' });
					return { kind: 'ok', data: { revision: 2, patch: [], diagnostics: [], transactionId: 't1' } };
				},
				undo: async () => failure(401, {}),
				redo: async () => failure(401, {})
			},
			newTransactionId: () => 'txn-1',
			onUnauthenticated: () => unauth++
		});
		await store.load('s');
		const out = store.submit([{ op: 'set_property', params: {} }]);
		await store.settledOrPaused();
		expect(store.paused).toBe(true);
		expect(store.pending).toBe(1);
		expect(store.unsaved).toBe(true);
		expect(store.saveState).toBe('signed-out');
		expect(unauth).toBe(1);
		expect(sent).toEqual(['txn-1']);

		signedIn = true;
		store.resume();
		expect((await out).status).toBe('applied');
		// The same transaction id is retried, so a request that did land is a no-op.
		expect(sent).toEqual(['txn-1', 'txn-1']);
		expect(store.pending).toBe(0);
		expect(store.saveState).toBe('saved');
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
