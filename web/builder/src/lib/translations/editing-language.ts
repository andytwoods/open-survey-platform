/**
 * The editing language (planning/rich-text.md §5, task RT6): which of the survey's languages
 * the builder's text fields edit. Pure helpers: the URL form (`?lang=de`), what is remembered
 * per survey, and the resolution against the survey's language list. The default language
 * is what a field edits when nothing (or nothing valid) was asked for.
 */
export const LANG_PARAM = 'lang';

/** `osp_spec.model.LanguageTag`: a 2–3 letter tag with optional subtags. */
const TAG = /^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$/;

/** The URL's `?lang=`: a well-formed tag, else null (junk is ignored, never thrown on). */
export function langFromSearch(search: string): string | null {
	const v = new URLSearchParams(search).get(LANG_PARAM)?.trim() ?? '';
	return TAG.test(v) ? v : null;
}

/**
 * `href` with `?lang=` set (a language other than the default) or removed (the default, or
 * null); the rest of the URL is untouched.
 */
export function withLang(href: string, lang: string | null): string {
	const url = new URL(href);
	if (lang) url.searchParams.set(LANG_PARAM, lang);
	else url.searchParams.delete(LANG_PARAM);
	return url.toString();
}

/** The language a field edits: the requested one when it is a survey language, else the default. */
export function resolveEditingLanguage(
	requested: string | null | undefined,
	languages: readonly string[],
	defaultLanguage: string
): string {
	return requested && languages.includes(requested) ? requested : defaultLanguage;
}

export interface LanguageOption {
	value: string;
	label: string;
}

/** The select's options: the default language first, then the others in survey order. */
export function languageOptions(languages: readonly string[], defaultLanguage: string): LanguageOption[] {
	const rest = languages.filter((l) => l !== defaultLanguage);
	const first = languages.includes(defaultLanguage) ? [defaultLanguage] : [];
	return [...first, ...rest].map((l) => ({ value: l, label: l === defaultLanguage ? `${l} (default)` : l }));
}

// -- what is remembered (localStorage; absent or broken storage means nothing is) ----------

export const storageKey = (surveyId: string): string => `osp.editing-language.${surveyId}`;
export const REFERENCE_KEY = 'osp.reference-strip';

export function rememberedLanguage(storage: Storage | null, surveyId: string): string | null {
	try {
		const v = storage?.getItem(storageKey(surveyId))?.trim() ?? '';
		return TAG.test(v) ? v : null;
	} catch {
		return null;
	}
}

export function rememberLanguage(storage: Storage | null, surveyId: string, lang: string | null): void {
	try {
		if (lang) storage?.setItem(storageKey(surveyId), lang);
		else storage?.removeItem(storageKey(surveyId));
	} catch {
		// Storage full or forbidden: the URL still carries the choice.
	}
}

/** Whether the reference strip is open (the default) or collapsed, as remembered. */
export function rememberedReferenceOpen(storage: Storage | null): boolean {
	try {
		return storage?.getItem(REFERENCE_KEY) !== 'closed';
	} catch {
		return true;
	}
}

export function rememberReferenceOpen(storage: Storage | null, open: boolean): void {
	try {
		if (open) storage?.removeItem(REFERENCE_KEY);
		else storage?.setItem(REFERENCE_KEY, 'closed');
	} catch {
		// Nothing to do: the strip just opens again next time.
	}
}
