/**
 * Researcher hooks in Survey settings (task R11, runtime-design.md §7a): pure helpers the
 * Hooks editor builds its `set_hooks` op from, the reference it shows (events, `ctx`,
 * actions) and the static checks it runs on a draft before anything is saved. The server
 * validates the manifest (shape, references); running the code is the Preview's job, in the
 * same sandbox participants get.
 */
import type { Invocation } from '../sync/transport';

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);

export const HOOKS_FORMAT = 'osp-hooks/1';
export const DEFAULT_TIMEOUT_MS = 2000;
export const MAX_TIMEOUT_MS = 5000;

/** The sandbox's events, in the order they happen in a run (manifest.ts HOOK_EVENTS). */
export const HOOK_EVENTS: ReadonlyArray<{ id: string; when: string; data: string }> = [
	{ id: 'onStart', when: 'A new session starts', data: 'the declared URL parameters' },
	{ id: 'onResume', when: 'After a refresh or a cross-device resume', data: 'nothing' },
	{ id: 'onPageInit', when: 'Before a page renders (can set variables it uses)', data: 'the page id' },
	{ id: 'onPageShown', when: 'Once a page is on screen', data: 'visible items and realised orders' },
	{ id: 'onAnswer', when: 'An answer changes', data: 'item id, new value, old value' },
	{ id: 'onPageNext', when: 'Next is pressed (may rejectPage)', data: 'the page id' },
	{ id: 'onBack', when: 'Back is pressed', data: 'the page id' },
	{ id: 'onValidationError', when: 'A page fails validation', data: 'failed items and messages' },
	{ id: 'onBeforeSubmit', when: 'Before the final submit', data: 'the full response record' },
	{ id: 'onSubmitted', when: 'After the server acknowledges the submit', data: 'nothing' }
];

export const CTX_FIELDS: ReadonlyArray<{ field: string; meaning: string }> = [
	{ field: 'ctx.trial', meaning: '1-based number of the page in this participant’s path' },
	{ field: 'ctx.trialId, ctx.blockId', meaning: 'ids of the current page and block' },
	{ field: 'ctx.position', meaning: '{ randomiserId, index, of } inside a randomiser or loop' },
	{ field: 'ctx.pagesDone, ctx.pagesEstimated', meaning: 'progress' },
	{ field: 'ctx.conditions', meaning: 'assigned conditions, e.g. { framing: "loss" }' },
	{ field: 'ctx.language, ctx.device', meaning: 'current language; phone / tablet / desktop' },
	{ field: 'ctx.elapsedMs, ctx.trialElapsedMs', meaning: 'time since start / since this page was shown' },
	{ field: 'ctx.results', meaning: 'values and states of the questions this handler reads' },
	{ field: 'ctx.vars', meaning: 'the variables this handler reads' },
	{ field: 'ctx.sessionId', meaning: 'pseudonymous session id' },
	{ field: 'ctx.random(), ctx.now()', meaning: 'seeded randomness and the injected clock (Math.random and Date use them too)' }
];

export const ACTIONS: ReadonlyArray<{ call: string; meaning: string }> = [
	{ call: 'act.addParadata(key, value)', meaning: 'stored with the response' },
	{ call: 'act.rejectPage({ itemId?, message })', meaning: 'from onPageNext only: blocks Next with a custom validation error' },
	{ call: 'act.setVariable(id, value)', meaning: 'only hook variables declared in writes (none in this survey format yet)' },
	{ call: 'act.setEndRedirect(templateId, params)', meaning: 'a redirect template declared under redirects (owner-confirmed)' },
	{ call: 'act.postToParent(type, payload)', meaning: 'a message type declared under parent (owner-confirmed)' }
];

export const STARTER_SOURCE = [
	"// Runs in a sandbox: no network, no DOM. Register handlers with osp.on(event, fn).",
	"osp.on('onPageShown', function (ctx, data, act) {",
	"  act.addParadata('shownTrial', ctx.trial);",
	'});',
	''
].join('\n');

// -- the manifest in the survey ---------------------------------------------------------

export interface HookHandler {
	reads: string[];
	writes: string[];
	timeoutMs?: number;
}

export interface HookManifest extends Obj {
	format: string;
	source: string;
	handlers: Record<string, HookHandler>;
}

export function hooksOf(survey: unknown): HookManifest | null {
	const h = isObj(survey) ? survey.hooks : undefined;
	if (!isObj(h) || typeof h.source !== 'string' || !isObj(h.handlers)) return null;
	return h as HookManifest;
}

export function hooksOp(hooks: HookManifest | null): Invocation {
	return { op: 'set_hooks', params: { hooks } };
}

/** A fresh manifest for a survey that had none. */
export function starterManifest(): HookManifest {
	return { format: HOOKS_FORMAT, source: STARTER_SOURCE, handlers: { onPageShown: { reads: [], writes: [] } } };
}

// -- the editor's draft -----------------------------------------------------------------

export interface HandlerDraft {
	on: boolean;
	/** Ids, comma or space separated, as typed. */
	reads: string;
	/** Milliseconds as typed; empty is the default. */
	timeoutMs: string;
}

export interface HooksDraft {
	source: string;
	handlers: Record<string, HandlerDraft>;
}

