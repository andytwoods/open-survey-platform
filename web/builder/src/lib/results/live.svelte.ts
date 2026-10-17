/**
 * The live poller (task LV3, planning/live-results.md §5): asks the watermark endpoint on
 * the server's interval, pauses while the tab is hidden (and polls at once on return),
 * backs off on failure, ends on 401/403, and when the watermark changes either refreshes
 * the results by itself (idle, policy allows) or shows "N new responses · Refresh" (the
 * researcher is busy). Refreshes are coalesced: at most one every `minRefreshMs`, never
 * two at once; a change seen mid-flight means one more afterwards. Presenting (task LV4,
 * LV-D5), the policy batches refreshes: k new responses or the time cap, busy ignored.
 * Pure of the DOM except `document.visibilityState`, so vitest drives it with a fake clock.
 */
import {
	batchDue,
	clampPoll,
	DEFAULT_MIN_REFRESH_MS,
	DEFAULT_POLL_MS,
	livePolicy,
	nextBackoff,
	type LivePolicy
} from './live';

export type Fetched<T> = { ok: true; data: T } | { ok: false; status: number; message: string; aborted?: boolean };

export interface Watermark {
	watermark: string;
	responses: number;
	versionsUsed: number[];
	pollAfterMs: number;
}

export interface LiveHooks {
	/** The watermark of the versions the page shows. */
	poll(signal: AbortSignal): Promise<Fetched<Watermark>>;
	/** Re-query the results. `live` marks an automatic refresh (audited as `results.live`). */
	refresh(live: boolean): Promise<boolean>;
	/** The watermark of the results on screen (null before the first load). */
	watermark(): string | null;
	/** The researcher is busy (recent input, an open menu or dialog, unapplied filters, a query in flight). */
	busy(): boolean;
	/** Where the page is (presentation mode batches refreshes and ignores "busy"). */
	policy?(): LivePolicy;
	/** The tab is hidden (default: `document.visibilityState`). */
	hidden?(): boolean;
}

export type LiveStatus = 'off' | 'waiting' | 'polling' | 'refreshing' | 'paused' | 'retrying' | 'ended';

export class LivePoller {
	on = $state(false);
	status = $state<LiveStatus>('off');
	/** Why polling is paused. */
	pausedBy = $state<'hidden' | null>(null);
	/** The watermark differs from the results on screen (the badge shows). */
	changed = $state(false);
	/** New stored responses since the results on screen; null: unknown; <= 0: removed. */
	pending = $state<number | null>(null);
	/** Stored responses of the versions at the last poll (every status, before filters). */
	responses = $state<number | null>(null);
	/** The server's interval. */
	intervalMs = $state(DEFAULT_POLL_MS);
	/** The current back-off wait after a failed poll (0: none). */
	retryMs = $state(0);
	/** The last failure, in words (a 403 ends live with it). */
	error = $state<string | null>(null);
	/** When the results were last refreshed by this poller (automatic or the Refresh button). */
	lastRefreshAt = $state<number | null>(null);
	/** Counts the poller's refreshes (the page announces each one). */
	refreshes = $state(0);
	readonly minRefreshMs: number;
	readonly #hooks: LiveHooks;
	#timer: ReturnType<typeof setTimeout> | null = null;
	#refreshTimer: ReturnType<typeof setTimeout> | null = null;
	#abort: AbortController | null = null;
	#inFlight = false;
	/** Stored responses when the watermark last matched the results on screen. */
	#known: number | null = null;
	/** The last successful poll. */
	#last: { watermark: string; responses: number } | null = null;
	/** Recent polls, newest last: what a watermark's stored count was (for a refresh overtaken mid-flight). */
	#recent: { watermark: string; responses: number }[] = [];
	/** When live was turned on: a batch's time cap runs from here until the first refresh. */
	#startedAt = 0;
	#onVisibility: (() => void) | null = null;

	constructor(hooks: LiveHooks, opts: { minRefreshMs?: number } = {}) {
		this.#hooks = hooks;
		this.minRefreshMs = opts.minRefreshMs ?? DEFAULT_MIN_REFRESH_MS;
	}

	/** Turn live on or off. */
	set(on: boolean) {
		if (on) this.start();
		else this.stop();
	}

