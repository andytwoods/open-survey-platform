import { answers, canonicalJson, restore, isState, view, withChecksum, type Plan } from '@osp/engine';
import { HookRunner, type HookManifest, type InvokeOutcome, type InvokeRequest } from '@osp/hooks-sandbox';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NetworkError } from '../src/lib/api';
import { boot, isPrefix, type Env, type HookFactory, type Session } from '../src/lib/session';
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

	it('the end sends no snapshot save that could land after the submit (H2d)', async () => {
		// A real server runs requests concurrently, so a PUT sent alongside the submit can
		// reach the store second and earn 409 session.submitted. Held saves model that.
		const p = plan();
		const server = new FakeServer(p);
		const s = await open(env(server));
		s.answer('age', '7');
		s.next();
		s.next();
		await settle(100);
		server.holdSaves = true;
		s.next(); // the end
		await settle(100);
		expect(s.phase).toBe('done');
		server.holdSaves = false;
		for (const go of server.held.splice(0)) go();
		s.flushKeepalive(); // the thank-you page is hidden or closed
		await settle(60_000);
		expect(server.refused).toEqual([]);
		const submitAt = server.calls.indexOf('submit');
		expect(server.calls.slice(submitAt)).toEqual(['submit']);
		expect(server.only.submitted?.answers.age?.value).toBe(7);
	});

	it('a save already on the wire is settled before the submit is sent (H2d)', async () => {
		const p = plan();
		const server = new FakeServer(p);
		const s = await open(env(server));
		s.answer('age', '8');
		s.next();
		await settle(100);
		server.holdSaves = true;
		s.answer('why', 'typed last');
		s.blur();
		await settle(300); // that save is now on the wire, held
		expect(server.held.length).toBe(1);
		s.next(); // p3
		s.next(); // the end
		await settle(100);
		expect(s.phase).toBe('submitting');
		expect(server.calls).not.toContain('submit');
		server.holdSaves = false;
		for (const go of server.held.splice(0)) go();
		await settle(60_000);
		expect(s.phase).toBe('done');
		expect(server.refused).toEqual([]);
		expect(server.calls.slice(server.calls.indexOf('submit'))).toEqual(['submit']);
		expect(server.only.submitted?.answers.why?.value).toBe('typed last');
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

describe('end redirects (EN2, end-of-survey plan §4.2)', () => {
	function redirectPlan(): Plan {
		const p = plan();
		return withChecksum({
			...p,
			redirectTemplates: { lab: { url: 'https://lab.example.org/done/{r}', params: { r: {} } } },
			endings: {
				complete: {
					status: 'auto',
					summary: 'none',
					redirect: { template: 'lab', params: { r: [{ pipe: '$response.id' }] }, delay: 5, mode: 'auto' }
				}
			}
		} as unknown as Plan);
	}

	it("is given only once this tab's submit is acknowledged, with the server's response id", async () => {
		const p = redirectPlan();
		const server = new FakeServer(p);
		const s = await open(env(server));
		expect(s.redirect).toBeNull();
		s.answer('age', '1');
		s.next();
		s.next();
		server.offline = true;
		s.next();
		await settle(100);
		expect(s.phase).toBe('submitting');
		expect(s.redirect).toBeNull(); // nothing navigates before the acknowledgement
		server.offline = false;
		await settle(60_000);
		expect(s.phase).toBe('done');
		expect(s.redirect).toEqual({
			url: `https://lab.example.org/done/r-${server.only.id}`,
			rejected: null,
			host: 'lab.example.org',
			delay: 5,
			mode: 'auto',
			label: null
		});
		// The record sent to the server was built before the id existed: no rejection logged.
		expect(server.only.submitted?.diagnostics).toEqual([]);
	});

	it('a reload that finishes a stored submit gets it; a resume of a submitted session never replays it', async () => {
		const p = redirectPlan();
		const server = new FakeServer(p);
		const store = durable();
		// The first tab's submit never gets through (and keeps failing after it is "closed").
		const blockedApi = { ...server.api, submit: () => Promise.reject(new NetworkError('offline')) };
		const a = await open({ ...env(server, store), api: blockedApi });
		a.answer('age', '2');
		a.next();
		a.next();
		a.next();
		await settle(100);
		expect(a.phase).toBe('submitting');
		expect(a.redirect).toBeNull();
		a.dispose();
		// The next load finishes the stored submit itself: that acknowledgement is its own.
		const b = await open(env(server, store));
		await settle(100);
		expect(b.phase).toBe('done');
		expect(b.redirect?.url).toBe(`https://lab.example.org/done/r-${server.only.id}`);
		// A resume link to the submitted session shows the thank-you screen, but this tab
		// submitted nothing: no redirect, so the participant is not sent off twice.
		const c = await open(env(server, store), 'demo', server.only.token);
		await settle(100);
		expect(c.phase).toBe('done');
		expect(c.redirect).toBeNull();
	});

	it('a value that fails its pattern leaves no URL (nothing navigates, nothing is shown)', async () => {
		const p = redirectPlan();
		const bad = withChecksum({
			...p,
			redirectTemplates: { lab: { url: 'https://lab.example.org/done/{r}', params: { r: { pattern: '[0-9]{3}' } } } },
			endings: { complete: { ...p.endings!.complete!, redirect: { template: 'lab', params: { r: [{ pipe: 'why' }] }, delay: 0, mode: 'auto' } } }
		} as unknown as Plan);
		const server = new FakeServer(bad);
		const s = await open(env(server));
		s.answer('age', '3');
		s.next();
		s.answer('why', '12/../admin');
		s.next();
		s.next();
		await settle(100);
		expect(s.phase).toBe('done');
		expect(s.redirect).toMatchObject({ url: null, rejected: 'r' });
		expect(server.only.submitted?.diagnostics).toEqual([
			{ code: 'redirect.param_rejected', site: 'endings.complete.redirect', path: '/params/r' }
		]);
	});
});

describe('the list of answers under the ending (EN5, end-of-survey plan §4.4)', () => {
	function summaryPlan(summary: 'answers' | 'none' = 'answers'): Plan {
		const p = plan();
		return withChecksum({ ...p, endings: { complete: { status: 'auto', summary } } } as unknown as Plan);
	}
	const ids = (s: Session) => s.summary?.map((e) => e.id) ?? null;

	it("is given only once this tab's submit is acknowledged, in path order, and only when the ending asks for it", async () => {
		const server = new FakeServer(summaryPlan());
		const s = await open(env(server));
		expect(s.summary).toBeNull();
		s.answer('age', '42');
		s.next();
		s.answer('why', 'because');
		s.next();
		server.offline = true;
		s.next();
		await settle(100);
		expect(s.phase).toBe('submitting');
		expect(s.summary).toBeNull();
		server.offline = false;
		await settle(60_000);
		expect(s.phase).toBe('done');
		expect(ids(s)).toEqual(['age', 'why']);
		expect(s.summary![1]!.value).toEqual([{ type: 'p', content: [{ kind: 'value', text: 'because' }] }]);

		const none = new FakeServer(summaryPlan('none'));
		const n = await open(env(none));
		n.answer('age', '1');
		n.next();
		n.next();
		n.next();
		await settle(100);
		expect(n.phase).toBe('done');
		expect(n.summary).toBeNull();
	});

	it('is not shown on a resume of an already-submitted session, nor after a withdrawal', async () => {
		const server = new FakeServer(summaryPlan());
		const store = durable();
		const a = await open(env(server, store));
		a.answer('age', '2');
		a.next();
		a.next();
		a.next();
		await settle(100);
		expect(ids(a)).toEqual(['age']);
		// A resume link to the submitted session (every-page): the ending, without the answers.
		const b = await open(env(server, durable()), 'demo', server.only.token);
		await settle(100);
		expect(b.phase).toBe('done');
		expect(b.summary).toBeNull();
		// Withdrawn: the server deleted the response, so the list goes too.
		expect(await a.withdraw()).toBe(true);
		expect(a.withdrawn).toBe(true);
		expect(a.summary).toBeNull();
	});

	it('end-only with a memory-only copy: a resume after the submit has nothing left to show', async () => {
		const server = new FakeServer(summaryPlan(), 'end-only');
		const pointer = tabPointer();
		const a = await open({ ...env(server, new MemoryStore()), pointer });
		a.answer('age', '3');
		await a.next();
		await a.next();
		await a.next();
		await settle(100);
		expect(a.phase).toBe('done');
		expect(ids(a)).toEqual(['age']);
		expect(pointer.map.size).toBe(0);
		a.dispose();
		const b = await open({ ...env(server, new MemoryStore()), pointer }, 'demo', server.only.token);
		await settle(100);
		expect(b.phase).toBe('done');
		expect(view(b.state).end).toBeNull();
		expect(b.summary).toBeNull();
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

	/**
	 * R9-1 (fixture 30 `storage-blocked`): typing, then a refresh at once. A save is on the
	 * wire when pagehide sends the newest copy too; the dead page never sees either reply.
	 * Returns the dead page and the server, with both saves held at the network.
	 */
	async function refreshWhileSaving(edit = false, flushes = 1) {
		const p = plan();
		const server = new FakeServer(p);
		const pointer = tabPointer();
		const a = await open({ ...env(server, new MemoryStore()), pointer });
		a.next(); // to p2 (age is required on p1)
		a.answer('age', '1');
		await a.next();
		await settle();
		expect(view(a.state).page).toBe('p2');
		server.holdSaves = true;
		a.answer('why', 'Rob');
		await settle();
		expect(server.held).toHaveLength(1); // 'Rob' is on the wire
		a.answer('why', edit ? 'Bob' : 'Robin'); // appended keystrokes, or an edit
		for (let i = 0; i < flushes; i++) a.flushKeepalive(); // visibilitychange, pagehide
		await settle();
		expect(server.held).toHaveLength(2);
		a.dispose();
		return { p, server, pointer };
	}

	for (const order of ['wire-first', 'newest-first'] as const) {
		for (const edit of [false, true]) {
			it(`a refresh straight after typing keeps the last answer (${order}${edit ? ', edited' : ''})`, async () => {
				const { p, server, pointer } = await refreshWhileSaving(edit);
				const [wire, newest] = server.held;
				server.holdSaves = false;
				if (order === 'wire-first') wire!();
				newest!();
				if (order === 'newest-first') wire!();
				await settle();
				expect(server.conflicts).toHaveLength(0);
				const want = edit ? 'Bob' : 'Robin';
				expect(serverAnswers(server, p).why).toEqual({ state: 'answered', value: want });
				const b = await open({ ...env(server, new MemoryStore()), pointer });
				expect(view(b.state).page).toBe('p2');
				expect(b.state.data.values.why).toBe(want);
				expect(b.notice).toBeNull();
			});
		}
	}

	it('visibilitychange + pagehide (two flushes) chain the newest copy once, no conflict', async () => {
		const { p, server } = await refreshWhileSaving(false, 2);
		expect(server.held).toHaveLength(2); // the wire save + one chained copy, not two
		const [wire, newest] = server.held;
		server.holdSaves = false;
		newest!();
		wire!();
		await settle();
		expect(server.conflicts).toHaveLength(0);
		expect(serverAnswers(server, p).why).toEqual({ state: 'answered', value: 'Robin' });
	});

	for (const order of ['wire-first', 'newest-first'] as const) {
		it(`hidden while a save waits out a backoff: the newest copy is chained too (${order})`, async () => {
			const p = plan();
			const server = new FakeServer(p);
			const pointer = tabPointer();
			const a = await open({ ...env(server, new MemoryStore()), pointer });
			a.next();
			a.answer('age', '1');
			await a.next();
			await settle();
			server.offline = true;
			a.answer('why', 'Rob'); // fails: the pump keeps 'Rob' in flight and sleeps
			await settle();
			a.answer('why', 'Robin'); // wakes it, fails again, sleeps; 'Rob' is still the body
			await settle();
			expect(a.rec.inflight?.snapshot.revision).toBeLessThan(a.rec.snapshot!.revision);
			server.offline = false;
			server.holdSaves = true;
			a.flushKeepalive(); // not sending: resend the body, and chain the newest
			await settle();
			expect(server.held).toHaveLength(2);
			a.dispose();
			const [wire, newest] = server.held;
			server.holdSaves = false;
			if (order === 'wire-first') wire!();
			newest!();
			if (order === 'newest-first') wire!();
			await settle();
			expect(server.conflicts).toHaveLength(0);
			expect(serverAnswers(server, p).why).toEqual({ state: 'answered', value: 'Robin' });
			const b = await open({ ...env(server, new MemoryStore()), pointer });
			expect(b.state.data.values.why).toBe('Robin');
			expect(b.notice).toBeNull();
		});
	}

	it('a page hidden and shown again clears the pointer’s promise once the server has it all', async () => {
		const p = plan();
		const server = new FakeServer(p);
		const pointer = tabPointer();
		const a = await open({ ...env(server, new MemoryStore()), pointer });
		server.holdSaves = true;
		a.answer('age', '1');
		await settle();
		a.flushKeepalive(); // tab hidden with a save on the wire
		expect(pointer.map.get('demo')?.pending).toBe(a.rec.snapshot!.revision);
		server.holdSaves = false;
		for (const go of server.held) go();
		await settle();
		expect(a.net).toBe('saved');
		expect(pointer.map.get('demo')?.pending).toBeUndefined();
		expect(serverAnswers(server, p).age).toEqual({ state: 'answered', value: 1 });
	});

	it('the reloaded page waits for the dead page’s last save when its resume overtakes it', async () => {
		const { p, server, pointer } = await refreshWhileSaving();
		expect(pointer.map.get('demo')?.pending).toBeGreaterThan(0);
		// The new page's resume reaches the server first and gets the old copy...
		const booting = boot({ ...env(server, new MemoryStore()), pointer }, { slug: 'demo' });
		await settle(20);
		expect(server.calls.filter((c) => c === 'resume').length).toBe(1);
		// ...then the two keepalive saves land, newest first.
		server.holdSaves = false;
		server.held[1]!();
		server.held[0]!();
		await settle(500);
		const b = await booting;
		sessions.push(b);
		void b.run();
		await settle();
		expect(b.state.data.values.why).toBe('Robin');
		expect(b.notice).toBeNull();
		expect(server.conflicts).toHaveLength(0);
		expect(serverAnswers(server, p).why).toEqual({ state: 'answered', value: 'Robin' });
		// The pointer no longer promises a save once the new page has it.
		b.flushKeepalive();
		expect(pointer.map.get('demo')?.pending).toBeUndefined();
	});

	it('a dead page’s save that never lands delays the reload by at most ~3 s', async () => {
		const { server, pointer } = await refreshWhileSaving();
		server.held.length = 0; // both lost on the way
		server.holdSaves = false;
		const booting = boot({ ...env(server, new MemoryStore()), pointer }, { slug: 'demo' });
		await settle(3200);
		const b = await booting;
		sessions.push(b);
		expect(view(b.state).page).toBe('p2');
		expect(b.state.data.values.why).toBeUndefined();
		expect(server.calls.filter((c) => c === 'resume').length).toBe(7);
	});

	it('two devices that diverged still conflict: the server copy wins (R6-6)', async () => {
		const p = plan();
		const server = new FakeServer(p);
		const store = durable();
		const a = await open(env(server, store));
		a.answer('age', '1');
		await a.next();
		await settle();
		const b = await open(env(server, durable()), 'demo', a.rec.resumeToken);
		b.answer('why', 'from B');
		await b.next();
		await settle();
		a.answer('why', 'from A'); // A is stale and diverges from B
		a.blur();
		await settle(1000);
		expect(server.conflicts).toHaveLength(1);
		expect(serverAnswers(server, p).why).toEqual({ state: 'answered', value: 'from B' });
		expect(a.notice).toBe('conflict');
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

describe('researcher hooks (runtime-design §7a)', () => {
	const manifest: HookManifest = {
		format: 'osp-hooks/1',
		source: '',
		handlers: { onPageShown: { reads: [], writes: [] }, onPageNext: { reads: ['age'], writes: [] } }
	};
	const hooked = () => withChecksum({ ...plan(), hooks: manifest } as unknown as Plan);

	/** A sandbox that answers every call at once, except the ones `hold` keeps waiting. */
	function invoker(hold: string[] = []) {
		const calls: InvokeRequest[] = [];
		const waiting: (() => void)[] = [];
		return {
			calls,
			release: () => waiting.splice(0).forEach((r) => r()),
			invoke(req: InvokeRequest): Promise<InvokeOutcome> {
				calls.push(req);
				if (!hold.includes(req.event)) return Promise.resolve({ status: 'ok', actions: [] });
				return new Promise((resolve) => waiting.push(() => resolve({ status: 'ok', actions: [] })));
			},
			dispose() {}
		};
	}
	const factory = (inv: ReturnType<typeof invoker>, ready: Promise<void> = Promise.resolve()): HookFactory =>
		async (p, state, onState) => {
			await ready;
			return new HookRunner({ plan: p, manifest, invoker: inv, state, onState });
		};
	const nextReads = (inv: ReturnType<typeof invoker>) =>
		inv.calls.filter((c) => c.event === 'onPageNext').map((c) => (c.ctx as { results: Record<string, unknown> }).results);

	it('an answer typed while onPageShown runs is applied when it is done, not dropped', async () => {
		const p = hooked();
		const inv = invoker(['onPageShown']);
		const s = await open({ ...env(new FakeServer(p)), hooks: factory(inv) });
		expect(s.phase).toBe('hook');
		s.answer('age', '42');
		expect(s.state.data.values.age).toBeUndefined();
		inv.release();
		await settle();
		expect(s.phase).toBe('page');
		expect(s.state.data.values.age).toBe(42);
		const next = s.next();
		await settle();
		inv.release(); // p2's onPageShown
		expect(await next).toBe('advanced');
		expect(nextReads(inv)).toEqual([{ age: expect.objectContaining({ value: 42 }) }]);
		expect(view(s.state).page).toBe('p2');
	});

	it('while the sandbox loads, Next waits and answers are held for the runner', async () => {
		const p = hooked();
		const inv = invoker();
		let loaded!: () => void;
		const s = await open({ ...env(new FakeServer(p)), hooks: factory(inv, new Promise((r) => (loaded = r))) });
		expect(s.phase).toBe('hook');
		expect(await s.next()).toBeNull();
		s.answer('age', '7');
		loaded();
		await settle();
		expect(s.phase).toBe('page');
		expect(s.state.data.values.age).toBe(7);
		expect(inv.calls.map((c) => c.event)).toEqual(['onPageShown']);
	});
});
