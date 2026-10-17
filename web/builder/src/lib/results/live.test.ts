import { describe, expect, it } from 'vitest';
import {
	BATCH_K,
	BATCH_MAX_WAIT_MS,
	batchDue,
	clampPoll,
	clockTime,
	DEFAULT_POLL_MS,
	liveIn,
	liveModeIn,
	livePolicy,
	MAX_BACKOFF_MS,
	nextBackoff,
	pendingText,
	presentFooter,
	statusText,
	withLive
} from './live';

// Live results (task LV3), the pure parts: the URL flag, the server's interval, back-off,
// the badge's and status line's words, and the policy seam (LV-D4–D6). Task LV4 adds the
// presentation cadence in the flag, the batch rule and the projected footer's words.

describe('the ?live= flag', () => {
	it('reads on, off and absent', () => {
		expect(liveIn('')).toBeNull();
		expect(liveIn('?present=1')).toBeNull();
		expect(liveIn('?live=1')).toBe(true);
		expect(liveIn('?live=on')).toBe(true);
		expect(liveIn('?live=every')).toBe(true);
		expect(liveIn('?live=batched')).toBe(true);
		expect(liveIn('?live=')).toBe(true);
		expect(liveIn('?live=0')).toBe(false);
		expect(liveIn('?live=off')).toBe(false);
		expect(liveIn('?live=False')).toBe(false);
	});

	it('writes live=1 and clears it, touching nothing else', () => {
		expect(withLive('https://x.test/surveys/s1/results?layout=l1', true)).toBe('https://x.test/surveys/s1/results?layout=l1&live=1');
		expect(withLive('https://x.test/surveys/s1/results?live=1&present=1', false)).toBe('https://x.test/surveys/s1/results?present=1');
		expect(withLive('https://x.test/surveys/s1/results', false)).toBe('https://x.test/surveys/s1/results');
	});

	it('carries the presentation cadence (LV4): "every" as the value, batched as the plain flag; never the suppression switch', () => {
		expect(liveModeIn('?live=every')).toBe('every');
		expect(liveModeIn('?live=batched')).toBe('batched');
		expect(liveModeIn('?live=Every')).toBe('every');
		expect(liveModeIn('?live=1')).toBeNull();
		expect(liveModeIn('?live=0')).toBeNull();
		expect(liveModeIn('?live=exact')).toBeNull();
		expect(liveModeIn('')).toBeNull();
		expect(withLive('https://x.test/r', true, 'every')).toBe('https://x.test/r?live=every');
		expect(withLive('https://x.test/r?live=every', true, 'batched')).toBe('https://x.test/r?live=1');
		expect(withLive('https://x.test/r?live=every', false, 'every')).toBe('https://x.test/r');
	});
});

describe('intervals', () => {
	it('clamps the server’s pollAfterMs to the server’s own bounds', () => {
		expect(clampPoll(10_000)).toBe(10_000);
		expect(clampPoll(1)).toBe(1_000);
		expect(clampPoll(99_999_999)).toBe(3_600_000);
		expect(clampPoll('fast')).toBe(DEFAULT_POLL_MS);
		expect(clampPoll(NaN)).toBe(DEFAULT_POLL_MS);
		expect(clampPoll(2499.6)).toBe(2500);
	});

	it('backs off from the interval, doubling to the cap, from wherever it is', () => {
		expect(nextBackoff(0, 10_000)).toBe(10_000);
		expect(nextBackoff(10_000, 10_000)).toBe(20_000);
		expect(nextBackoff(20_000, 10_000)).toBe(40_000);
		expect(nextBackoff(40_000, 10_000)).toBe(80_000);
		expect(nextBackoff(80_000, 10_000)).toBe(MAX_BACKOFF_MS);
		expect(nextBackoff(MAX_BACKOFF_MS, 10_000)).toBe(MAX_BACKOFF_MS);
		expect(nextBackoff(0, 500)).toBe(1_000); // never below the floor
		expect(nextBackoff(2_000, 10_000)).toBe(10_000); // never below the interval
	});
});

