/**
 * Theme preference: 'system' follows prefers-color-scheme; 'light' / 'dark' pin it by
 * setting <html data-theme>. The preference is remembered in localStorage when available.
 */
export type ThemePreference = 'system' | 'light' | 'dark';
export type ResolvedTheme = 'light' | 'dark';

const STORAGE_KEY = 'osp-theme';

function readStored(): ThemePreference {
	try {
		const v = globalThis.localStorage?.getItem(STORAGE_KEY);
		return v === 'light' || v === 'dark' ? v : 'system';
	} catch {
		return 'system';
	}
}

function systemPrefersDark(): boolean {
	return globalThis.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
}

class ThemeController {
	preference = $state<ThemePreference>('system');
	#systemDark = $state(false);

	get resolved(): ResolvedTheme {
		if (this.preference === 'system') return this.#systemDark ? 'dark' : 'light';
		return this.preference;
	}

	/** Call once on the client (e.g. in the root layout's onMount). Returns a cleanup. */
	init(): () => void {
		this.preference = readStored();
		this.#systemDark = systemPrefersDark();
		this.#apply();
		const mq = globalThis.matchMedia?.('(prefers-color-scheme: dark)');
		const onChange = (e: MediaQueryListEvent) => (this.#systemDark = e.matches);
		mq?.addEventListener('change', onChange);
		return () => mq?.removeEventListener('change', onChange);
	}

	set(pref: ThemePreference) {
		this.preference = pref;
		try {
			if (pref === 'system') globalThis.localStorage?.removeItem(STORAGE_KEY);
			else globalThis.localStorage?.setItem(STORAGE_KEY, pref);
		} catch {
			/* storage blocked: preference lasts for this page only */
		}
		this.#apply();
	}

	/** Flip between light and dark, starting from whatever is showing now. */
	toggle() {
		this.set(this.resolved === 'dark' ? 'light' : 'dark');
	}

	#apply() {
		const root = globalThis.document?.documentElement;
		if (!root) return;
		if (this.preference === 'system') delete root.dataset.theme;
		else root.dataset.theme = this.preference;
	}
}

export const theme = new ThemeController();
