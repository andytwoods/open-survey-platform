import { describe, expect, it } from 'vitest';
import {
	clampPoll,
	clockTime,
	DEFAULT_POLL_MS,
	liveIn,
	livePolicy,
	MAX_BACKOFF_MS,
	nextBackoff,
	pendingText,
	statusText,
	withLive
} from './live';

// Live results (task LV3), the pure parts: the URL flag, the server's interval, back-off,
// the badge's and status line's words, and the policy seam (LV-D4–D6).

describe('the ?live= flag', () => {
	it('reads on, off and absent', () => {
		expect(liveIn('')).toBeNull();
		expect(liveIn('?present=1')).toBeNull();
		expect(liveIn('?live=1')).toBe(true);
		expect(liveIn('?live=on')).toBe(true);
		expect(liveIn('?live=every')).toBe(true);
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
		const base = { intervalMs: 10_000, retryMs: 0, error: null, lastRefreshAt: null, pausedBy: null } as const;
		expect(statusText({ ...base, status: 'off' })).toBe('');
		expect(statusText({ ...base, status: 'waiting' })).toBe('Checking every 10 s');
		expect(statusText({ ...base, status: 'polling', lastRefreshAt: new Date(2026, 9, 17, 14, 32).getTime() })).toBe('Checking every 10 s · updated 14:32');
		expect(statusText({ ...base, status: 'refreshing' })).toBe('Refreshing…');
		expect(statusText({ ...base, status: 'paused', pausedBy: 'hidden' })).toBe('Paused while the tab is hidden');
		expect(statusText({ ...base, status: 'paused', pausedBy: 'presentation' })).toBe('Paused while presenting');
		expect(statusText({ ...base, status: 'retrying', retryMs: 20_000, error: 'Network error.' })).toBe(
			'Could not check for new responses (Network error.). Trying again in 20 s.'
		);
		expect(statusText({ ...base, status: 'ended', error: 'No access.' })).toBe('No access.');
		expect(statusText({ ...base, status: 'ended' })).toBe('Live is off.');
		expect(clockTime(new Date(2026, 0, 1, 9, 5).getTime())).toBe('09:05');
	});
});

describe('policy (LV-D4–D6)', () => {
	it('in the app: poll and refresh when idle; presenting: paused until LV4', () => {
		expect(livePolicy({ presenting: false })).toEqual({ poll: true, auto: true });
		expect(livePolicy({ presenting: true })).toEqual({ poll: false, auto: false, reason: 'presentation' });
	});
});
