import { describe, expect, it } from 'vitest';
import { RELOAD_KEY, RELOAD_WINDOW_MS, Session } from './session.svelte';

function memoryStorage() {
	const m = new Map<string, string>();
	return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), m };
}

function make(opts: { unsaved?: boolean; now?: number } = {}) {
	const storage = memoryStorage();
	let reloads = 0;
	let now = opts.now ?? 1_000_000;
	const s = new Session({
		now: () => now,
		reload: () => void reloads++,
		storage,
		here: () => '/surveys/s1?x=1#q',
		unsaved: () => opts.unsaved ?? false
	});
	return {
		s,
		storage,
		reloads: () => reloads,
		advance: (ms: number) => (now += ms)
	};
}

describe('Session (D9)', () => {
	it('reload mode: reloads once, then shows the banner instead of looping', () => {
		const a = make();
		a.s.configure('reload');
		a.s.unauthenticated();
		expect(a.s.status).toBe('ended');
		expect(a.reloads()).toBe(1);
		expect(a.s.reloading).toBe(true);
		expect(a.storage.m.get(RELOAD_KEY)).toBe('1000000');

		// The reloaded page (same tab storage) gets a 401 again: no second reload.
		const b = new Session({ now: () => 1_000_500, reload: () => expect.unreachable(), storage: a.storage });
		b.configure('reload');
		b.unauthenticated();
		expect(b.status).toBe('ended');
		expect(b.reloading).toBe(false);
		expect(b.signInUrl).toBeNull();
	});

	it('reload mode: may reload again only after the window has passed', () => {
		const a = make();
		a.s.configure(undefined);
		a.storage.setItem(RELOAD_KEY, String(1_000_000 - RELOAD_WINDOW_MS - 1));
		a.s.unauthenticated();
		expect(a.reloads()).toBe(1);
	});

	it('never auto-reloads over unsaved edits', () => {
		const a = make({ unsaved: true });
		a.s.configure('reload');
		a.s.unauthenticated();
		expect(a.reloads()).toBe(0);
		expect(a.s.status).toBe('ended');
		a.s.reloadNow();
		expect(a.reloads()).toBe(1);
	});

	it('redirect mode: no reload; the banner links to sign-in with ?next=', () => {
		const a = make();
		a.s.configure({ redirect: '/accounts/login/' });
		a.s.unauthenticated();
		expect(a.reloads()).toBe(0);
		expect(a.s.signInUrl).toBe('/accounts/login/?next=%2Fsurveys%2Fs1%3Fx%3D1%23q');
		a.s.configure({ redirect: 'https://lab.example.org/login?sso=1#top' });
		expect(a.s.signInUrl).toBe('https://lab.example.org/login?sso=1&next=%2Fsurveys%2Fs1%3Fx%3D1%23q#top');
	});

	it('a 401 is reported once; 403 is a separate state that does not hide a 401', () => {
		const a = make();
		a.s.configure({ redirect: '/login' });
		a.s.forbidden();
		expect(a.s.status).toBe('forbidden');
		a.s.dismissForbidden();
		expect(a.s.status).toBe('ok');
		a.s.unauthenticated();
		a.s.unauthenticated();
		a.s.forbidden();
		expect(a.s.status).toBe('ended');
	});
});
