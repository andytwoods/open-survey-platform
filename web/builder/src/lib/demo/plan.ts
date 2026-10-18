/**
 * The demo's `POST /api/surveys/{id}/preview-plan` (osp_app.preview.preview_plan), in the
 * browser: @osp/engine's `compileSurvey` (CE3: checksum-identical to osp_runtime.plan),
 * validated by @osp/spec first, with seed version "draft" (semantics R1-1) and the theme
 * resolved as publish does: the survey's own, else the lab default (the demo lab has none),
 * else the Clean preset.
 */
import { compileSurvey, embedTheme, type Plan, type PlanDiagnostic } from '@osp/engine';
import type { Json } from '@osp/ops';
import { validate } from '@osp/spec';
import { conditionTexts } from './expressions';

export interface CompiledDraft {
	plan: Plan | null;
	conditions: Record<string, string>;
	diagnostics: PlanDiagnostic[];
}

export function compileDraft(survey: unknown, fallbackTheme: unknown = null): CompiledDraft {
	const body = typeof survey === 'object' && survey !== null && !Array.isArray(survey) ? { ...survey, version: null } : survey;
	const { plan, diagnostics } = compileSurvey(body, { validate: (d) => validate(d) });
	if (!plan) return { plan: null, conditions: {}, diagnostics };
	const settings = (body as { settings?: { theme?: unknown } }).settings;
	const theme = settings?.theme ?? fallbackTheme;
	const themed = theme ? (embedTheme(plan, theme as Json) as unknown as Plan) : plan;
	return { plan: themed, conditions: conditionTexts(themed as unknown as Record<string, unknown>), diagnostics };
}
