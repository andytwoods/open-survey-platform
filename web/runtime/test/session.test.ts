import { answers, canonicalJson, restore, isState, view, withChecksum, type Plan } from '@osp/engine';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { boot, isPrefix, type Env, type Session } from '../src/lib/session';
import { MemoryStore, type LocalStore, type PointerRecord, type SessionPointer } from '../src/lib/storage';
import { FakeServer } from './fake-server';

const t = (s: string) => ({ en: [s] });

function plan(withQuota = false): Plan {
	const items = {
		age: { id: 'age', type: 'integer', page: 'p1', label: t('Age'), name: 'age', required: true },
		why: { id: 'why', type: 'text', page: 'p2', label: t('Why'), name: 'why', required: false },
		bye: { id: 'bye', type: 'note', page: 'p3', label: t('Bye') }
	};
	const pages = {
		p1: { id: 'p1', block: 'b1', items: ['age'], itemOrder: 'fixed' },
		p2: { id: 'p2', block: 'b2', items: ['why'], itemOrder: 'fixed' },
		p3: { id: 'p3', block: 'b3', items: ['bye'], itemOrder: 'fixed' }
	};
	const block = (n: number) => ({ type: 'block', id: `n${n}`, block: `b${n}`, pages: [`p${n}`] });
	const flow = withQuota
		? [block(1), { type: 'quotaCheck', id: 'qc', quota: 'q1' }, block(2), block(3)]
		: [block(1), block(2), block(3)];
	return withChecksum({
		planVersion: 'osp-runtime-plan/1',
		engineVersion: '1',
		survey: { id: 'srv', version: 1, specVersion: 'osp-survey/0.1', seedVersion: '1' },
		languages: ['en'],
		defaultLanguage: 'en',
		title: t('Test'),
		settings: { backNavigation: true, saveMode: 'every-page', localCopy: 'browser', resumeExpiryDays: 30 },
		items,
		questions: ['age', 'why'],
		pages,
		blocks: { b1: { id: 'b1', pages: ['p1'] }, b2: { id: 'b2', pages: ['p2'] }, b3: { id: 'b3', pages: ['p3'] } },
		variables: {},
		quotas: withQuota
			? {
					q1: {
						id: 'q1',
						when: { kind: 'answered', ref: { kind: 'ref', id: 'age' } },
						limit: 10,
						countOn: 'complete',
						onFull: { block: null, pages: [], outcome: 'full' }
					}
				}
			: {},
		flow
	} as unknown as Plan);
}

/** A MemoryStore that reports itself as IndexedDB (storage available). */
function durable(): LocalStore {
	const m = new MemoryStore();
	return {
		kind: 'indexeddb',
		get: (k) => m.get(k),
		put: (r) => m.put(r),
		delete: (k) => m.delete(k),
		purge: (b) => m.purge(b)
	};
}

function env(server: FakeServer, store: LocalStore = durable()): Env {
	return {
		api: server.api,
		store,
		now: () => Date.now(),
		random: () => 0.5,
		setTimer: (fn, ms) => setTimeout(fn, ms),
		clearTimer: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
		debounceMs: 3000
	};
}

const settle = async (ms = 0) => {
	await vi.advanceTimersByTimeAsync(ms);
};

let sessions: Session[] = [];
async function open(e: Env, slug = 'demo', resumeToken?: string) {
	const s = await boot(e, { slug, resumeToken });
	sessions.push(s);
	void s.run();
	await settle();
	return s;
}

beforeEach(() => {
	vi.useFakeTimers({ now: new Date('2026-10-16T10:00:00Z') });
	sessions = [];
});
afterEach(() => {
	for (const s of sessions) s.dispose();
	vi.useRealTimers();
});

function serverAnswers(server: FakeServer, p: Plan) {
	const st = restore(p, server.only.snapshot);
	if (!isState(st)) throw new Error('server snapshot does not restore');
	return answers(st);
}

