/**
 * The lab theme library (`/api/themes`, task B12) as the Appearance view uses it: list,
 * save (create, or update the theme it was loaded from), and make a theme the lab default.
 * Every call returns a message for the view; nothing here throws.
 */
import type { Theme } from '@osp/ui-components';
import { api } from '../api';

export interface LibraryTheme {
	id: string;
	name: string;
	theme: Theme;
	isDefault: boolean;
	diagnostics: { severity: string; code: string; message: string; pointer: string }[];
}

export type LibraryResult = { ok: true; theme?: LibraryTheme } | { ok: false; message: string };

function messageOf(error: unknown, status: number): string {
	const m = (error as { message?: unknown } | undefined)?.message;
	return typeof m === 'string' ? m : `Request failed (${status}).`;
}

export class ThemeLibrary {
	themes = $state.raw<LibraryTheme[]>([]);
	defaultId = $state<string | null>(null);
	canManage = $state(false);
	loaded = $state(false);
	error = $state<string | null>(null);

	async load(): Promise<void> {
		try {
			const { data, error, response } = await api.GET('/api/themes');
			if (data) {
				this.themes = data.themes as unknown as LibraryTheme[];
				this.defaultId = data.defaultThemeId ?? null;
				this.canManage = data.canManage;
				this.error = null;
			} else this.error = messageOf(error, response.status);
		} catch (e) {
			this.error = (e as Error)?.message || 'Network error';
		}
		this.loaded = true;
	}

	byName(name: string): LibraryTheme | undefined {
		return this.themes.find((t) => t.name === name.trim());
	}

	/** Save under `name`: updates the library theme of that name, else creates one. */
	async save(name: string, theme: Theme): Promise<LibraryResult> {
		const existing = this.byName(name);
		try {
			const r = existing
				? await api.PATCH('/api/themes/{theme_id}', {
						params: { path: { theme_id: existing.id } },
						body: { theme: theme as unknown as Record<string, unknown> }
					})
				: await api.POST('/api/themes', {
						body: { name: name.trim(), theme: theme as unknown as Record<string, unknown> }
					});
			if (!r.data) return { ok: false, message: messageOf(r.error, r.response.status) };
			await this.load();
			return { ok: true, theme: r.data as unknown as LibraryTheme };
		} catch (e) {
			return { ok: false, message: (e as Error)?.message || 'Network error' };
		}
	}

	async makeDefault(id: string | null): Promise<LibraryResult> {
		try {
			const r = await api.PUT('/api/themes/default', { body: { themeId: id } });
			if (!r.data) return { ok: false, message: messageOf(r.error, r.response.status) };
			this.themes = r.data.themes as unknown as LibraryTheme[];
			this.defaultId = r.data.defaultThemeId ?? null;
			return { ok: true };
		} catch (e) {
			return { ok: false, message: (e as Error)?.message || 'Network error' };
		}
	}

	async remove(id: string): Promise<LibraryResult> {
		try {
			const r = await api.DELETE('/api/themes/{theme_id}', { params: { path: { theme_id: id } } });
			if (r.response.status !== 204) return { ok: false, message: messageOf(r.error, r.response.status) };
			await this.load();
			return { ok: true };
		} catch (e) {
			return { ok: false, message: (e as Error)?.message || 'Network error' };
		}
	}
}
