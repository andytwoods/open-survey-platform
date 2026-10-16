/**
 * Who is signed in. Password first, then a TOTP (or recovery) code if the account has
 * one enrolled. The session itself is an HttpOnly cookie; we only keep `me` and the
 * CSRF token it carries.
 */
import type { components } from '@osp/api-client';
import { api, setCsrfToken } from './api';

export type Me = components['schemas']['Me'];
export type LoginStep = 'ok' | 'mfa' | 'failed' | 'offline';

class Auth {
	me = $state.raw<Me | null>(null);
	/** True once /me has answered (signed in or not). */
	checked = $state(false);

	#set(me: Me | null) {
		this.me = me;
		setCsrfToken(me?.csrfToken ?? null);
	}

	/** Ask the server who we are. Returns true if signed in. */
	async refresh(): Promise<boolean> {
		try {
			const { data, response } = await api.GET('/api/auth/me');
			this.#set(response.ok && data ? data : null);
		} catch {
			this.#set(null);
		}
		this.checked = true;
		return this.me !== null;
	}

	async login(email: string, password: string): Promise<LoginStep> {
		try {
			const { data, response } = await api.POST('/api/auth/login', { body: { email, password } });
			if (!response.ok || !data) return response.status >= 500 ? 'offline' : 'failed';
			if (data.status === 'mfa_required') return 'mfa';
			this.#set(data.me ?? null);
			this.checked = true;
			return this.me ? 'ok' : 'failed';
		} catch {
			return 'offline';
		}
	}

	async loginTotp(code: string, recovery = false): Promise<LoginStep> {
		try {
			const { data, response } = await api.POST('/api/auth/login/totp', { body: { code, recovery } });
			if (!response.ok || !data?.me) return response.status >= 500 ? 'offline' : 'failed';
			this.#set(data.me);
			this.checked = true;
			return 'ok';
		} catch {
			return 'offline';
		}
	}

	async logout(): Promise<void> {
		try {
			await api.POST('/api/auth/logout');
		} catch {
			// Signed out locally either way.
		}
		this.#set(null);
	}

	/** The session expired mid-edit (a 401): forget who we were. */
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