describe('every-page saving', () => {
	it('stores seed, assignment and checksum locally before the first page, then saves', async () => {
		const p = plan();
		const server = new FakeServer(p);
		const store = durable();
		const s = await open(env(server, store));
		const rec = await store.get('demo');
		expect(rec?.sessionSeed).toBe(server.only.seed);
		expect(rec?.planChecksum).toBe(p.checksum);
		expect(rec?.snapshot?.data.sessionSeed).toBe(server.only.seed);
		expect(view(s.state).page).toBe('p1');
		await settle();
		expect(server.only.revision).toBe(1);
		expect(s.net).toBe('saved');
	});

	it('writes locally on every answer, saves after the debounce and on blur', async () => {
		const p = plan();
		const server = new FakeServer(p);
		const store = durable();
		const s = await open(env(server, store));
		const before = server.only.revision;
		s.answer('age', '4');
		await settle();
		expect((await store.get('demo'))?.snapshot?.data.values.age).toBe(4);
		await settle(2000);
		expect(server.only.revision).toBe(before);
		await settle(1100);
		expect(server.only.revision).toBe(before + 1);
		s.answer('age', '42');
		s.blur();
		await settle(300); // the blur save waits a moment for a Next/Back that would replace it
		expect(serverAnswers(server, p).age).toBeDefined();
		expect(server.only.snapshot?.data.values.age).toBe(42);
	});

	it('resends a save whose reply was lost unchanged, so it is a replay, not a conflict', async () => {
		const p = plan();
		const server = new FakeServer(p);
		const s = await open(env(server));
		s.answer('age', '30');
		server.dropReplies = 1;
		s.next();
		await settle(5000);
		s.answer('why', 'because');
		s.blur();
		await settle(60_000);
		expect(server.conflicts).toEqual([]);
		expect(server.only.snapshot?.data.values).toEqual({ age: 30, why: 'because' });
		expect(s.net).toBe('saved');
	});

	it('keeps answering offline and catches up when the connection returns', async () => {
		const p = plan();
		const server = new FakeServer(p);
		const s = await open(env(server));
		server.offline = true;
		s.answer('age', '31');
		s.next();
		s.answer('why', 'offline text');
		await settle(10_000);
		expect(s.net).toBe('offline');
		expect(view(s.state).page).toBe('p2');
		server.offline = false;
		s.wake();
		await settle(100);
		expect(s.net).toBe('saved');
		expect(canonicalJson(server.only.snapshot)).toBe(canonicalJson(s.rec.snapshot));
	});

	it('a refresh with unsent answers reconciles by event log and pushes them', async () => {
		const p = plan();
		const server = new FakeServer(p);
		const store = durable();
		const e = env(server, store);
		const a = await open(e);
		a.answer('age', '50');
		a.next();
		await settle();
		server.offline = true;
		a.answer('why', 'typed then refreshed');
		a.dispose(); // the tab dies before any save
		server.offline = false;
		const b = await open(e);
		expect(view(b.state).page).toBe('p2');
		await settle(100);
		expect(server.conflicts).toEqual([]);
		expect(server.only.snapshot?.data.values).toEqual({ age: 50, why: 'typed then refreshed' });
	});

	it('two devices: the server copy wins and the losing local copy is kept', async () => {
		const p = plan();
		const server = new FakeServer(p);
		const a = await open(env(server, durable()));
		a.answer('age', '20');
		a.next();
		await settle();
		const token = a.rec.resumeToken;
		const b = await open(env(server, new MemoryStore()), 'demo', token);
		expect(view(b.state).page).toBe('p2');
		b.answer('why', 'from device B');
		b.next();
		await settle();
		a.answer('why', 'from device A');
		a.next();
		await settle(100);
		expect(a.rec.conflicts).toHaveLength(1);
		expect(server.conflicts).toHaveLength(1);
		expect(a.state.data.values.why).toBe('from device B');
		expect(server.only.snapshot?.data.values.why).toBe('from device B');
		expect(a.notice).toBe('conflict'); // R6-6: the device that lost says so
		expect(isPrefix(server.only.snapshot, a.rec.snapshot)).toBe(true);
	});

	it('storage blocked: saves on every answer without waiting for the debounce', async () => {
		const p = plan();
		const server = new FakeServer(p);
		const s = await open(env(server, new MemoryStore()));
		expect(s.storageBlocked).toBe(true);
		const rev = server.only.revision;
		s.answer('age', '7');
		await settle();
		expect(server.only.revision).toBe(rev + 1);
	});
});

