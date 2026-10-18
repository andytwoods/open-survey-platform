/**
 * The preview plan, compiled in the browser (task CE5, planning/client-edits.md decision 7):
 * what `POST /api/surveys/{id}/preview-plan` (osp_app/preview.py) answers, from the draft as
 * edited here, with no server round trip.
 *
 * - The survey is validated with `@osp/spec` and compiled with `@osp/engine`'s
 *   `compileSurvey` (byte-identical to `osp_runtime.plan`), with `version` cleared so the
 *   plan seeds as `"draft"` (semantics R1-1). A draft with errors gives `plan: null` and the
 *   diagnostics, so the preview can say what to fix.
 * - The theme is resolved as publish resolves it (osp_app/publish_theme.py): the survey's
 *   own `settings.theme`, else the lab default (fetched by the caller), else the "clean"
 *   preset; it runs through the schema check and the contrast guard (the TS ports in
 *   appearance/), and a theme that fails is left out and reported.
 * - `conditions` holds every condition in the plan as text, by engine site, for the
 *   debugger (`condition_texts`).
 */
import { compileSurvey, embedTheme, exprToText, type Expr, type Plan, type PlanDiagnostic } from '@osp/engine';
import { validate } from '@osp/spec';
import { THEME_DEFAULTS, THEME_PRESETS, THEME_VERSION, type Theme } from '@osp/ui-components';
import { checkTheme } from '../appearance/guard';
import { validateThemeValue } from '../appearance/validate';

export interface LabDefaultTheme {
	name: string;
	theme: unknown;
}

export interface PreviewPlan {
	plan: Plan | null;
	conditions: Record<string, string>;
	diagnostics: PlanDiagnostic[];
}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);

/** `resolve_theme`: the theme JSON to embed (null when it fails the guard) and diagnostics. */
export function resolveTheme(survey: unknown, lab: LabDefaultTheme | null): { theme: Theme | null; diagnostics: PlanDiagnostic[] } {
	const settings = isObj(survey) ? survey.settings : null;
	const own = isObj(settings) ? settings.theme : null;
	let raw: unknown;
	let source: string;
	let prefix: string;
	if (own !== undefined && own !== null) [raw, source, prefix] = [own, 'survey theme', '/settings/theme'];
	else if (lab) [raw, source, prefix] = [lab.theme, `lab default '${lab.name}'`, '/labTheme'];
	else [raw, source, prefix] = [THEME_PRESETS.find((p) => p.id === 'clean')!.theme, 'clean preset', '/labTheme'];
	const { theme, problems } = validateThemeValue(raw);
	if (!theme) {
		return {
			theme: null,
			diagnostics: problems.map((p) => ({ severity: 'error', code: 'theme.schema', message: `Theme (${source}): ${p.message}`, pointer: prefix + p.pointer }))
		};
	}
	let found: ReturnType<typeof checkTheme>;
	try {
		found = checkTheme(theme);
	} catch {
		found = [{ severity: 'error', code: 'theme.schema', message: 'The theme could not be checked.', pointer: '', ratio: null, required: null, suggestion: null }];
	}
	const diagnostics: PlanDiagnostic[] = found.map((d) => ({
		severity: d.severity,
		code: d.code,
		message: `Theme (${source}): ${d.message}${d.suggestion !== null && d.suggestion !== undefined ? ` Nearest passing value: ${d.suggestion}.` : ''}`,
		pointer: prefix + d.pointer
	}));
	if (diagnostics.some((d) => d.severity === 'error')) return { theme: null, diagnostics };
	// Every field, as the pydantic model dumps it.
	const full = { themeVersion: THEME_VERSION, preset: null, logoAssetId: null, headerText: null, ...THEME_DEFAULTS, ...theme } as Theme;
	return { theme: full, diagnostics };
}

function text(ast: unknown): string | null {
	try {
		return exprToText(ast as Expr);
	} catch {
		return null;
	}
}

/** `condition_texts`: every expression in the plan as text, by engine site. */
export function conditionTexts(plan: Plan): Record<string, string> {
	const out: Record<string, string> = {};
	const put = (site: string, ast: unknown) => {
		if (ast === undefined || ast === null) return;
		const t = text(ast);
		if (t !== null) out[site] = t;
	};
	const p = plan as unknown as Obj;
	const entries = (v: unknown): [string, Obj][] => (isObj(v) ? (Object.entries(v).filter(([, x]) => isObj(x)) as [string, Obj][]) : []);
	for (const [id, item] of entries(p.items)) {
		put(`items.${id}.showIf`, item.showIf);
		put(`items.${id}.constraint`, item.constraint);
	}
	for (const [id, page] of entries(p.pages)) put(`pages.${id}.showIf`, page.showIf);
	for (const [id, quota] of entries(p.quotas)) put(`quotas.${id}.when`, quota.when);
	for (const [id, v] of entries(p.variables)) put(`variables.${id}.expr`, v.expr);
	const walk = (nodes: unknown) => {
		if (!Array.isArray(nodes)) return;
		for (const n of nodes) {
			if (!isObj(n)) continue;
			if (n.type === 'branch') {
				put(`flow.${String(n.id)}.if`, n.if);
				walk(n.then);
				walk(n.else);
			} else if (n.type === 'randomiser') walk(n.children);
		}
	};
	walk(p.flow);
	return out;
}

/** Compile `survey` for the preview (`survey.preview_plan`), never throwing. */
export function previewPlan(survey: unknown, lab: LabDefaultTheme | null): PreviewPlan {
	const body = isObj(survey) ? { ...survey, version: null } : survey;
	const { plan, diagnostics } = compileSurvey(body, { validate: (d) => validate(d) as PlanDiagnostic[] });
	if (!plan) return { plan: null, conditions: {}, diagnostics };
	const resolved = resolveTheme(body, lab);
	const out = resolved.theme ? (embedTheme(plan, resolved.theme) as unknown as Plan) : plan;
	return { plan: out, conditions: conditionTexts(out), diagnostics: [...diagnostics, ...resolved.diagnostics] };
}
