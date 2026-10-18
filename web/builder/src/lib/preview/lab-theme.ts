/**
 * The lab default theme for the preview (a survey without its own theme previews with it,
 * as it would publish). One read of the theme library (`GET /api/themes`); if that fails
 * the preview falls back to the "clean" preset, which is what a lab with no default gets.
 */
import { api } from '../api';
import type { LabDefaultTheme } from './compile';

export async function labDefaultTheme(tenantId: string | null): Promise<LabDefaultTheme | null> {
	try {
		const { data } = await api.GET('/api/themes', { params: { query: tenantId ? { tenantId } : {} } });
		const id = data?.defaultThemeId;
		const t = id ? data.themes.find((x) => x.id === id) : undefined;
		return t ? { name: t.name, theme: t.theme } : null;
	} catch {
		return null;
	}
}
