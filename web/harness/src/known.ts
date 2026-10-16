/**
 * Runtime bugs the harness found and reported (task R4: report, don't fix the app or the
 * engine). Each entry is an expected failure (`test.fail`) with an issue note. When the
 * app is fixed the test passes, Playwright reports "expected to fail, but passed", and the
 * entry must be removed.
 *
 * Key: `<fixture>/<script id>`. `projects`: only on these device projects (default: all).
 */
export interface KnownBug {
	issue: string;
	projects?: string[];
}

export const KNOWN_RUNTIME_BUGS: Record<string, KnownBug> = {
	'04-text-whitespace/whitespace': {
		issue:
			'R4-1: every text question renders as a one-line <input> (Question.svelte never sets TextInput `multiline`; ' +
			'osp-survey/0.1 has no long-text flag), so a participant cannot enter line breaks: t_lines ' +
			'"waves on the shore\\n\\n  gulls  overhead" is stored with the newlines turned into spaces (semantics §2 keeps internal whitespace).'
	},
	'23-refresh-every-step/arm-a': {
		issue:
			'R4-2: after a refresh, the constraint error of the last failed Next is shown again (steps[6].errors.age). ' +
			'FORMAT.md §3: errors only come from a `next` in that step; the engine runner and R3 both say a reloaded page shows none. ' +
			'App.svelte renders view().errors, which the restored engine state still holds.'
	},
	'30-regression-server-resume/storage-blocked': {
		issue:
			'R4-3: with IndexedDB blocked (private mode) a refresh starts a NEW session: nothing in the page remembers the ' +
			'session id or resume token, so the answers already saved on the server (R-1) are never resumed and the participant ' +
			'starts again at p1 (runtime-design §5 step 7; fixture 30 "refresh and resume restore unsubmitted answers from the server").'
	},
	'18-multi-language/de': {
		issue:
			'R4-4: language negotiation. WebKit reports navigator.language "de-DE" for a German locale; App.svelte passes it ' +
			'unchanged and the engine only takes an exact plan language, so a German participant on Safari gets English.',
		projects: ['iphone-se']
	},
	'31-regression-choice-label-piping/de': {
		issue: 'R4-4 (as 18-multi-language/de): navigator.language "de-DE" on WebKit does not select the plan language "de".',
		projects: ['iphone-se']
	}
};

export function knownBug(fixture: string, script: string, project: string): KnownBug | null {
	const k = KNOWN_RUNTIME_BUGS[`${fixture}/${script}`];
	if (!k) return null;
	if (k.projects && !k.projects.includes(project)) return null;
	return k;
}
