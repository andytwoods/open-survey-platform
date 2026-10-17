// Import a survey from another platform (task IM1): the pure half of the Import dialog.
//
// The file is read in the browser and sent as text to `POST /api/surveys/import/preview`,
// which answers with what would be created and a diagnostic for every feature that does
// not carry over as it is. `POST /api/surveys/import` then creates the draft. No parsing
// happens here: the server's importers are the only readers of these formats.
import type { components } from '@osp/api-client';
import { api } from '../api';

export type ImportPreview = components['schemas']['ImportPreviewResponse'];
export type ImportDiagnostic = components['schemas']['ImportDiagnosticOut'];
export type ImportSummary = components['schemas']['ImportSummaryOut'];
export type ImportFormat = ImportPreview['format'];
export type SurveyDetail = components['schemas']['SurveyDetail'];

export const FORMAT_LABELS: Record<ImportFormat, string> = {
	qsf: 'Qualtrics (.qsf)',
	lss: 'LimeSurvey (.lss)',
	surveyjs: 'SurveyJS JSON'
};

/** What the file picker accepts. Anything else is still sent: the server says what it is. */
export const ACCEPT = '.qsf,.lss,.json,application/json,text/xml,application/xml';

/** Files above this are refused here, before upload (the server's limit is the same). */
export const MAX_BYTES = 20_000_000;

const TYPE_LABELS: Record<string, string> = {
	integer: 'whole number',
	decimal: 'decimal number',
	text: 'text',
	single: 'single choice',
	multi: 'multiple choice',
	date: 'date',
	matrix: 'grid',
	slider: 'slider',
	note: 'note'
};

export function typeLabel(type: string): string {
	return TYPE_LABELS[type] ?? type;
}

function plural(n: number, one: string, many = `${one}s`): string {
	return `${n} ${n === 1 ? one : many}`;
}

/** The diagnostics split for display: losses first, then behaviour changes, then notes. */
export function groupDiagnostics(diagnostics: readonly ImportDiagnostic[]): {
	errors: ImportDiagnostic[];
	losses: ImportDiagnostic[];
	warnings: ImportDiagnostic[];
	infos: ImportDiagnostic[];
} {
	return {
		errors: diagnostics.filter((d) => d.severity === 'error'),
		losses: diagnostics.filter((d) => d.severity === 'loss'),
		warnings: diagnostics.filter((d) => d.severity === 'warning'),
		infos: diagnostics.filter((d) => d.severity === 'info')
	};
}

/** One line per thing that carried over, for the preview's "What will be created" list. */
export function summaryLines(summary: ImportSummary): string[] {
	const lines: string[] = [];
	const types = Object.entries(summary.byType)
		.filter(([, n]) => n > 0)
		.map(([t, n]) => `${n} ${typeLabel(t)}`);
	lines.push(
		`${plural(summary.questions, 'question')} on ${plural(summary.pages, 'page')} in ${plural(summary.blocks, 'block')}` +
			(types.length ? ` (${types.join(', ')})` : '')
	);
	if (summary.languages.length > 1) lines.push(`Languages: ${summary.languages.join(', ')}`);
	if (summary.conditions) lines.push(plural(summary.conditions, 'condition') + ' (show-if, validation, branches)');
	if (summary.variables) lines.push(plural(summary.variables, 'variable'));
	if (summary.quotas) lines.push(plural(summary.quotas, 'quota'));
	if (summary.flowNodes > 2) lines.push(`${summary.flowNodes} flow steps`);
	return lines;
}

/** The validator's view of the draft that would be created, in one sentence (or null). */
export function validationNote(preview: ImportPreview): string | null {
	const errors = preview.validation.filter((d) => d.severity === 'error').length;
	const warnings = preview.validation.filter((d) => d.severity === 'warning').length;
	if (errors) return `The editor will show ${plural(errors, 'error')} to fix.`;
	if (warnings) return `The editor will show ${plural(warnings, 'warning')} (for example missing translations).`;
	return null;
}

export interface ImportRequest {
	filename: string;
	content: string;
	format?: ImportFormat;
}

export interface CreateRequest extends ImportRequest {
	title?: string;
	tenantId?: string;
}

export type PreviewOutcome = { kind: 'ok'; preview: ImportPreview } | { kind: 'failed'; message: string };
export type CreateOutcome =
	| { kind: 'ok'; survey: SurveyDetail; preview: ImportPreview }
	| { kind: 'failed'; message: string; diagnostics?: { code: string; message: string }[] };

/** The two server calls, behind an interface so the dialog can be tested without fetch. */
export interface ImportClient {
	preview(req: ImportRequest): Promise<PreviewOutcome>;
	create(req: CreateRequest): Promise<CreateOutcome>;
}

type ErrorBody = { message?: string; diagnostics?: { code: string; message: string }[] } | undefined;

export const apiImportClient: ImportClient = {
	async preview(req) {
		try {
			const { data, error, response } = await api.POST('/api/surveys/import/preview', { body: req });
			if (data) return { kind: 'ok', preview: data };
			if (response.status === 401) return { kind: 'failed', message: 'Your session ended. Sign in again.' };
			return { kind: 'failed', message: (error as ErrorBody)?.message ?? 'The server could not read the file.' };
		} catch {
			return { kind: 'failed', message: 'Could not reach the server.' };
		}
	},
	async create(req) {
		try {
			const { data, error, response } = await api.POST('/api/surveys/import', { body: req });
			if (data) return { kind: 'ok', survey: data.survey, preview: data.preview };
			if (response.status === 401) return { kind: 'failed', message: 'Your session ended. Sign in again.' };
			const body = error as ErrorBody;
			return { kind: 'failed', message: body?.message ?? 'Could not import the survey.', diagnostics: body?.diagnostics };
		} catch {
			return { kind: 'failed', message: 'Could not reach the server.' };
		}
	}
};

/** Read a picked file as text; refuses files over `MAX_BYTES` before reading them. */
export async function readSurveyFile(file: File): Promise<{ content: string } | { error: string }> {
	if (file.size > MAX_BYTES) return { error: `${file.name} is larger than ${MAX_BYTES / 1_000_000} MB.` };
	try {
		return { content: await file.text() };
	} catch {
		return { error: `${file.name} could not be read.` };
	}
}
