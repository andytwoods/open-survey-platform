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
	'20-worked-example/complete-gain': {
		issue: 'R3b: fixture un-pended by SEM1 (if(), calculate, embedded data, quota); runtime app not yet updated.'
	},
	'20-worked-example/declined': {
		issue: 'R3b: as 20/complete-gain.'
	},
	'20-worked-example/loss-charity-back-refresh': {
		issue: 'R3b: as 20/complete-gain.'
	},
	'20-worked-example/screenout-quota-full': {
		issue: 'R3b: as 20/complete-gain (quota full path).'
	},
	'24-quota-pending-retry/timeout-refresh-lost-reply': {
		issue: 'R3b: SEM1 R6-4: refresh must re-send the pending quota call with the same idempotency key.'
	},
	'25-second-device-resume/stale-device-a': {
		issue: 'R3b: SEM1 R6-6: 409 must adopt the server copy and show the other-device notice.'
	},
	'26-decimal-edge-cases/precision': {
		issue: 'R3b: SEM1 R6-2: canonical decimal strings, 28 significant digits, reject longer input.'
	},
	'26-decimal-edge-cases/trailing-zeros': {
		issue: 'R3b: SEM1 R6-2: canonical decimal strings.'
	},
	'33-end-only-save/storage-blocked': {
		issue: 'R3b: SEM1 R6-5: memory-only refresh must restart() with the same seed and conditions and show a notice.'
	},
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
	'39-slider/off-step': {
		issue:
			'C2c-1: the Slider widget (ui-components, R5) passes a typed value to the Bits slider, which snaps it to the ' +
			'step grid and reports the snapped value: typing 7.25 on a 0.5-step slider stores 7 while the box still shows ' +
			'7.25. Semantics §2 (C2c-4) refuses an off-step value as unreadable (value.off_step) rather than storing a value ' +
			'the participant did not give, so the engine never sees the typed value.'
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
