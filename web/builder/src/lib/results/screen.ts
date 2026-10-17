/**
 * The projected screen (task LV4, planning/live-results.md §5 "Lab screen"): fullscreen
 * (the Fullscreen API, no CSP implication; it needs a user gesture, so the Present dialog's
 * button asks) and a screen wake lock while presenting live (`navigator.wakeLock`, ignored
 * where unsupported or refused; browsers release it when the tab is hidden, so it is asked
 * for again when the tab shows). Every call is best effort and never throws.
 */

interface WakeLockSentinel {
	release(): Promise<void>;
}

interface WakeLockNavigator {
	wakeLock?: { request(type: 'screen'): Promise<WakeLockSentinel> };
}

/** Keep the screen awake until the returned function is called. */
export function keepAwake(doc: Document = document, nav: WakeLockNavigator = navigator as WakeLockNavigator): () => void {
	let sentinel: WakeLockSentinel | null = null;
	let stopped = false;
	const request = async () => {
		if (!nav.wakeLock || stopped || sentinel || doc.visibilityState !== 'visible') return;
		try {
			const s = await nav.wakeLock.request('screen');
			if (stopped) await s.release();
			else sentinel = s;
		} catch {
			/* refused (battery saver, permissions policy) or unsupported: the screen may sleep */
		}
	};
	const onVisibility = () => {
		if (doc.visibilityState === 'hidden') sentinel = null; // the browser released it
		else void request();
	};
	doc.addEventListener('visibilitychange', onVisibility);
	void request();
	return () => {
		stopped = true;
		doc.removeEventListener('visibilitychange', onVisibility);
		void sentinel?.release().catch(() => undefined);
		sentinel = null;
	};
}

/** Ask for fullscreen (from a user gesture). False when refused or unsupported. */
export async function enterFullscreen(doc: Document = document): Promise<boolean> {
	try {
		if (doc.fullscreenElement) return true;
		await doc.documentElement.requestFullscreen?.();
		return !!doc.fullscreenElement;
	} catch {
		return false;
	}
}

/** Leave fullscreen if the page is in it. */
export async function exitFullscreen(doc: Document = document): Promise<void> {
	try {
		if (doc.fullscreenElement) await doc.exitFullscreen();
	} catch {
		/* already left */
	}
}
