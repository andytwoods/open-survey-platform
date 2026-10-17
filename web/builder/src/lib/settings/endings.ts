/**
 * Endings per outcome (end-of-survey plan §4.1, task EN1): pure helpers the Endings section of
 * Survey settings and the flow's End card build on. They only list what the survey already
 * says and shape `set_ending` ops; the server validates every op and reports `ending.*`.
 */
import type { Invocation } from '../sync/transport';

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

/** Where an outcome comes from, for the editor's "used by" line. */
export interface OutcomeUse {
	outcome: string;
	/** Human-readable sources: "End node end_1", "Quota q_old (when full)", "Consent decline", "End of the flow". */
	sources: string[];
	/** The consent page's decline: nothing is recorded, so the status line is fixed. */
	declined: boolean;
}

export const HOOK_FAILED = 'hook-failed';

/** Outcomes a session can end with, in a stable order: `complete` first, then flow order. */
export function outcomesInUse(survey: unknown): OutcomeUse[] {
	const out = new Map<string, OutcomeUse>();
	const add = (outcome: string, source: string, declined = false) => {
		const u = out.get(outcome) ?? { outcome, sources: [], declined: false };
		if (!u.sources.includes(source)) u.sources.push(source);
		u.declined ||= declined;
		out.set(outcome, u);
	};
	add('complete', 'End of the flow');
	const s = isObj(survey) ? survey : {};
	if (isObj(s.consent)) {
		const d = typeof s.consent.declineOutcome === 'string' ? s.consent.declineOutcome : 'declined';
		add(d, 'Consent decline', true);
	}
	const checked = new Set<string>();
	const walk = (nodes: unknown[]) => {
		for (const n of nodes) {
			if (!isObj(n)) continue;
			if (n.type === 'end') add(typeof n.outcome === 'string' ? n.outcome : 'complete', `End node ${String(n.id)}`);
			if (n.type === 'quotaCheck' && typeof n.quota === 'string') checked.add(n.quota);
			walk(list(n.then));
			walk(list(n.else));
			walk(list(n.children));
		}
	};
	walk(list(s.flow));
	for (const q of list(s.quotas)) {
		if (isObj(q) && typeof q.id === 'string' && checked.has(q.id) && isObj(q.onFull) && typeof q.onFull.outcome === 'string') {
			add(q.onFull.outcome, `Quota ${q.id} (when full)`);
		}
	}
	return [...out.values()];
}

export function endingsOf(survey: unknown): Record<string, Obj> {
	const settings = isObj(survey) ? survey.settings : undefined;
	const e = isObj(settings) ? settings.endings : undefined;
	if (!isObj(e)) return {};
	return Object.fromEntries(Object.entries(e).filter((kv): kv is [string, Obj] => isObj(kv[1])));
}

export function endingOf(survey: unknown, outcome: string): Obj | null {
	return endingsOf(survey)[outcome] ?? null;
}

/** The ending object after one field changes; an emptied text field is removed. */
export function endingWith(ending: Obj | null, field: string, value: unknown): Obj {
	const next: Obj = { ...(ending ?? {}) };
	if (value === undefined) delete next[field];
	else next[field] = value;
	return next;
}

export function endingOp(outcome: string, ending: Obj | null): Invocation {
	return { op: 'set_ending', params: { outcome, ending } };
}

/** The `#…` Survey settings fragment that opens one outcome's ending. */
export const endingAnchor = (outcome: string) => `ending-${outcome}`;
