/**
 * Participant-facing strings of the app itself (widgets carry their own, ui-components
 * locale.ts). English only for now; a translated survey will need these per language.
 */
export const ui = {
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
	memoryEveryPage: 'Your browser is not keeping data for this site, so each answer is sent as soon as you give it.',
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
	startAgain: 'Start again'
};

export function fill(s: string, vars: Record<string, string | number>): string {
	return s.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m));
}
