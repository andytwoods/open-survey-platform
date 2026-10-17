/**
 * Who the host says we are (plan P: osp-api has no sign-in of its own any more).
 *
 * Interim shim by P1 so the builder still compiles after `/api/auth/*` was removed: it
 * reads `GET /api/me`, and login/TOTP/logout are stubs. P2 deletes this file along with the
 * login page, RequireAuth and the "Sign out" button.
 */
import type { components } from '@osp/api-client';
import { api, setCsrfToken } from './api';

export type Identity = components['schemas']['Identity'];
/** `email` kept for the existing header; it is the host's display name (or user id). */
export type Me = Identity & { email: string };
export type LoginStep = 'ok' | 'mfa' | 'failed' | 'offline';

class Auth {
	me = $state.raw<Me | null>(null);
	/** True once /me has answered (signed in or not). */
	checked = $state(false);

	#set(me: Identity | null) {
		this.me = me ? { ...me, email: me.displayName ?? me.userId } : null;
		setCsrfToken(null);
	}

	/** Ask the server who we are. Returns true if the host vouched for us. */
	async refresh(): Promise<boolean> {
		try {
			const { data, response } = await api.GET('/api/me');
			this.#set(response.ok && data ? data : null);
		} catch {
			this.#set(null);
		}
		this.checked = true;
		return this.me !== null;
	}

	/** Sign-in belongs to the host now: there is nothing to log in to here. */
	async login(email: string, password: string): Promise<LoginStep> {
		void email;
		void password;
		return (await this.refresh()) ? 'ok' : 'failed';
	}

	async loginTotp(code: string, recovery = false): Promise<LoginStep> {
		void code;
		void recovery;
		return (await this.refresh()) ? 'ok' : 'failed';
	}

	/** Signing out is the host's job; forget who we were locally. */
	async logout(): Promise<void> {
		this.#set(null);
	}

	/** The host session ended mid-edit (a 401): forget who we were. */
	expired() {
		this.#set(null);
	}
}

export const auth = new Auth();

/** Only same-app paths are allowed as a post-login destination (no open redirect). */
export function safeNext(next: string | null): string {
	if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/\\')) return '/';
	return next;
}
