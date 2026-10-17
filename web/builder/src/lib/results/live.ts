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
/**
 * Presentation mode's batched refresh (task LV4, LV-D5, lead decision 1): the projected
 * view redraws when at least this many new responses have arrived, or when this long has
 * passed since the last refresh, whichever first. The same k hides small cells on screen.
 */
export const BATCH_K = 5;
export const BATCH_MAX_WAIT_MS = 600_000;

/** How presentation mode refreshes: in batches (the default) or on every change. */
export type PresentRefresh = 'batched' | 'every';

const OFF = ['0', 'off', 'false', 'no'];

/** The URL's live flag: on/off when present, null when absent (the layout decides). */
export function liveIn(search: string): boolean | null {
	const v = new URLSearchParams(search).get(LIVE_PARAM);
	if (v === null) return null;
	return !OFF.includes(v.trim().toLowerCase());
}

/**
 * The URL's presentation cadence (`?live=batched|every`), null when the flag is absent, off
 * or a plain `1`. The URL never carries the suppression switch (lead decision 1).
 */
export function liveModeIn(search: string): PresentRefresh | null {
	const v = new URLSearchParams(search).get(LIVE_PARAM)?.trim().toLowerCase();
	return v === 'batched' || v === 'every' ? v : null;
}

/**
 * `href` with the live flag set or cleared (the rest of the URL untouched). `mode` 'every'
 * is written as the flag's value, so a lab-screen link carries the cadence; batched is the
 * default and reads as `1`.
 */
export function withLive(href: string, on: boolean, mode: PresentRefresh = 'batched'): string {
	const url = new URL(href);
	if (on) url.searchParams.set(LIVE_PARAM, mode === 'every' ? 'every' : '1');
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
 * polling and automatic refresh when idle. Presentation mode (task LV4, LV-D5) refreshes
 * in batches by default: only when `batch.k` new responses have arrived or `batch.maxWaitMs`
 * have passed since the last refresh, so a projected screen never shows one person's
 * answers land; nobody is "busy" on a lab screen, so refreshes are never held for the
 * badge. The presenter can choose every change instead. The viewer role (plan V phase 3)
 * will get only the batched form through this same function.
 */
export interface LivePolicy {
	/** Poll the watermark at all. */
	poll: boolean;
	/** Refresh by itself when idle (else only the badge). */
	auto: boolean;
	/** Refresh even while the page counts as busy (presentation: no one is working on it). */
	ignoreBusy?: boolean;
	/** Batched refresh: wait for `k` new responses or `maxWaitMs` since the last refresh. */
	batch?: { k: number; maxWaitMs: number };
}

export function livePolicy(ctx: { presenting: boolean; refresh?: PresentRefresh }): LivePolicy {
	if (ctx.presenting) {
		const policy: LivePolicy = { poll: true, auto: true, ignoreBusy: true };
		if (ctx.refresh !== 'every') policy.batch = { k: BATCH_K, maxWaitMs: BATCH_MAX_WAIT_MS };
		return policy;
	}
	return { poll: true, auto: true };
}

/**
 * Whether a batched policy refreshes now (LV-D5). `pending` is new responses since the
 * results on screen (null: unknown, so it does not count as enough; removals count as
 * nothing new); `sinceMs` the time since the last refresh (or since live started).
 */
export function batchDue(batch: { k: number; maxWaitMs: number }, pending: number | null, sinceMs: number): boolean {
	return (pending !== null && pending >= batch.k) || sinceMs >= batch.maxWaitMs;
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
			return `Paused while the tab is hidden${updated}`;
		case 'retrying':
			return `Could not check for new responses${s.error ? ` (${s.error})` : ''}. Trying again in ${Math.round(s.retryMs / 1000)} s.`;
		case 'ended':
			return s.error ?? 'Live is off.';
	}
}

/**
 * Presentation mode's footer (LV-D5): the response count and when the screen was last
 * drawn, plus what is hidden. Never the size of the last delta, never "N new".
 */
export function presentFooter(s: {
	responses: number;
	/** When the results on screen were received. */
	updatedAt: number | null;
	live: boolean;
	/** Small cells hidden below this on screen; null when exact counts are shown. */
	k: number | null;
}): string {
	const parts = [`${s.responses} ${s.responses === 1 ? 'response' : 'responses'}`];
	if (s.updatedAt !== null) parts.push(`updated ${clockTime(s.updatedAt)}`);
	if (s.live) parts.push('live');
	if (s.k !== null) parts.push(`counts below ${s.k} hidden`);
	return parts.join(' · ');
}
