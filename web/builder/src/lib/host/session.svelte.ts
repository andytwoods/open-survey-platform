/**
 * Whether the host's session still lets this page act (planning/pages-split.md F3, D9).
 * Sign-in belongs to the host: the page only reacts.
 *
 * - 401: the host session ended. Writes stop (api.ts answers them locally with a 401 and
 *   the survey store keeps them queued). With `onUnauthenticated: { redirect }` a banner
 *   links to the host's sign-in with `?next=` (this page). With "reload" (the default) the
 *   page reloads once so the host's login runs, but only when no edit is pending and it
 *   has not auto-reloaded in the last few minutes; otherwise the banner offers a reload.
 *   Never a reload loop.
 * - 403: "you don't have access", a different message; nothing else changes.
 */
import type { components } from '@osp/api-client';
import type { OspPageConfig } from './config';

export type Identity = components['schemas']['Identity'];
export type SessionStatus = 'ok' | 'ended' | 'forbidden';

/** sessionStorage key: when this tab last reloaded itself after a 401. */
export const RELOAD_KEY = 'osp-401-reload';
/** At most one automatic reload per this long (per tab). */
export const RELOAD_WINDOW_MS = 5 * 60_000;

export interface SessionDeps {
	now: () => number;
	reload: () => void;
	/** sessionStorage, or null when unavailable (then never auto-reload). */
	storage: Pick<Storage, 'getItem' | 'setItem'> | null;
	/** The current page, for `?next=`. */
	here: () => string;
	/** Edits waiting to be saved (they would be lost by a reload). */
	unsaved: () => boolean;
}

function browserStorage(): SessionDeps['storage'] {
	try {
		return typeof sessionStorage === 'undefined' ? null : sessionStorage;
	} catch {
		return null;
	}
}

export class Session {
	status = $state<SessionStatus>('ok');
	identity = $state.raw<Identity | null>(null);
	/** Set when the page reloads itself (the banner is not shown then). */
	reloading = $state(false);

	#mode: OspPageConfig['onUnauthenticated'] = 'reload';
	#deps: SessionDeps;

	constructor(deps: Partial<SessionDeps> = {}) {
		this.#deps = {
			now: () => Date.now(),
			reload: () => location.reload(),
			storage: browserStorage(),
			here: () => location.pathname + location.search + location.hash,
			unsaved: () => false,
			...deps
		};
	}

	configure(mode: OspPageConfig['onUnauthenticated'] | undefined, deps: Partial<SessionDeps> = {}) {
		this.#mode = mode ?? 'reload';
		this.#deps = { ...this.#deps, ...deps };
	}

	get ended(): boolean {
		return this.status === 'ended';
	}

	/** The host's sign-in URL with `next` set to this page, or null in reload mode. */
	get signInUrl(): string | null {
		const m = this.#mode;
		if (!m || m === 'reload') return null;
		const hashAt = m.redirect.indexOf('#');
		const [base, hash] = hashAt < 0 ? [m.redirect, ''] : [m.redirect.slice(0, hashAt), m.redirect.slice(hashAt)];
		const next = `next=${encodeURIComponent(this.#deps.here())}`;
		return `${base}${base.includes('?') ? '&' : '?'}${next}${hash}`;
	}

	/** A 401 arrived. */
	unauthenticated() {
		if (this.status === 'ended') return;
		this.status = 'ended';
		if (this.#mode === 'reload' && !this.#deps.unsaved() && this.#mayAutoReload()) {
			this.reloading = true;
			this.#deps.reload();
		}
	}

	/** A 403 arrived (does not override an ended session). */
	forbidden() {
		if (this.status === 'ok') this.status = 'forbidden';
	}

	dismissForbidden() {
		if (this.status === 'forbidden') this.status = 'ok';
	}

	/** The banner's "Reload" (a user action, so no loop guard). */
	reloadNow() {
		this.#deps.reload();
	}

	#mayAutoReload(): boolean {
		const s = this.#deps.storage;
		if (!s) return false;
		try {
			const last = Number(s.getItem(RELOAD_KEY) ?? 0);
			const now = this.#deps.now();
			if (Number.isFinite(last) && now - last < RELOAD_WINDOW_MS) return false;
			s.setItem(RELOAD_KEY, String(now));
			return true;
		} catch {
			return false;
		}
	}
}

export const session = new Session();
