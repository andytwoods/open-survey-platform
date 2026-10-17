/**
 * Participant-facing strings of the app itself (widgets carry their own, ui-components
 * locale.ts), one table per language, keyed by the session's plan language. `ui` is the
 * live table: `useLanguage` switches it once the session language is known (before the
 * survey renders). A language without a table falls back to English, key by key.
 */
const en = {
	next: 'Next',
	back: 'Back',
	checking: 'Please wait…',
	required: 'Answer this question.',
	constraint: 'Check this answer.',
	invalid: 'Enter a valid answer.',
	errorSummaryTitle: 'There is a problem',
	page: 'Page {n}',
	saved: 'Saved',
	saving: 'Saving…',
	// Short: the status sits between the nav buttons and must not reflow them.
	offline: 'Offline · saved on this device',
	offlineNoStorage: 'Offline · keep this page open',
	memoryEndOnly:
		'Your browser is not keeping data for this site. Your answers stay only in this window until you finish: closing or refreshing it will lose them.',
	memoryChosen: 'Your answers stay only in this window until you finish: closing or refreshing it will lose them.',
	memoryEveryPage: 'Your browser is not keeping data for this site, so each answer is sent as soon as you give it.',
	restarted:
		'This page was refreshed, so the answers kept only in this window were lost. The survey has started again from the beginning.',
	conflict:
		'This survey was updated on another device. You are now seeing the latest saved answers from there; please check them before you go on.',
	loading: 'Loading the survey…',
	submitting: 'Sending your answers…',
	submittingOffline: 'Waiting for a connection to send your answers. Please keep this page open.',
	thanksTitle: 'Thank you',
	thanks: 'Your answers have been sent.',
	continueLater: 'Continue on another device',
	continueHelp: 'Open this private link to carry on where you left off. Anyone with the link can see your answers.',
	copy: 'Copy link',
	copied: 'Link copied',
	problem: 'Something went wrong',
	retry: 'Try again',
	startAgain: 'Start again',
	hookRetry: 'Part of this survey did not respond. Please try again.',
	expiredSave: 'This session has expired, so your answers can no longer be saved.',
	expiredSubmit: 'This session has expired, so your answers could not be submitted.',
	submitFailed: 'Your answers could not be submitted. Please keep this page open and contact the research team.',
	quotaFailed: 'Something went wrong checking your place in this survey. Please contact the research team.',
	notFound: 'This survey link is not valid.',
	closed: 'This survey is closed.',
	expired: 'This session has expired.',
	tooMany: 'Too many attempts. Please try again in a minute.',
	refused: 'The server refused the request ({code}).',
	unreachable: 'Could not reach the survey server. Check your connection and try again.',
	planChecksum: 'The survey could not be loaded (its checksum does not match).',
	planNewer: 'This survey needs a newer version of the survey app.',
	restoreFailed: 'The saved answers could not be restored.',
	redirecting: 'Taking you back…',
	hooksFailed: 'This survey could not start its custom code. Please contact the research team.'
};

export type Strings = typeof en;

