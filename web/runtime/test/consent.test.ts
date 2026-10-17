/** Consent in the participant app (semantics.md §11, M5): nothing reaches the server before agreement. */
import { view, withChecksum, type Plan } from '@osp/engine';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { HttpError, type Api } from '../src/lib/api';
import { boot, type Env, type Session } from '../src/lib/session';
import { MemoryStore, type LocalStore } from '../src/lib/storage';
import { FakeServer } from './fake-server';

const t = (s: string) => ({ en: [s] });
const VERSION = 'sha256:' + 'b'.repeat(64);

function plan(saveMode: 'every-page' | 'end-only'): Plan {
	return withChecksum({
		planVersion: 'osp-runtime-plan/1',
		engineVersion: '1',
		survey: { id: 'srv', version: 1, specVersion: 'osp-survey/0.1', seedVersion: '1' },
		languages: ['en'],
		defaultLanguage: 'en',
		title: t('Test'),
		settings: { backNavigation: true, saveMode, localCopy: 'browser', resumeExpiryDays: 30 },
		consent: { version: VERSION, text: t('Info'), agree: t('Yes'), decline: t('No'), declineOutcome: 'declined', countDeclines: false },
		items: { age: { id: 'age', type: 'integer', page: 'p1', label: t('Age'), name: 'age', required: false } },
		questions: ['age'],
		pages: { p1: { id: 'p1', block: 'b1', items: ['age'], itemOrder: 'fixed' } },
		blocks: { b1: { id: 'b1', pages: ['p1'] } },
		variables: {},
		quotas: {},
		flow: [{ type: 'block', id: 'n1', block: 'b1', pages: ['p1'] }]
	} as unknown as Plan);
}

function durable(): LocalStore {
	const m = new MemoryStore();
	return { kind: 'indexeddb', get: (k) => m.get(k), put: (r) => m.put(r), delete: (k) => m.delete(k), purge: (b) => m.purge(b) };
}

/** The fake server plus the consent endpoints, recording calls. */
function withConsent(server: FakeServer): { api: Api; calls: string[] } {
	const calls: string[] = [];
	const api: Api = {
		...server.api,
		save: (...a) => {
			if (calls.includes('consent') === false) calls.push('save-before-consent');
			return server.api.save(...a);
		},
		consent: async (_sid, _tok, version) => {
			calls.push('consent');
			if (version !== VERSION) throw new HttpError(422, 'consent.version', {});
			return {};
		},
		decline: async () => {
			calls.push('decline');
			return {};
		},
		withdraw: async () => {
			calls.push('withdraw');
			return {};
		}
	};
	return { api, calls };
}

function env(api: Api, store: LocalStore): Env {
	return {
		api,
		store,
		now: () => Date.now(),
		random: () => 0.5,
		setTimer: (fn, ms) => setTimeout(fn, ms),
		clearTimer: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
		debounceMs: 3000
	};
}

let sessions: Session[] = [];
async function open(e: Env) {
	const s = await boot(e, { slug: 'demo' });
	sessions.push(s);
	void s.run();
	await vi.advanceTimersByTimeAsync(0);
	return s;
}

beforeEach(() => {
	vi.useFakeTimers({ now: new Date('2026-10-16T10:00:00Z') });
});
afterEach(() => {
	for (const s of sessions) s.dispose();
	sessions = [];
	vi.useRealTimers();
});

describe('consent page in the app', () => {
	it.each(['every-page', 'end-only'] as const)('saves nothing to the server before agreeing (%s)', async (mode) => {
		const server = new FakeServer(plan(mode), mode);
		const { api, calls } = withConsent(server);
		const s = await open(env(api, durable()));
		expect(view(s.state).status).toBe('consent');
		s.saveNow();
		s.flushKeepalive();
		await vi.advanceTimersByTimeAsync(10_000);
		expect(calls).toEqual([]);
		expect(server.calls.filter((c) => c !== 'start' && c !== 'plan')).toEqual([]);
		expect(await s.agree()).toBe(true);
		expect(view(s.state).page).toBe('p1');
		s.answer('age', 30);
		await vi.advanceTimersByTimeAsync(5_000);
		expect(calls[0]).toBe('consent');
		expect(calls).not.toContain('save-before-consent');
		if (mode === 'every-page') expect(server.only.snapshot).not.toBeNull();
		else expect(server.calls).not.toContain('save');
	});

	it('decline submits nothing and deletes the local copy', async () => {
		const server = new FakeServer(plan('every-page'));
		const store = durable();
		const { api, calls } = withConsent(server);
		const s = await open(env(api, store));
		await s.decline();
		await vi.advanceTimersByTimeAsync(5_000);
		expect(calls).toEqual(['decline']);
		expect(server.calls).not.toContain('submit');
		expect(server.calls).not.toContain('save');
		expect(s.phase).toBe('done');
		expect(await store.get('demo')).toBeFalsy();
	});

	it('withdraw after submitting calls the server and marks the session withdrawn', async () => {
		const server = new FakeServer(plan('every-page'));
		const { api, calls } = withConsent(server);
		const s = await open(env(api, durable()));
		await s.agree();
		s.answer('age', 40);
		s.next();
		await vi.advanceTimersByTimeAsync(5_000);
		expect(s.phase).toBe('done');
		expect(await s.withdraw()).toBe(true);
		expect(calls).toContain('withdraw');
		expect(s.withdrawn).toBe(true);
	});
});