describe('words', () => {
	it('the badge counts new responses, or says what it knows', () => {
		expect(pendingText(1)).toBe('1 new response');
		expect(pendingText(3)).toBe('3 new responses');
		expect(pendingText(null)).toBe('New responses');
		expect(pendingText(0)).toBe('Responses changed');
		expect(pendingText(-2)).toBe('Responses changed');
	});

	it('the status line says what the poller is doing', () => {
		const base = { intervalMs: 10_000, retryMs: 0, error: null, lastRefreshAt: null } as const;
		expect(statusText({ ...base, status: 'off' })).toBe('');
		expect(statusText({ ...base, status: 'waiting' })).toBe('Checking every 10 s');
		expect(statusText({ ...base, status: 'polling', lastRefreshAt: new Date(2026, 9, 17, 14, 32).getTime() })).toBe('Checking every 10 s · updated 14:32');
		expect(statusText({ ...base, status: 'refreshing' })).toBe('Refreshing…');
		expect(statusText({ ...base, status: 'paused' })).toBe('Paused while the tab is hidden');
		expect(statusText({ ...base, status: 'retrying', retryMs: 20_000, error: 'Network error.' })).toBe(
			'Could not check for new responses (Network error.). Trying again in 20 s.'
		);
		expect(statusText({ ...base, status: 'ended', error: 'No access.' })).toBe('No access.');
		expect(statusText({ ...base, status: 'ended' })).toBe('Live is off.');
		expect(clockTime(new Date(2026, 0, 1, 9, 5).getTime())).toBe('09:05');
	});

	it('the projected footer (LV-D5) says the count, the time and what is hidden; never a delta', () => {
		const at = new Date(2026, 9, 17, 14, 32).getTime();
		expect(presentFooter({ responses: 142, updatedAt: at, live: true, k: 5 })).toBe('142 responses · updated 14:32 · live · counts below 5 hidden');
		expect(presentFooter({ responses: 1, updatedAt: at, live: false, k: null })).toBe('1 response · updated 14:32');
		expect(presentFooter({ responses: 0, updatedAt: null, live: true, k: null })).toBe('0 responses · live');
		expect(presentFooter({ responses: 7, updatedAt: at, live: true, k: 5 })).not.toMatch(/new/);
	});
});

describe('policy (LV-D4–D6)', () => {
	it('in the app: poll and refresh when idle; presenting: batched by default, busy ignored, or every change on request', () => {
		expect(livePolicy({ presenting: false })).toEqual({ poll: true, auto: true });
		expect(livePolicy({ presenting: false, refresh: 'every' })).toEqual({ poll: true, auto: true });
		expect(livePolicy({ presenting: true })).toEqual({ poll: true, auto: true, ignoreBusy: true, batch: { k: BATCH_K, maxWaitMs: BATCH_MAX_WAIT_MS } });
		expect(livePolicy({ presenting: true, refresh: 'batched' })).toEqual({ poll: true, auto: true, ignoreBusy: true, batch: { k: 5, maxWaitMs: 600_000 } });
		expect(livePolicy({ presenting: true, refresh: 'every' })).toEqual({ poll: true, auto: true, ignoreBusy: true });
	});

	it('a batch is due at k new responses or at the time cap, whichever first; unknown or removed never counts as k', () => {
		const batch = { k: 5, maxWaitMs: 600_000 };
		expect(batchDue(batch, 4, 0)).toBe(false);
		expect(batchDue(batch, 5, 0)).toBe(true);
		expect(batchDue(batch, 9, 0)).toBe(true);
		expect(batchDue(batch, 1, 599_999)).toBe(false);
		expect(batchDue(batch, 1, 600_000)).toBe(true);
		expect(batchDue(batch, null, 0)).toBe(false);
		expect(batchDue(batch, null, 600_000)).toBe(true);
		expect(batchDue(batch, -2, 0)).toBe(false);
		expect(batchDue(batch, 0, 0)).toBe(false);
	});
});
