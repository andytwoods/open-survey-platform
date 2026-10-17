import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { livePolicy } from './live';
import { LivePoller, type Fetched, type LiveHooks, type Watermark } from './live.svelte';

// The live poller (task LV3) on a fake clock: polls on the server's interval, re-queries
// only on a watermark change and only when idle (else the badge), at most once per
// minRefreshMs and never two at once (a change seen mid-flight means one more), pauses in
// a hidden tab and polls at once on return, backs off on failure, ends on 401/403, and
// pauses while presenting (LV4's job to make that batched).

function harness(opts: { minRefreshMs?: number } = {}) {
	const server = { watermark: 'a', responses: 5, pollAfterMs: 10_000 };
	let shown: string | null = 'a';
	const polls: number[] = [];
	const refreshes: { live: boolean; at: number }[] = [];
	const h = {
		busy: false,
		hidden: false,
		presenting: false,
		fail: null as { status: number; message: string } | null,
		refreshMs: 0,
		/** A response arrived (or `n` of them). */
		arrive(n = 1) {
			server.responses += n;
			server.watermark = `w${server.responses}`;
		},
		server,
		polls,
		refreshes,
		shown: () => shown
	};
	const hooks: LiveHooks = {
		async poll(): Promise<Fetched<Watermark>> {
			polls.push(Date.now());
			if (h.fail) return { ok: false, ...h.fail };
			return { ok: true, data: { ...server, versionsUsed: [1] } };
		},
		async refresh(live) {
			refreshes.push({ live, at: Date.now() });
			const asOf = server.watermark; // a query returns the world as it was when it started
			if (h.refreshMs) await new Promise((r) => setTimeout(r, h.refreshMs));
			shown = asOf;
			return true;
		},
		watermark: () => shown,
		busy: () => h.busy,
		hidden: () => h.hidden,
		policy: () => livePolicy({ presenting: h.presenting })
	};
	const poller = new LivePoller(hooks, opts);
	// The same object the hooks read, so a test's `t.busy = true` is seen by the poller.
	return Object.assign(h, { poller });
}

const tickTo = (ms: number) => vi.advanceTimersByTimeAsync(ms);

beforeEach(() => {
	vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
	vi.setSystemTime(0);
});
afterEach(() => vi.useRealTimers());

