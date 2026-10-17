/**
 * Presentation mode (task V6): the Results page shows only the cards, and the shell hides
 * its top bar. One module-level flag, so the shell and the page agree; the page mirrors it
 * into the URL (`?present=1`, see `presentation.ts`) so the view can be shared or printed.
 *
 * Task LV4 (planning/live-results.md LV-D5, lead decision 1) adds the presenter's choices
 * for a live screen: `refresh` (batched by default: k new responses or the time cap; or
 * every change) is a cadence a shared link may carry (`?live=batched|every`); `exact`
 * (show exact counts instead of hiding cells below k) is a deliberate switch an owner or
 * editor makes in the Present dialog, with a warning, and is never read from the URL. It
 * resets on exit, so each presentation starts suppressed.
 */
import { BATCH_K, type PresentRefresh } from './live';

class Presentation {
	active = $state(false);
	/** How the projected view refreshes while live. */
	refresh = $state<PresentRefresh>('batched');
	/** Exact counts on screen (the suppression switch is off). Never set from a URL. */
	exact = $state(false);
	/** Ask the browser for fullscreen when entering (a user gesture is needed, so the dialog does it). */
	fullscreen = $state(false);

	/** Cells with 1 … k-1 responses are hidden on screen; null when exact counts are shown. */
	get k(): number | null {
		return this.active && !this.exact ? BATCH_K : null;
	}

	enter(opts: { refresh?: PresentRefresh; exact?: boolean; fullscreen?: boolean } = {}) {
		if (opts.refresh) this.refresh = opts.refresh;
		this.exact = opts.exact === true;
		this.fullscreen = opts.fullscreen === true;
		this.active = true;
	}

	exit() {
		this.active = false;
		this.exact = false;
		this.fullscreen = false;
	}

	toggle() {
		if (this.active) this.exit();
		else this.enter();
	}
}

export const presentation = new Presentation();
