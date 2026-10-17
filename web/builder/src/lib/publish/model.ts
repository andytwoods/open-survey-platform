/**
 * Publish flow helpers (task B12): where each blocking problem is fixed, the participant
 * link and the export links. Display only: the server decides what blocks a publish.
 */

export interface PublishDiagnostic {
	severity: string;
	code: string;
	message: string;
	pointer: string;
}

/** Where a problem is fixed: a Survey settings section, the Appearance view, or the editor. */
export type ProblemPlace =
	| { view: 'settings'; section: 'retention' | 'consent' | 'languages' | null }
	| { view: 'appearance' }
	| { view: 'editor'; pointer: string };

export interface PublishProblem extends PublishDiagnostic {
	place: ProblemPlace;
	/** The link text. */
	action: string;
}

const under = (pointer: string, base: string) => pointer === base || pointer.startsWith(base + '/');

export function placeOf(d: PublishDiagnostic): { place: ProblemPlace; action: string } {
	const p = d.pointer ?? '';
	if (d.code === 'publish.retention_required' || under(p, '/settings/retention'))
		return { place: { view: 'settings', section: 'retention' }, action: 'Choose data retention' };
	if (d.code.startsWith('theme.') || under(p, '/settings/theme') || under(p, '/labTheme'))
		return { place: { view: 'appearance' }, action: 'Fix in Appearance' };
	if (d.code.startsWith('consent.') || d.code === 'publish.consent_missing' || under(p, '/consent'))
		return { place: { view: 'settings', section: 'consent' }, action: 'Edit consent' };
	if (under(p, '/metadata/languages') || under(p, '/metadata/defaultLanguage'))
		return { place: { view: 'settings', section: 'languages' }, action: 'Edit languages' };
	if (under(p, '/settings')) return { place: { view: 'settings', section: null }, action: 'Open survey settings' };
	return { place: { view: 'editor', pointer: p }, action: 'Go to the problem' };
}

export function problemsOf(diagnostics: readonly PublishDiagnostic[]): {
	errors: PublishProblem[];
	warnings: PublishProblem[];
} {
	const all = diagnostics.map((d) => ({ ...d, ...placeOf(d) }));
	return {
		errors: all.filter((d) => d.severity === 'error'),
		warnings: all.filter((d) => d.severity === 'warning')
	};
}

/** The link participants open (served by the API host: `/s/{slug}`). */
export function participantLink(origin: string, slug: string): string {
	return `${origin.replace(/\/$/, '')}/s/${encodeURIComponent(slug)}`;
}

export function exportLinks(surveyId: string): { label: string; href: string; description: string }[] {
	const id = encodeURIComponent(surveyId);
	return [
		{ label: 'XLSForm (.xlsx)', href: `/api/surveys/${id}/export/xlsform`, description: 'For ODK / Enketo / KoboToolbox' },
		{ label: 'LimeSurvey (.lss)', href: `/api/surveys/${id}/export/lss`, description: 'Import into LimeSurvey' }
	];
}

/** The reproducibility package of one published version (task M3's endpoint). */
export function reproLink(surveyId: string, version: number): string {
	return `/api/surveys/${encodeURIComponent(surveyId)}/versions/${version}/repro-package`;
}
