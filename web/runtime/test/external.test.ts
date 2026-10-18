/**
 * External task step in the session (task EX2): reaching the node hands the participant off
 * to the task (a return token minted, the paused state saved, the tab navigated with
 * `osp_return` + `osp_token`); on return the token is verified and the values captured; a
 * hop whose URL cannot be built is skipped rather than stranding the participant.
 */
import { view, withChecksum, type Plan } from '@osp/engine';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { boot, type Env, type Session } from '../src/lib/session';
import { MemoryStore, type LocalStore } from '../src/lib/storage';
import { FakeServer } from './fake-server';

const t = (s: string) => ({ en: [s] });

function extPlan(): Plan {
	const ext = { type: 'externalTask', id: 'et1', template: 'task', params: { pid: [{ pipe: 'prolific_pid' }] }, returns: [{ variable: 'rt', param: 'rt' }] };
	return withChecksum({
		planVersion: 'osp-runtime-plan/1',
		engineVersion: '1',
		survey: { id: 'srv', version: 1, specVersion: 'osp-survey/0.1', seedVersion: '1' },
		languages: ['en'],
		defaultLanguage: 'en',
		title: t('Test'),
		settings: { backNavigation: true, saveMode: 'every-page', localCopy: 'browser', resumeExpiryDays: 30 },
		items: { age: { id: 'age', type: 'integer', page: 'p1', label: t('Age'), name: 'age', required: true }, why: { id: 'why', type: 'text', page: 'p2', label: t('Why'), name: 'why', required: false } },
		questions: ['age', 'why'],
		pages: { p1: { id: 'p1', block: 'b1', items: ['age'], itemOrder: 'fixed' }, p2: { id: 'p2', block: 'b2', items: ['why'], itemOrder: 'fixed' } },
		blocks: { b1: { id: 'b1', pages: ['p1'] }, b2: { id: 'b2', pages: ['p2'] } },
		variables: {
			prolific_pid: { id: 'prolific_pid', kind: 'embedded', name: 'prolific_pid', valueType: 'text', source: 'url', param: 'PROLIFIC_PID', default: null },
			rt: { id: 'rt', kind: 'embedded', name: 'rt', valueType: 'integer', source: 'url', param: 'rt', default: null }
		},
		quotas: {},
		redirectTemplates: { task: { url: 'https://run.pavlovia.org/e?pid={pid}', params: { pid: {} } } },
		flow: [{ type: 'block', id: 'n1', block: 'b1', pages: ['p1'] }, ext, { type: 'block', id: 'n2', block: 'b2', pages: ['p2'] }]
	} as unknown as Plan);
}

function durable(): LocalStore {
	const m = new MemoryStore();
	return { kind: 'indexeddb', get: (k) => m.get(k), put: (r) => m.put(r), delete: (k) => m.delete(k), purge: (b) => m.purge(b) };
}

const navigated: string[] = [];
function env(server: FakeServer, store: LocalStore): Env {
	return {
		api: server.api,
		store,
		now: () => Date.now(),
		random: () => 0.5,
		setTimer: (fn, ms) => setTimeout(fn, ms),
		clearTimer: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
		navigate: (u) => navigated.push(u),
		returnUrl: () => 'https://host.example/s/demo',
		debounceMs: 3000
	};
}

const settle = async (ms = 0) => {
	await vi.advanceTimersByTimeAsync(ms);
};

let sessions: Session[] = [];
beforeEach(() => {
	vi.useFakeTimers({ now: new Date('2026-10-18T10:00:00Z') });
	sessions = [];
	navigated.length = 0;
});
afterEach(() => {
	for (const s of sessions) s.dispose();
	vi.useRealTimers();
});

async function open(e: Env, o: { urlParams?: Record<string, string>; externalReturn?: Session['externalReturn'] } = {}) {
	const s = await boot(e, { slug: 'demo', urlParams: o.urlParams });
	sessions.push(s);
	s.externalReturn = o.externalReturn ?? null;
	void s.run();
	await settle();
	await settle(3000);
	return s;
}

describe('external task handoff and return', () => {
	it('hands off: mints a token, saves, and navigates with the filled URL, osp_return and osp_token', async () => {
		const p = extPlan();
		const server = new FakeServer(p);
		const store = durable();
		const s = await open(env(server, store), { urlParams: { PROLIFIC_PID: 'p9' } });
		s.answer('age', '30');
		await s.next();
		await settle(200);
		expect(navigated).toHaveLength(1);
		const url = new URL(navigated[0]!);
		expect(url.origin + url.pathname).toBe('https://run.pavlovia.org/e');
		expect(url.searchParams.get('pid')).toBe('p9');
		expect(url.searchParams.get('osp_return')).toBe('https://host.example/s/demo');
		expect(url.searchParams.get('osp_token')).toBe(`rt:${server.only.id}:et1`);
		expect(server.calls).toContain('externalHandoff');
		// The paused state is on the server, so a return resumes exactly here.
		expect(server.only.snapshot).not.toBeNull();
	});

	it('on return: verifies the token, captures the values and continues', async () => {
		const p = extPlan();
		const server = new FakeServer(p);
		const store = durable();
		const a = await open(env(server, store), { urlParams: { PROLIFIC_PID: 'p9' } });
		a.answer('age', '30');
		await a.next();
		await settle(200);
		const token = new URL(navigated[0]!).searchParams.get('osp_token')!;
		// A fresh page load back from the task (same device): resume and present the return.
		const b = await open(env(server, store), { externalReturn: { token, values: { rt: '742', junk: 'x' } } });
		await settle(200);
		expect(view(b.state).page).toBe('p2');
		const rec = b.state.data;
		expect(rec.urlParams.rt).toBe('742'); // captured (declared in returns)
		expect(rec.urlParams.junk).toBeUndefined(); // not declared: dropped
		expect(server.calls).toContain('externalReturn');
	});

	it('skips the hop and continues when the outbound URL cannot be built', async () => {
		const p = extPlan();
		const server = new FakeServer(p);
		const store = durable();
		const s = await open(env(server, store), { urlParams: {} }); // no PROLIFIC_PID: pid is empty
		s.answer('age', '30');
		await s.next();
		await settle(200);
		expect(navigated).toHaveLength(0); // no handoff
		expect(view(s.state).page).toBe('p2'); // not stranded
		expect(server.calls).not.toContain('externalHandoff');
	});
});