const de: Strings = {
	next: 'Weiter',
	back: 'Zurück',
	checking: 'Bitte warten…',
	required: 'Bitte beantworten Sie diese Frage.',
	constraint: 'Bitte prüfen Sie diese Antwort.',
	invalid: 'Bitte geben Sie eine gültige Antwort ein.',
	errorSummaryTitle: 'Es gibt ein Problem',
	page: 'Seite {n}',
	saved: 'Gespeichert',
	saving: 'Wird gespeichert…',
	offline: 'Offline · auf diesem Gerät gespeichert',
	offlineNoStorage: 'Offline · Seite bitte offen lassen',
	memoryEndOnly:
		'Ihr Browser speichert keine Daten für diese Seite. Ihre Antworten bleiben nur in diesem Fenster, bis Sie fertig sind: Schließen oder Neuladen löscht sie.',
	memoryChosen: 'Ihre Antworten bleiben nur in diesem Fenster, bis Sie fertig sind: Schließen oder Neuladen löscht sie.',
	memoryEveryPage: 'Ihr Browser speichert keine Daten für diese Seite, daher wird jede Antwort sofort gesendet.',
	restarted:
		'Die Seite wurde neu geladen, deshalb sind die nur in diesem Fenster gehaltenen Antworten verloren. Die Umfrage beginnt von vorn.',
	conflict:
		'Diese Umfrage wurde auf einem anderen Gerät weitergeführt. Sie sehen jetzt die dort zuletzt gespeicherten Antworten; bitte prüfen Sie sie, bevor Sie fortfahren.',
	loading: 'Die Umfrage wird geladen…',
	submitting: 'Ihre Antworten werden gesendet…',
	submittingOffline: 'Warten auf eine Verbindung, um Ihre Antworten zu senden. Bitte lassen Sie diese Seite offen.',
	thanksTitle: 'Vielen Dank',
	thanks: 'Ihre Antworten wurden gesendet.',
	continueLater: 'Auf einem anderen Gerät fortfahren',
	continueHelp:
		'Öffnen Sie diesen privaten Link, um dort weiterzumachen, wo Sie aufgehört haben. Wer den Link hat, kann Ihre Antworten sehen.',
	copy: 'Link kopieren',
	copied: 'Link kopiert',
	problem: 'Etwas ist schiefgelaufen',
	retry: 'Erneut versuchen',
	startAgain: 'Neu beginnen',
	hookRetry: 'Ein Teil dieser Umfrage hat nicht reagiert. Bitte versuchen Sie es erneut.',
	expiredSave: 'Diese Sitzung ist abgelaufen, daher können Ihre Antworten nicht mehr gespeichert werden.',
	expiredSubmit: 'Diese Sitzung ist abgelaufen, daher konnten Ihre Antworten nicht gesendet werden.',
	submitFailed:
		'Ihre Antworten konnten nicht gesendet werden. Bitte lassen Sie diese Seite offen und wenden Sie sich an das Forschungsteam.',
	quotaFailed: 'Beim Prüfen Ihres Platzes in dieser Umfrage ist ein Fehler aufgetreten. Bitte wenden Sie sich an das Forschungsteam.',
	notFound: 'Dieser Umfragelink ist nicht gültig.',
	closed: 'Diese Umfrage ist geschlossen.',
	expired: 'Diese Sitzung ist abgelaufen.',
	tooMany: 'Zu viele Versuche. Bitte versuchen Sie es in einer Minute erneut.',
	refused: 'Der Server hat die Anfrage abgelehnt ({code}).',
	unreachable: 'Der Umfrageserver ist nicht erreichbar. Bitte prüfen Sie Ihre Verbindung und versuchen Sie es erneut.',
	planChecksum: 'Die Umfrage konnte nicht geladen werden (ihre Prüfsumme stimmt nicht).',
	planNewer: 'Diese Umfrage braucht eine neuere Version der Umfrage-App.',
	restoreFailed: 'Die gespeicherten Antworten konnten nicht wiederhergestellt werden.',
	redirecting: 'Sie werden zurückgeleitet…',
	hooksFailed: 'Diese Umfrage konnte ihren eigenen Programmcode nicht starten. Bitte wenden Sie sich an das Forschungsteam.'
};

/** App string tables by primary language subtag. */
export const STRINGS: Record<string, Strings> = { en, de };

/** The table for a language tag (`de-AT` → `de`), English if there is none. */
export function stringsFor(lang: string | null | undefined): Strings {
	const primary = (lang ?? '').toLowerCase().split(/[-_]/)[0] ?? '';
	return STRINGS[primary] ?? en;
}

/** The live table. Mutated in place by `useLanguage`, so imports stay valid. */
export const ui: Strings = { ...en };

/** Switch the app strings to `lang`'s table. Returns the table. */
export function useLanguage(lang: string | null | undefined): Strings {
	Object.assign(ui, stringsFor(lang));
	return ui;
}

export function fill(s: string, vars: Record<string, string | number>): string {
	return s.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m));
}

/**
 * Language negotiation: the participant's preferred languages (navigator.languages, most
 * preferred first) against the plan's languages. Per preference: an exact match (case
 * insensitive), then the same primary language (`de-DE` → `de`, `de` → `de-AT`). If no
 * preference matches, the plan's default language.
 */
export function negotiateLanguage(
	preferred: readonly string[] | null | undefined,
	available: readonly string[],
	fallback: string
): string {
	const norm = (s: string) => s.trim().toLowerCase().replace(/_/g, '-');
	const primary = (s: string) => norm(s).split('-')[0] ?? '';
	for (const raw of preferred ?? []) {
		if (typeof raw !== 'string' || !raw.trim()) continue;
		const exact = available.find((a) => norm(a) === norm(raw));
		if (exact) return exact;
		const p = primary(raw);
		const base = available.find((a) => norm(a) === p);
		if (base) return base;
		const sibling = available.find((a) => primary(a) === p);
		if (sibling) return sibling;
	}
	return available.includes(fallback) ? fallback : (available[0] ?? fallback);
}
