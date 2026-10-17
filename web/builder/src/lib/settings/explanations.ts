/**
 * Plain-language help for the survey settings whose trade-offs a researcher must see when
 * choosing them (runtime-design §5.0: "the builder spells these out when the setting is
 * switched"). Display text only: what the modes do is decided by the runtime and server.
 */

export type SaveMode = 'every-page' | 'end-only';
export type LocalCopy = 'browser' | 'memory';

export interface Explanation {
	title: string;
	summary: string;
	/** What you give up or should tell participants. */
	tradeOffs: string[];
}

export const SAVE_MODES: Record<SaveMode, Explanation> = {
	'every-page': {
		title: 'Saved to the server on every page',
		summary:
			'Answers are sent to the server as participants go, so a partly finished survey is kept ' +
			'and they can resume later, even on another device, with their resume link.',
		tradeOffs: [
			'Drop-outs are visible: you get partial responses and can see where people stopped.',
			'Refreshing or closing the page loses nothing that was already saved.',
			'Partial answers are stored on the server even if the participant never submits, so ' +
				'say so in your consent text.'
		]
	},
	'end-only': {
		title: 'Nothing is sent until the participant submits',
		summary:
			'Answers, timings and URL parameters (such as Prolific IDs) stay in the browser until the ' +
			'final submit. The server only sees that a session started (its seed and condition) and ' +
			'any quota checks.',
		tradeOffs: [
			'Drop-outs are invisible: if someone leaves before the end, you get no data at all, so ' +
				'attrition cannot be measured.',
			'No resume on another device, and answers are lost if the browser crashes or clears its storage.',
			'Refreshing the page keeps the answers only with "Browser storage" below; with "Memory only" ' +
				'a refresh starts the survey again (same conditions and order).',
			'The consent text template mentions this mode, because a started session can still be ' +
				'pseudonymous personal data.'
		]
	}
};

export const LOCAL_COPIES: Record<LocalCopy, string> = {
	browser:
		'A copy is kept in the browser (IndexedDB), so a refresh resumes where the participant ' +
		'was. It is deleted on submit, and cleaned up after the resume period. If the browser ' +
		'blocks storage, the survey falls back to memory only and says so on screen.',
	memory:
		'Nothing is written to the device: closing or refreshing the window loses every answer. ' +
		'This is the strict "nothing is kept" promise.'
};

export function saveModeOf(survey: unknown): SaveMode {
	const v = settingOf(survey, 'saveMode');
	return v === 'end-only' ? 'end-only' : 'every-page';
}

export function localCopyOf(survey: unknown): LocalCopy {
	return settingOf(survey, 'localCopy') === 'memory' ? 'memory' : 'browser';
}

export function settingOf(survey: unknown, key: string): unknown {
	const s = (survey as { settings?: Record<string, unknown> } | null)?.settings;
	return s && typeof s === 'object' ? s[key] : undefined;
}