	start() {
		if (this.on) return;
		this.on = true;
		this.error = null;
		this.retryMs = 0;
		this.changed = false;
		this.pending = null;
		this.#known = null;
		this.#last = null;
		this.#recent = [];
		this.#startedAt = Date.now();
		if (typeof document !== 'undefined' && !this.#onVisibility) {
			this.#onVisibility = () => this.#visibility();
			document.addEventListener('visibilitychange', this.#onVisibility);
		}
		this.#schedule(0);
	}

	/** Turn live off. With `reason`, it ended by itself (the status line says why). */
	stop(reason?: { status: 'ended'; error: string | null }) {
		this.#clear();
		this.#abort?.abort();
		this.#abort = null;
		if (this.#onVisibility && typeof document !== 'undefined') {
			document.removeEventListener('visibilitychange', this.#onVisibility);
			this.#onVisibility = null;
		}
		this.on = false;
		this.changed = false;
		this.pending = null;
		this.pausedBy = null;
		this.status = reason ? 'ended' : 'off';
		this.error = reason ? reason.error : null;
	}

	/** The policy may have changed (presentation mode entered or left, its cadence switched): check now. */
	wake() {
		if (!this.on || this.#inFlight) return;
		this.#schedule(0);
	}

	/** The badge's Refresh: a manual refresh (audited as `results.read`). */
	async refreshNow(): Promise<boolean> {
		return this.#refresh(false);
	}

	dispose() {
		this.stop();
	}

	#hidden(): boolean {
		if (this.#hooks.hidden) return this.#hooks.hidden();
		return typeof document !== 'undefined' && document.visibilityState === 'hidden';
	}

	#policy(): LivePolicy {
		return this.#hooks.policy?.() ?? livePolicy({ presenting: false });
	}

	#clear() {
		if (this.#timer) clearTimeout(this.#timer);
		this.#timer = null;
		if (this.#refreshTimer) clearTimeout(this.#refreshTimer);
		this.#refreshTimer = null;
	}

	/** The next poll in `ms`, and the status says so (unless a refresh or a retry is what it is). */
	#schedule(ms: number) {
		if (!this.#inFlight && this.status !== 'retrying') this.status = 'waiting';
		this.#arm(ms);
	}

	#arm(ms: number) {
		if (this.#timer) clearTimeout(this.#timer);
		this.#timer = setTimeout(() => {
			this.#timer = null;
			void this.#tick();
		}, ms);
	}

	#visibility() {
		if (!this.on) return;
		if (this.#hidden()) {
			if (this.#timer) clearTimeout(this.#timer);
			this.#timer = null;
			this.#abort?.abort();
			this.#abort = null;
			this.status = 'paused';
			this.pausedBy = 'hidden';
		} else {
			this.pausedBy = null;
			this.#schedule(0);
		}
	}

	async #tick() {
		if (!this.on) return;
		if (this.#hidden()) {
			this.status = 'paused';
			this.pausedBy = 'hidden';
			return; // visibilitychange resumes
		}
		const policy = this.#policy();
		if (!policy.poll) {
			this.status = 'paused';
			this.#arm(this.intervalMs); // checked again then, or sooner by wake()
			return;
		}
		this.pausedBy = null;
		if (!this.#inFlight) this.status = 'polling'; // a refresh in flight is the bigger news
		const abort = new AbortController();
		this.#abort = abort;
		const r = await this.#hooks.poll(abort.signal);
		if (!this.on || this.#abort !== abort) return;
		this.#abort = null;
		if (!r.ok) return this.#failed(r.status, r.message);
		this.retryMs = 0;
		this.error = null;
		this.intervalMs = clampPoll(r.data.pollAfterMs);
		this.responses = r.data.responses;
		this.#last = { watermark: r.data.watermark, responses: r.data.responses };
		if (this.#recent.at(-1)?.watermark !== r.data.watermark) this.#recent = [...this.#recent.slice(-9), this.#last];
		const current = this.#hooks.watermark();
		if (current === null || current === r.data.watermark) {
			this.#known = r.data.responses;
			this.changed = false;
			this.pending = null;
		} else {
			this.changed = true;
			this.pending = this.#known === null ? null : r.data.responses - this.#known;
			this.#maybeRefresh(policy);
		}
		if (this.on) this.#schedule(this.intervalMs);
	}

	#failed(status: number, message: string) {
		if (status === 401) return this.stop({ status: 'ended', error: null }); // the session banner says so
		if (status === 403) {
			return this.stop({
				status: 'ended',
				error: 'You no longer have access to this survey’s results, so Live is off.'
			});
		}
		this.retryMs = nextBackoff(this.retryMs, this.intervalMs);
		this.error = message || 'network error';
		this.status = 'retrying';
		this.#schedule(this.retryMs);
	}

	/**
	 * Refresh when allowed and idle, respecting `minRefreshMs`; else the badge stays. A
	 * batched policy (presenting, LV-D5) waits for k new responses or its time cap, whichever
	 * first; the cap is kept with a timer, so a quiet room still redraws on time.
	 */
	#maybeRefresh(policy: LivePolicy = this.#policy()) {
		if (!this.on || !this.changed || !policy.auto || this.#inFlight || this.#hidden()) return;
		if (!policy.ignoreBusy && this.#hooks.busy()) return;
		const now = Date.now();
		if (policy.batch) {
			const since = now - (this.lastRefreshAt ?? this.#startedAt);
			if (!batchDue(policy.batch, this.pending, since)) return this.#armRefresh(policy.batch.maxWaitMs - since);
		}
		const since = this.lastRefreshAt === null ? Infinity : now - this.lastRefreshAt;
		const wait = Math.max(0, this.minRefreshMs - since);
		if (wait > 0) return this.#armRefresh(wait);
		void this.#refresh(true);
	}

	/** Look again in `ms` (replacing an earlier, possibly longer, wait). */
	#armRefresh(ms: number) {
		if (this.#refreshTimer) clearTimeout(this.#refreshTimer);
		this.#refreshTimer = setTimeout(
			() => {
				this.#refreshTimer = null;
				this.#maybeRefresh();
			},
			Math.max(0, ms)
		);
	}

	async #refresh(live: boolean): Promise<boolean> {
		if (this.#inFlight) return false;
		this.#inFlight = true;
		this.status = 'refreshing';
		const ok = await this.#hooks.refresh(live);
		this.#inFlight = false;
		this.lastRefreshAt = Date.now();
		if (!this.on) return ok;
		if (this.status === 'refreshing') this.status = 'waiting';
		if (ok) {
			this.refreshes++;
			const now = this.#hooks.watermark();
			// The stored count of what is on screen now, if a poll saw that watermark: the new baseline.
			const seen = this.#recent.find((p) => p.watermark === now);
			if (seen) this.#known = seen.responses;
			if (this.#last && now === this.#last.watermark) {
				// Up to date with the last poll: the badge goes.
				this.changed = false;
				this.pending = null;
			} else if (this.#last) {
				// A change seen mid-flight (the poll is newer than what the query returned): once more.
				this.changed = true;
				this.pending = this.#known === null ? null : this.#last.responses - this.#known;
				this.#maybeRefresh();
			}
		}
		if (this.on && !this.#timer) this.#schedule(this.intervalMs);
		return ok;
	}
}
