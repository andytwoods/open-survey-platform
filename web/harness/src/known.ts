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

export const KNOWN_RUNTIME_BUGS: Record<string, KnownBug> = {};

export function knownBug(fixture: string, script: string, project: string): KnownBug | null {
	const k = KNOWN_RUNTIME_BUGS[`${fixture}/${script}`];
	if (!k) return null;
	if (k.projects && !k.projects.includes(project)) return null;
	return k;
}