export function draftOf(m: HookManifest | null): HooksDraft {
	const handlers: Record<string, HandlerDraft> = {};
	for (const { id } of HOOK_EVENTS) {
		const h = m?.handlers[id];
		handlers[id] = {
			on: !!h,
			reads: h ? h.reads.join(', ') : '',
			timeoutMs: h?.timeoutMs !== undefined ? String(h.timeoutMs) : ''
		};
	}
	return { source: m?.source ?? '', handlers };
}

export function parseIds(text: string): string[] {
	return text
		.split(/[\s,;]+/)
		.map((s) => s.trim())
		.filter(Boolean);
}

/** A problem with the draft the editor can see before asking the server. */
export interface DraftProblem {
	severity: 'error' | 'warning';
	pointer: string;
	message: string;
}

/**
 * The manifest a draft describes, built on `base` so everything the editor does not show
 * (writes, urlParams, redirects, parent, exportsConfirmedFor) is kept as it was. Problems
 * that make it unsendable (a bad timeout, an id that is not an identifier) come back too.
 */
export function manifestOf(draft: HooksDraft, base: HookManifest | null): { manifest: HookManifest; problems: DraftProblem[] } {
	const problems: DraftProblem[] = [];
	const handlers: Record<string, HookHandler> = {};
	for (const { id } of HOOK_EVENTS) {
		const d = draft.handlers[id];
		if (!d?.on) continue;
		const reads = parseIds(d.reads);
		for (const r of reads) {
			if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(r)) {
				problems.push({ severity: 'error', pointer: `/hooks/handlers/${id}/reads`, message: `'${r}' is not a question or variable id` });
			}
		}
		const h: HookHandler = { reads, writes: base?.handlers[id]?.writes ?? [] };
		const t = d.timeoutMs.trim();
		if (t) {
			const n = Number(t);
			if (!Number.isInteger(n) || n < 1 || n > MAX_TIMEOUT_MS) {
				problems.push({
					severity: 'error',
					pointer: `/hooks/handlers/${id}/timeoutMs`,
					message: `the timeout is a whole number of milliseconds from 1 to ${MAX_TIMEOUT_MS}`
				});
			} else h.timeoutMs = n;
		}
		handlers[id] = h;
	}
	const manifest: HookManifest = { ...(base ?? {}), format: HOOKS_FORMAT, source: draft.source, handlers };
	return { manifest, problems };
}

export function sameManifest(a: HookManifest | null, b: HookManifest | null): boolean {
	return JSON.stringify(a) === JSON.stringify(b);
}

// -- static checks ------------------------------------------------------------------------

const REGISTERS = /osp\s*\.\s*on\s*\(\s*(['"`])([A-Za-z_]\w*)\1/g;

/** Events the script registers with `osp.on('…')` (a text scan, not a parse). */
export function registeredEvents(source: string): string[] {
	const out: string[] = [];
	for (const m of source.matchAll(REGISTERS)) if (!out.includes(m[2]!)) out.push(m[2]!);
	return out;
}

/**
 * What the sandbox would report without running anything: a declared event the script
 * never registers fails every call with `no-handler`; a registered event that is not
 * declared never runs; an unknown event name is ignored by `osp.on`.
 */
export function staticProblems(m: HookManifest): DraftProblem[] {
	const out: DraftProblem[] = [];
	const known = HOOK_EVENTS.map((e) => e.id);
	const registered = registeredEvents(m.source);
	const declared = Object.keys(m.handlers);
	if (declared.length === 0) {
		out.push({ severity: 'warning', pointer: '/hooks/handlers', message: 'No event is handled: the script never runs.' });
	}
	for (const ev of declared) {
		if (!registered.includes(ev)) {
			out.push({
				severity: 'warning',
				pointer: `/hooks/handlers/${ev}`,
				message: `${ev} is handled but the script never registers it (osp.on('${ev}', …)): every call fails with no-handler.`
			});
		}
	}
	for (const ev of registered) {
		if (!known.includes(ev)) {
			out.push({ severity: 'warning', pointer: '/hooks/source', message: `osp.on('${ev}') is not an event: it is ignored.` });
		} else if (!declared.includes(ev)) {
			out.push({ severity: 'warning', pointer: '/hooks/source', message: `The script registers ${ev} but it is not handled above: it never runs.` });
		}
	}
	return out;
}

/** Server diagnostics about the manifest (pointer under `/hooks`). */
export function hookDiagnostics<T extends { pointer?: string }>(diagnostics: readonly T[]): T[] {
	return diagnostics.filter((d) => typeof d.pointer === 'string' && (d.pointer === '/hooks' || d.pointer.startsWith('/hooks/')));
}

/** Anything the manifest declares that this editor does not edit (the JSON view does). */
export function advancedParts(m: HookManifest | null): string[] {
	if (!m) return [];
	const out: string[] = [];
	if (Array.isArray(m.urlParams) && m.urlParams.length) out.push(`URL parameters: ${m.urlParams.join(', ')}`);
	if (isObj(m.redirects) && Object.keys(m.redirects).length) out.push(`redirect templates: ${Object.keys(m.redirects).join(', ')}`);
	if (isObj(m.parent) && typeof m.parent.origin === 'string') out.push(`parent messages to ${m.parent.origin}`);
	const writes = Object.entries(m.handlers).filter(([, h]) => h.writes.length);
	if (writes.length) out.push(`variable writes: ${writes.map(([ev, h]) => `${ev} → ${h.writes.join(', ')}`).join('; ')}`);
	return out;
}
