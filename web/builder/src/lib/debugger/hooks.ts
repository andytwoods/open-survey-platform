/**
 * Researcher hooks in the debugger (task R10, runtime-design §7a). Every hook call the
 * preview frame made is an engine `resolve` event with a `HookResolution` (status, actions,
 * error, refused actions), so this reads the run's event log; nothing re-runs hook code.
 */
import type { HookAction, HookResolution, State } from '@osp/engine';

export interface HookCall {
	seq: number;
	/** The hook event, e.g. `onPageNext`. */
	event: string;
	/** `ok`, `failed` (went on), `fatal` (ended `hook-failed`) or `refused` (stale or invalid). */
	status: 'ok' | 'failed' | 'fatal' | 'refused';
	/** What the hook did, one short line per accepted action. */
	actions: string[];
	/** Why it failed or was refused, if it did. */
	error: string | null;
	/** Actions the host refused (short codes); the hook itself went on. */
	diagnostics: string[];
}

const short = (v: unknown) => {
	const s = JSON.stringify(v) ?? 'null';
	return s.length > 80 ? `${s.slice(0, 79)}…` : s;
};

export function describeAction(a: HookAction): string {
	switch (a.kind) {
		case 'setVariable':
			return `setVariable ${a.id} = ${short(a.value)}`;
		case 'addParadata':
			return `addParadata ${a.key} = ${short(a.value)}`;
		case 'rejectPage':
			return `rejectPage${a.itemId ? ` ${a.itemId}` : ''}: ${short(a.message)}`;
		case 'setEndRedirect':
			return `setEndRedirect ${a.templateId} ${short(a.params)}`;
		case 'postToParent':
			return `postToParent ${a.type} (not sent from the preview)`;
		default:
			return short(a);
	}
}

/** The run's hook calls, oldest first. */
export function hookLog(state: State): HookCall[] {
	const out: HookCall[] = [];
	for (const e of state.data.events) {
		if (e.type !== 'resolve' || e.effect.kind !== 'hook') continue;
		const r = (e.value ?? null) as Partial<HookResolution> | null;
		const event = e.effect.event ?? '?';
		if (e.rejected !== undefined) {
			out.push({ seq: e.seq, event, status: 'refused', actions: [], error: e.rejected, diagnostics: [] });
			continue;
		}
		const status = r?.status === 'ok' || r?.status === 'failed' || r?.status === 'fatal' ? r.status : 'refused';
		out.push({
			seq: e.seq,
			event,
			status,
			actions: Array.isArray(r?.actions) ? r.actions.map(describeAction) : [],
			error: typeof r?.error === 'string' ? r.error : null,
			diagnostics: Array.isArray(r?.diagnostics) ? r.diagnostics.filter((d): d is string => typeof d === 'string') : []
		});
	}
	return out;
}
