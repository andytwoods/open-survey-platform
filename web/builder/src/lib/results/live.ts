/**
 * Live results (task LV3, planning/live-results.md LV-D1, LV-D2): the pure parts of the
 * page's polling. The page asks the cheap watermark endpoint every `pollAfterMs` (the
 * server's choice) and re-queries only when the watermark differs from the results on
 * screen; never faster than `minRefreshMs`, never while a request is in flight. The flag
 * lives in the URL (`?live=1`) and, as a setting, in a saved layout.
 */
export const LIVE_PARAM = 'live';
/** What the page assumes until the server says otherwise (OSP_LIVE_POLL_MS default). */
export const DEFAULT_POLL_MS = 10_000;
export const MIN_POLL_MS = 1_000;
export const MAX_POLL_MS = 3_600_000;
/** Automatic refreshes are at least this far apart (LV-D2). */
export const DEFAULT_MIN_REFRESH_MS = 5_000;
/** A failed poll backs off (interval, 2×, 4× …) up to this. */
export const MAX_BACKOFF_MS = 120_000;
/** Pointer or keyboard activity this recent means "busy": badge, don't yank. */
export const IDLE_AFTER_MS = 3_000;

/** The URL's live flag: on/off when present, null when absent (the layout decides). */
export function liveIn(search: string): boolean | null {
	const v = new URLSearchParams(search).get(LIVE_PARAM);
	if (v === null) return null;
	return !['0', 'off', 'false', 'no'].includes(v.trim().toLowerCase());
}

/** `href` with the live flag set or cleared (the rest of the URL untouched). */
export function withLive(href: string, on: boolean): string {
	const url = new URL(href);
	if (on) url.searchParams.set(LIVE_PARAM, '1');
	else url.searchParams.delete(LIVE_PARAM);
	return url.toString();
}

/** The server's `pollAfterMs`, within the bounds the server itself enforces. */
export function clampPoll(ms: unknown): number {
	if (typeof ms !== 'number' || !Number.isFinite(ms)) return DEFAULT_POLL_MS;
	return Math.min(MAX_POLL_MS, Math.max(MIN_POLL_MS, Math.round(ms)));
}

/** The wait after a failed poll: the interval, then double each time, capped. */
export function nextBackoff(current: number, intervalMs: number): number {
	const base = Math.max(MIN_POLL_MS, intervalMs);
	if (current <= 0) return Math.min(MAX_BACKOFF_MS, base);
	return Math.min(MAX_BACKOFF_MS, Math.max(base, current * 2));
}

/**
 * The badge's words. `pending` is new stored responses since the results on screen; null
 * when the count is unknown (the first poll already differed), 0 or less when responses
 * were removed (a withdrawal or a retention run) rather than added.
 */
export function pendingText(pending: number | null): string {
	if (pending === null) return 'New responses';
	if (pending <= 0) return 'Responses changed';
	return pending === 1 ? '1 new response' : `${pending} new responses`;
}

/**
 * What live may do where the page is (LV-D4–D6). In the app an owner or editor gets
 * polling and automatic refresh when idle. Presentation mode's live (batched, suppressed
 * by default) is task LV4: until it lands, live pauses while presenting. The viewer role
 * (plan V phase 3) will get only the batched, suppressed form through this same function.
 */
export interface LivePolicy {
	/** Poll the watermark at all. */
	poll: boolean;
	/** Refresh by itself when idle (else only the badge). */
	auto: boolean;
	/** Why polling is off, for the status line. */
	reason?: 'presentation';
}

export function livePolicy(ctx: { presenting: boolean }): LivePolicy {
	if (ctx.presenting) return { poll: false, auto: false, reason: 'presentation' };
	return { poll: true, auto: true };
}

/** "14:32" in the viewer's local time, for "updated hh:mm". */
export function clockTime(at: number): string {
	const d = new Date(at);
	return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** The status line's words (the poller's state in one short sentence). */
export function statusText(s: {
	status: 'off' | 'waiting' | 'polling' | 'refreshing' | 'paused' | 'retrying' | 'ended';
	intervalMs: number;
	retryMs: number;
	error: string | null;
	pausedBy?: 'hidden' | 'presentation' | null;
	lastRefreshAt: number | null;
}): string {
	const updated = s.lastRefreshAt === null ? '' : ` · updated ${clockTime(s.lastRefreshAt)}`;
	const every = `Checking every ${Math.round(s.intervalMs / 1000)} s`;
	switch (s.status) {
		case 'off':
			return '';
		case 'waiting':
		case 'polling':
			return `${every}${updated}`;
		case 'refreshing':
			return `Refreshing…${updated}`;
		case 'paused':
			return s.pausedBy === 'presentation' ? 'Paused while presenting' : `Paused while the tab is hidden${updated}`;
		case 'retrying':
			return `Could not check for new responses${s.error ? ` (${s.error})` : ''}. Trying again in ${Math.round(s.retryMs / 1000)} s.`;
		case 'ended':
			return s.error ?? 'Live is off.';
	}
}
