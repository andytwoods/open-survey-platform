/**
 * The lab's panel profile (`/api/panel-profile`, task B21) as the profile page uses it:
 * load (with the stock schemas it is an overlay on), save, clear. Every call returns a
 * message for the page; nothing here throws.
 */
import { api } from '../api';
import type { PropertySchemasDoc } from '../properties/types';
import type { ProfileDocument } from './logic';

export interface ProfileDiagnostic {
	severity: string;
	code: string;
	message: string;
	pointer: string;
}

export type ProfileResult = { ok: true } | { ok: false; message: string; diagnostics?: ProfileDiagnostic[] };

function messageOf(error: unknown, status: number): string {
	const m = (error as { message?: unknown } | undefined)?.message;
	return typeof m === 'string' ? m : `Request failed (${status}).`;
}

function diagnosticsOf(error: unknown): ProfileDiagnostic[] | undefined {
	const d = (error as { diagnostics?: unknown } | undefined)?.diagnostics;
	return Array.isArray(d) ? (d as ProfileDiagnostic[]) : undefined;
}

export class ProfileLibrary {
	profile = $state.raw<ProfileDocument | null>(null);
	stock = $state.raw<PropertySchemasDoc | null>(null);
	diagnostics = $state.raw<ProfileDiagnostic[]>([]);
	canManage = $state(false);
	updatedBy = $state<string | null>(null);
	loaded = $state(false);
	error = $state<string | null>(null);

	async load(): Promise<void> {
		try {
			const [p, s] = await Promise.all([api.GET('/api/panel-profile'), api.GET('/api/meta/property-schemas')]);
			if (p.data && s.data) {
				this.profile = (p.data.profile as ProfileDocument | null) ?? null;
				this.diagnostics = p.data.diagnostics as ProfileDiagnostic[];
				this.canManage = p.data.canManage;
				this.updatedBy = p.data.updatedBy ?? null;
				this.stock = s.data as unknown as PropertySchemasDoc;
				this.error = null;
			} else this.error = p.data ? messageOf(s.error, s.response.status) : messageOf(p.error, p.response.status);
		} catch (e) {
			this.error = (e as Error)?.message || 'Network error';
		}
		this.loaded = true;
	}

	async save(profile: ProfileDocument): Promise<ProfileResult> {
		try {
			const r = await api.PUT('/api/panel-profile', { body: { profile: profile as Record<string, unknown> } });
			if (!r.data) return { ok: false, message: messageOf(r.error, r.response.status), diagnostics: diagnosticsOf(r.error) };
			this.profile = (r.data.profile as ProfileDocument | null) ?? null;
			this.diagnostics = r.data.diagnostics as ProfileDiagnostic[];
			this.updatedBy = r.data.updatedBy ?? null;
			return { ok: true };
		} catch (e) {
			return { ok: false, message: (e as Error)?.message || 'Network error' };
		}
	}

	async clear(): Promise<ProfileResult> {
		try {
			const r = await api.DELETE('/api/panel-profile');
			if (r.response.status !== 204) return { ok: false, message: messageOf(r.error, r.response.status) };
			this.profile = null;
			this.diagnostics = [];
			this.updatedBy = null;
			return { ok: true };
		} catch (e) {
			return { ok: false, message: (e as Error)?.message || 'Network error' };
		}
	}
}
