/**
 * The demo's draft between its own pages (task DEMO2). Each demo page is a full page load,
 * so the edited draft is kept in sessionStorage (this tab only) after every change and
 * picked up by the next demo page, including "Take the study". A reload drops it: the demo
 * then starts from the prespecified study again, as its banner says.
 */
import type { SurveyDoc } from '../sync/transport';
import type { DemoDraft } from './memory-transport';
import { DEMO_SURVEY_ID } from './study';

/** sessionStorage key of the draft carried between demo pages. */
export const STATE_KEY = 'osp-demo-draft-v1';

function storage(): Storage | null {
	try {
		return typeof sessionStorage === 'undefined' ? null : sessionStorage;
	} catch {
		return null;
	}
}

/** Was this page load a reload (F5, the browser's reload button)? */
function isReload(): boolean {
	try {
		const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined;
		return nav?.type === 'reload';
	} catch {
		return false;
	}
}

/** The draft carried over from the previous demo page, unless this load is a reload. */
export function restoreDraft(): DemoDraft | null {
	const s = storage();
	if (!s) return null;
	try {
		if (isReload()) {
			s.removeItem(STATE_KEY);
			return null;
		}
		const raw = s.getItem(STATE_KEY);
		if (!raw) return null;
		const d = JSON.parse(raw) as Partial<DemoDraft>;
		if (d.id !== DEMO_SURVEY_ID || typeof d.revision !== 'number' || typeof d.survey !== 'object' || !d.survey) return null;
		return { id: d.id, title: String(d.title ?? ''), revision: d.revision, survey: d.survey as SurveyDoc };
	} catch {
		return null;
	}
}

export function keepDraft(d: DemoDraft) {
	try {
		storage()?.setItem(STATE_KEY, JSON.stringify(d));
	} catch {
		// Full or blocked storage: the draft still lives on this page.
	}
}

export function dropDraft() {
	try {
		storage()?.removeItem(STATE_KEY);
	} catch {
		// nothing to drop
	}
}
