/**
 * The editing language shared by every pane of a survey page (planning/rich-text.md §5,
 * RT-D11): one choice drives the property panel, the choice and row dialogs, the flow's End
 * cards and the consent and endings editors. Kept in the URL (`?lang=de`, so a link opens
 * the same language) and remembered per survey (localStorage, so the next page of the same
 * survey opens in it too). The reference strip's open/collapsed state is shared the same way.
 */
import { defaultLanguage } from '../model/outline';
import { languagesOf } from '../settings/model';
import {
	langFromSearch,
	rememberedLanguage,
	rememberedReferenceOpen,
	rememberLanguage,
	rememberReferenceOpen,
	resolveEditingLanguage,
	withLang
} from './editing-language';

export const editingLanguage = $state({
	/** What was asked for (URL, then remembered); null means the survey's default language. */
	requested: null as string | null,
	surveyId: '',
	/** The default-language reference above a translated field is open (not collapsed). */
	referenceOpen: true
});

function storage(): Storage | null {
	try {
		return typeof localStorage === 'undefined' ? null : localStorage;
	} catch {
		return null;
	}
}

/**
 * Read the page's URL and what is remembered for this survey. Once per page. A language in
 * the URL becomes the remembered one, so the survey's other pages open in it too.
 */
export function initEditingLanguage(surveyId: string): void {
	editingLanguage.surveyId = surveyId;
	const fromUrl = typeof location === 'undefined' ? null : langFromSearch(location.search);
	if (fromUrl) rememberLanguage(storage(), surveyId, fromUrl);
	editingLanguage.requested = fromUrl ?? rememberedLanguage(storage(), surveyId);
	editingLanguage.referenceOpen = rememberedReferenceOpen(storage());
}

/** The language the panes edit for `survey`: the request when it is a survey language, else the default. */
export function editLanguageOf(survey: unknown): string {
	return resolveEditingLanguage(editingLanguage.requested, languagesOf(survey), defaultLanguage(survey));
}

/** Choose the editing language: state, URL (`?lang=` only for a non-default language) and memory. */
export function setEditingLanguage(lang: string, defaultLang: string): void {
	editingLanguage.requested = lang;
	rememberLanguage(storage(), editingLanguage.surveyId, lang);
	if (typeof location === 'undefined' || typeof history === 'undefined') return;
	const next = withLang(location.href, lang === defaultLang ? null : lang);
	if (next !== location.href) history.replaceState(history.state, '', next);
}

export function setReferenceOpen(open: boolean): void {
	editingLanguage.referenceOpen = open;
	rememberReferenceOpen(storage(), open);
}
