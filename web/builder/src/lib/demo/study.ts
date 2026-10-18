/**
 * The demo's prespecified study (web/builder/demo-site/study.json): an invented "Coffee and
 * focus" survey that uses most features (consent, two languages, a grid, sliders, show-if,
 * a branch to an ending, piping, a computed variable, a randomiser, shuffled choices, an
 * ending per outcome, a theme). tests/test_demo_study.py validates it with osp-spec.
 */
import study from '../../../demo-site/study.json';
import type { SurveyDoc } from '../sync/transport';
import type { DemoDraft } from './memory-transport';

export const DEMO_SURVEY_ID = 'coffee-focus';

/** A fresh copy of the study (the JSON module is shared, so never hand it out directly). */
export function demoStudy(): SurveyDoc {
	return JSON.parse(JSON.stringify(study)) as SurveyDoc;
}

export function demoDraft(): DemoDraft {
	const survey = demoStudy();
	const title = (survey.metadata as { title?: unknown } | undefined)?.title;
	const en = typeof title === 'string' ? title : ((title as Record<string, string> | undefined)?.en ?? 'Demo study');
	return { id: DEMO_SURVEY_ID, title: en, revision: 1, survey };
}
