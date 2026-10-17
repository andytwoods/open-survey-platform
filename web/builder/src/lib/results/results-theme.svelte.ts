/**
 * The Results page's theme state (task V6): the choice, the survey's own theme, the lab
 * library (loaded once through the `ResultsSource`) and what they resolve to. The view
 * supplies the app's light/dark mode; everything else is derived here.
 */
import type { Mode, Theme } from '@osp/ui-components';
import type { ChartContrastProblem } from './charts/theme';
import type { ThemeTokens } from './charts/types';
import {
	APP_THEME,
	describeExportTheme,
	exportMode,
	type LibraryThemeRef,
	resolveTheme,
	type ResolvedTheme,
	screenMode,
	type ThemeChoice,
	themeProblems,
	themeTokens
} from './results-theme';

export interface ThemeLibraryList {
	themes: LibraryThemeRef[];
	defaultThemeId: string | null;
}

export type ThemeLibraryLoader = () => Promise<{ ok: true; data: ThemeLibraryList } | { ok: false; message: string }>;

export class ResultsTheme {
	choice = $state<ThemeChoice>(APP_THEME);
	surveyTheme = $state<Theme | null>(null);
	library = $state<LibraryThemeRef[]>([]);
	labDefaultId = $state<string | null>(null);
	loaded = $state(false);
	/** Why the library could not be listed (the picker still offers presets and the survey's theme). */
	error = $state<string | null>(null);

	get resolved(): ResolvedTheme {
		return resolveTheme(this.choice, { surveyTheme: this.surveyTheme, library: this.library, labDefaultId: this.labDefaultId });
	}

	/** The theme to draw with on screen (null: the app's colours). */
	get theme(): Theme | null {
		return this.resolved.theme;
	}

	/** The mode the cards show in, given the app's mode. */
	mode(appMode: Mode): Mode {
		const t = this.theme;
		return t ? screenMode(t, appMode) : appMode;
	}

	/** Chart tokens on screen, or null for the app's own tokens. */
	tokens(appMode: Mode): ThemeTokens | null {
		return themeTokens(this.theme, this.mode(appMode));
	}

	/** Chart tokens for exports, or null for the publication look. */
	get exportTokens(): ThemeTokens | null {
		const t = this.theme;
		return t ? themeTokens(t, exportMode(t)) : null;
	}

	/** The manifest's theme line. */
	get exportDescription(): string {
		return describeExportTheme(this.resolved);
	}

	/** Chart contrast problems of the theme as shown on screen. */
	problems(appMode: Mode): ChartContrastProblem[] {
		return themeProblems(this.theme, this.mode(appMode));
	}

	choose(choice: ThemeChoice) {
		this.choice = choice;
	}

	/** List the lab library once (a failure leaves the presets and the survey's theme). */
	async load(list: ThemeLibraryLoader | undefined): Promise<void> {
		if (this.loaded || !list) {
			this.loaded = true;
			return;
		}
		const r = await list();
		if (r.ok) {
			this.library = r.data.themes;
			this.labDefaultId = r.data.defaultThemeId;
			this.error = null;
		} else {
			this.error = r.message;
		}
		this.loaded = true;
	}
}