describe('LivePoller', () => {
	it('polls at once, then on the server’s interval; nothing changed, nothing re-queried', async () => {
		const t = harness();
		expect(t.poller.status).toBe('off');
		t.poller.start();
		expect(t.poller.on).toBe(true);
		await tickTo(0);
		expect(t.polls).toHaveLength(1);
		expect(t.poller.intervalMs).toBe(10_000);
		expect(t.poller.responses).toBe(5);
		expect(t.poller.status).toBe('waiting');
		await tickTo(9_999);
		expect(t.polls).toHaveLength(1);
		await tickTo(1);
		expect(t.polls).toHaveLength(2);
		await tickTo(30_000);
		expect(t.polls).toHaveLength(5);
		expect(t.refreshes).toEqual([]);
		expect(t.poller.changed).toBe(false);
		// The server can change its mind about the interval.
		t.server.pollAfterMs = 2_000;
		await tickTo(10_000);
		await tickTo(2_000);
		expect(t.poller.intervalMs).toBe(2_000);
		expect(t.polls).toHaveLength(7);
		t.poller.stop();
		await tickTo(60_000);
		expect(t.polls).toHaveLength(7);
		expect(t.poller.status).toBe('off');
	});

	it('a changed watermark while idle re-queries as a live refresh and counts the new responses', async () => {
		const t = harness();
		t.poller.start();
		await tickTo(0);
		t.arrive(2);
		await tickTo(10_000);
		expect(t.refreshes).toEqual([{ live: true, at: 10_000 }]);
		expect(t.poller.refreshes).toBe(1);
		expect(t.poller.changed).toBe(false);
		expect(t.poller.pending).toBeNull();
		expect(t.poller.lastRefreshAt).toBe(10_000);
		// The next poll matches what is shown: baseline 7; one more arrives: "1 new".
		await tickTo(10_000);
		t.busy = true;
		t.arrive(1);
		await tickTo(10_000);
		expect(t.poller.changed).toBe(true);
		expect(t.poller.pending).toBe(1);
		expect(t.refreshes).toHaveLength(1); // busy: badge, no refresh
	});

	it('busy means the badge; idle again refreshes on the next poll; Refresh is a manual query', async () => {
		const t = harness();
		t.busy = true;
		t.poller.start();
		await tickTo(0);
		t.arrive();
		await tickTo(10_000);
		expect(t.poller.changed).toBe(true);
		expect(t.poller.pending).toBe(1);
		expect(t.refreshes).toEqual([]);
		await tickTo(10_000);
		expect(t.refreshes).toEqual([]); // still busy
		t.busy = false;
		await tickTo(10_000);
		expect(t.refreshes).toEqual([{ live: true, at: 30_000 }]);
		expect(t.poller.changed).toBe(false);

		t.busy = true;
		t.arrive();
		await tickTo(10_000);
		expect(t.poller.changed).toBe(true);
		await t.poller.refreshNow();
		expect(t.refreshes.at(-1)).toEqual({ live: false, at: 40_000 });
		expect(t.poller.changed).toBe(false);
		expect(t.poller.pending).toBeNull();
	});

	it('responses removed: the badge says "changed", the count is not negative news', async () => {
		const t = harness();
		t.busy = true;
		t.poller.start();
		await tickTo(0);
		t.server.responses = 3;
		t.server.watermark = 'w3';
		await tickTo(10_000);
		expect(t.poller.changed).toBe(true);
		expect(t.poller.pending).toBe(-2);
	});

	it('refreshes at most once per minRefreshMs, and never two at once (a change mid-flight means one more)', async () => {
		const t = harness({ minRefreshMs: 5_000 });
		t.server.pollAfterMs = 1_000;
		t.poller.start();
		await tickTo(0);
		t.arrive();
		await tickTo(1_000);
		expect(t.refreshes).toHaveLength(1);
		t.arrive();
		await tickTo(1_000); // 2 s: too soon
		expect(t.refreshes).toHaveLength(1);
		expect(t.poller.changed).toBe(true);
		await tickTo(4_000); // 6 s: 5 s after the first
		expect(t.refreshes).toHaveLength(2);
		expect(t.refreshes[1].at).toBe(6_000);
		expect(t.poller.changed).toBe(false);

		// A slow refresh: a poll that sees a newer watermark mid-flight does not start a second
		// one; after it completes, one more follows (after minRefreshMs from its end).
		await tickTo(6_000); // 12 s
		t.refreshMs = 3_000;
		t.arrive();
		await tickTo(1_000); // 13 s: refresh 3 starts
		expect(t.refreshes).toHaveLength(3);
		t.arrive(); // 13 s + : newer than what refresh 3 will return
		await tickTo(1_000); // 14 s: the poll sees it; a refresh is in flight → no second one
		expect(t.refreshes).toHaveLength(3);
		expect(t.poller.status).toBe('refreshing');
		await tickTo(2_000); // 16 s: refresh 3 done, but it shows the 13 s world: the badge is back
		expect(t.refreshes).toHaveLength(3);
		expect(t.poller.changed).toBe(true);
		expect(t.poller.pending).toBe(1);
		t.refreshMs = 0;
		await tickTo(4_999); // not yet: minRefreshMs runs from the end of refresh 3
		expect(t.refreshes).toHaveLength(3);
		await tickTo(1); // 21 s: one more, and only one
		expect(t.refreshes).toHaveLength(4);
		expect(t.refreshes[3]).toEqual({ live: true, at: 21_000 });
		expect(t.poller.changed).toBe(false);
		expect(t.shown()).toBe(t.server.watermark);
		await tickTo(10_000);
		expect(t.refreshes).toHaveLength(4);
	});

	it('a hidden tab pauses polling; coming back polls at once', async () => {
		const t = harness();
		t.poller.start();
		await tickTo(0);
		t.hidden = true;
		document.dispatchEvent(new Event('visibilitychange'));
		expect(t.poller.status).toBe('paused');
		expect(t.poller.pausedBy).toBe('hidden');
		await tickTo(60_000);
		expect(t.polls).toHaveLength(1);
		t.arrive();
		t.hidden = false;
		document.dispatchEvent(new Event('visibilitychange'));
		await tickTo(0);
		expect(t.polls).toHaveLength(2);
		expect(t.refreshes).toHaveLength(1);
		expect(t.poller.status).toBe('waiting');
	});

	it('a failed poll backs off (10 → 20 → 40 … 120 s) and keeps the last results; success resets it', async () => {
		const t = harness();
		t.poller.start();
		await tickTo(0);
		t.fail = { status: 0, message: 'Network error.' };
		await tickTo(10_000);
		expect(t.poller.status).toBe('retrying');
		expect(t.poller.retryMs).toBe(10_000);
		expect(t.poller.error).toBe('Network error.');
		await tickTo(10_000);
		expect(t.poller.retryMs).toBe(20_000);
		await tickTo(20_000);
		expect(t.poller.retryMs).toBe(40_000);
		await tickTo(40_000);
		expect(t.poller.retryMs).toBe(80_000);
		await tickTo(80_000);
		expect(t.poller.retryMs).toBe(120_000);
		await tickTo(120_000);
		expect(t.poller.retryMs).toBe(120_000);
		expect(t.polls).toHaveLength(7);
		t.fail = { status: 429, message: 'Too many watermark requests.' };
		await tickTo(120_000);
		expect(t.poller.status).toBe('retrying'); // 429 is a back-off too
		t.fail = null;
		await tickTo(120_000);
		expect(t.poller.status).toBe('waiting');
		expect(t.poller.retryMs).toBe(0);
		expect(t.poller.error).toBeNull();
		expect(t.poller.on).toBe(true);
		expect(t.refreshes).toEqual([]);
	});

	it('401 ends live quietly (the session banner speaks); 403 ends it with the access message', async () => {
		const a = harness();
		a.poller.start();
		await tickTo(0);
		a.fail = { status: 401, message: 'Signed out.' };
		await tickTo(10_000);
		expect(a.poller.on).toBe(false);
		expect(a.poller.status).toBe('ended');
		expect(a.poller.error).toBeNull();
		await tickTo(60_000);
		expect(a.polls).toHaveLength(2);

		const b = harness();
		b.poller.start();
		await tickTo(0);
		b.fail = { status: 403, message: 'Forbidden.' };
		await tickTo(10_000);
		expect(b.poller.on).toBe(false);
		expect(b.poller.status).toBe('ended');
		expect(b.poller.error).toMatch(/no longer have access/);
		// Turning it on again starts afresh.
		b.fail = null;
		b.poller.start();
		await tickTo(0);
		expect(b.poller.status).toBe('waiting');
		expect(b.poller.error).toBeNull();
	});

	it('presenting pauses live (until LV4); wake() polls again at once', async () => {
		const t = harness();
		t.presenting = true;
		t.poller.start();
		await tickTo(0);
		expect(t.polls).toHaveLength(0);
		expect(t.poller.status).toBe('paused');
		expect(t.poller.pausedBy).toBe('presentation');
		t.presenting = false;
		t.poller.wake();
		await tickTo(0);
		expect(t.polls).toHaveLength(1);
		expect(t.poller.status).toBe('waiting');
	});

	it('set() toggles; stop() drops a poll in flight and clears the badge', async () => {
		const t = harness();
		t.poller.set(true);
		await tickTo(0);
		t.arrive();
		t.busy = true;
		await tickTo(10_000);
		expect(t.poller.changed).toBe(true);
		t.poller.set(false);
		expect(t.poller.changed).toBe(false);
		expect(t.poller.pending).toBeNull();
		expect(t.poller.status).toBe('off');
		await tickTo(60_000);
		expect(t.polls).toHaveLength(2);
	});
});