describe('effects and submit', () => {
	it('retries the quota call until it answers, then submits and deletes the local copy', async () => {
		const p = plan(true);
		const server = new FakeServer(p);
		const store = durable();
		const s = await open(env(server, store));
		s.answer('age', '9');
		server.offline = true;
		s.next();
		await settle(5000);
		expect(s.phase).toBe('pending');
		server.offline = false;
		await settle(60_000);
		expect(s.phase).toBe('page');
		expect(view(s.state).page).toBe('p2');
		s.next();
		s.next();
		await settle();
		expect(s.phase).toBe('done');
		expect(server.only.submitted?.answers.age).toEqual({ state: 'answered', value: 9 });
		expect(await store.get('demo')).toBeUndefined();
	});

	it('shows thank-you only after the acknowledgement; a lost reply is resubmitted identically', async () => {
		const p = plan();
		const server = new FakeServer(p);
		const store = durable();
		const s = await open(env(server, store));
		s.answer('age', '1');
		s.next();
		s.next();
		server.dropOn.submit = 1;
		s.next();
		await settle();
		expect(s.phase).toBe('submitting');
		expect((await store.get('demo'))?.submitting).not.toBeNull();
		await settle(60_000);
		expect(s.phase).toBe('done');
		expect(server.calls.filter((c) => c === 'submit').length).toBe(2);
	});

	it('end-only: no answers reach the server before submit', async () => {
		const p = plan();
		const server = new FakeServer(p, 'end-only');
		const s = await open(env(server));
		expect(s.net).toBe('local');
		s.answer('age', '3');
		s.blur();
		s.next();
		s.answer('why', 'secret');
		s.flushKeepalive();
		await settle(10_000);
		expect(server.calls).not.toContain('save');
		expect(server.only.snapshot).toBeNull();
		s.next();
		s.next();
		await settle();
		expect(server.calls).not.toContain('save');
		expect(server.only.submitted?.answers.why).toEqual({ state: 'answered', value: 'secret' });
	});

	it('refreshing after the end resubmits the stored record and finishes', async () => {
		const p = plan();
		const server = new FakeServer(p);
		const store = durable();
		const e = env(server, store);
		const a = await open(e);
		a.answer('age', '5');
		a.next();
		a.next();
		server.offline = true;
		a.next();
		await settle(100);
		a.dispose();
		server.offline = false;
		const b = await open(e);
		await settle(100);
		expect(b.phase).toBe('done');
		expect(server.only.submitted?.answers.age?.value).toBe(5);
	});
});

/** A tab's sessionStorage pointer, in memory. */
function tabPointer(): SessionPointer & { map: Map<string, PointerRecord> } {
	const map = new Map<string, PointerRecord>();
	return {
		kind: 'sessionStorage',
		map,
		get: (k) => (map.has(k) ? (JSON.parse(JSON.stringify(map.get(k))) as PointerRecord) : null),
		set: (k, p) => void map.set(k, JSON.parse(JSON.stringify(p)) as PointerRecord),
		clear: (k) => void map.delete(k)
	};
}

describe('no durable local copy (R4-3, R6-5)', () => {
	it('every-page, storage blocked: a refresh resumes the same session from the server', async () => {
		const p = plan();
		const server = new FakeServer(p);
		const pointer = tabPointer();
		const a = await open({ ...env(server, new MemoryStore()), pointer });
		a.answer('age', '20');
		await a.next();
		await settle();
		a.dispose();
		// Refresh: a new page, a new (empty) MemoryStore, the same tab pointer.
		const b = await open({ ...env(server, new MemoryStore()), pointer });
		expect(b.rec.sessionId).toBe(a.rec.sessionId);
		expect(view(b.state).page).toBe('p2');
		expect(b.state.data.values.age).toBe(20);
		expect(server.sessions.size).toBe(1);
		expect(b.notice).toBeNull();
	});

	it('end-only, storage blocked: a refresh restarts the session with the same seed and a notice', async () => {
		const p = plan();
		const server = new FakeServer(p, 'end-only');
		const pointer = tabPointer();
		const a = await open({ ...env(server, new MemoryStore()), pointer });
		a.answer('age', '20');
		await a.next();
		expect(view(a.state).page).toBe('p2');
		a.dispose();
		const b = await open({ ...env(server, new MemoryStore()), pointer });
		expect(b.rec.sessionId).toBe(a.rec.sessionId);
		expect(view(b.state).page).toBe('p1');
		expect(b.state.data.values.age).toBeUndefined();
		expect(b.state.data.sessionSeed).toBe(a.state.data.sessionSeed);
		expect(b.notice).toBe('restarted');
		expect(server.calls).not.toContain('save');
		// Moving on clears the notice; the end submits once, to the same session.
		b.answer('age', '21');
		await b.next();
		expect(b.notice).toBeNull();
		await b.next();
		await b.next();
		await settle();
		expect(server.only.submitted?.answers.age).toEqual({ state: 'answered', value: 21 });
		expect(pointer.map.size).toBe(0);
	});
});

describe('errors after a refresh (R4-2)', () => {
	it('a restored page shows no error until the next Next', async () => {
		const p = plan();
		const server = new FakeServer(p);
		const store = durable();
		const a = await open(env(server, store));
		expect(await a.next()).toBe('invalid');
		expect(Object.keys(a.view().errors)).toEqual(['age']);
		a.dispose();
		const b = await open(env(server, store));
		expect(b.view().errors).toEqual({});
		expect(b.view().items.every((i) => i.error === null)).toBe(true);
		expect(await b.next()).toBe('invalid');
		expect(Object.keys(b.view().errors)).toEqual(['age']);
	});
});
