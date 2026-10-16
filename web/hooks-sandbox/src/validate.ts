/**
 * Host-side validation of what a hook returned (runtime-design.md §7a "Host validation").
 * Everything from the sandbox is untrusted: type, size, depth, rate, declared variable ids,
 * declared redirect templates and placeholders, declared parent message types and schemas.
 * Refused actions become short diagnostic codes, logged with the result and never applied.
 */

import { view, type HookAction, type Plan, type State } from '@osp/engine';
import {
	buildRedirectUrl,
	exportsAllowed,
	matchesSchema,
	type HookEvent,
	type HookManifest
} from './manifest.ts';

export const LIMITS = {
	actionsPerCall: 32,
	depth: 6,
	textLength: 1000,
	messageLength: 300,
	paradataPerSession: 500,
	parentPerCall: 5,
	parentPerSession: 50,
	payloadBytes: 4096
} as const;

export interface ValidationContext {
	plan: Plan;
	manifest: HookManifest;
	event: HookEvent;
	state: State;
}

export interface Validated {
	actions: HookAction[];
	diagnostics: string[];
	/** Set when the whole result is refused (too many actions, too deep). */
	refused?: string;
}

/** Bidirectional overrides/isolates and C0/C1 controls (tabs and newlines aside). */
// eslint-disable-next-line no-control-regex -- matching control characters is the point
const UNSAFE_TEXT = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f‎‏‪-‮⁦-⁩]/u;
const PARADATA_KEY = /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/;
const DECIMAL = /^-?\d{1,30}(\.\d{1,30})?$/;

function depthOf(v: unknown, limit: number, d = 0): number {
	if (d > limit) return d;
	if (v && typeof v === 'object') {
		let max = d;
		for (const x of Object.values(v as Record<string, unknown>)) {
			max = Math.max(max, depthOf(x, limit, d + 1));
			if (max > limit) return max;
		}
		return max;
	}
	return d;
}

const short = (s: unknown) => String(s).slice(0, 64);
const isPlainObject = (v: unknown): v is Record<string, unknown> =>
	!!v && typeof v === 'object' && !Array.isArray(v);

/** Clean a rejectPage message: controls and bidi marks out, whitespace collapsed. */
export function cleanMessage(s: string): string {
	return s
		.replace(new RegExp(UNSAFE_TEXT.source, 'gu'), '')
		.replace(/\s+/gu, ' ')
		.trim()
		.slice(0, LIMITS.messageLength);
}

function hookSoFar(state: State) {
	return state.data.hooks ?? { vars: {}, paradata: [], redirect: null, parentMessages: 0 };
}

export function validateActions(raw: unknown, vc: ValidationContext): Validated {
	const { plan, manifest, event, state } = vc;
	if (!Array.isArray(raw)) return { actions: [], diagnostics: [], refused: 'actions-not-a-list' };
	if (raw.length > LIMITS.actionsPerCall) return { actions: [], diagnostics: [], refused: 'too-many-actions' };
	if (depthOf(raw, LIMITS.depth) > LIMITS.depth) return { actions: [], diagnostics: [], refused: 'too-deep' };

	const decl = manifest.handlers[event];
	const exports = exportsAllowed(manifest);
	const so = hookSoFar(state);
	const actions: HookAction[] = [];
	const diagnostics: string[] = [];
	let paradata = so.paradata.length;
	let parentCall = 0;
	let parentSession = so.parentMessages;
	let rejects = 0;
	let redirects = 0;
	const deny = (code: string) => diagnostics.push(code);

	for (const a of raw) {
		if (!isPlainObject(a) || typeof a.type !== 'string') {
			deny('action:malformed');
			continue;
		}
		if (event === 'onSubmitted' && a.type !== 'postToParent' && a.type !== 'setEndRedirect') {
			deny(`${short(a.type)}:after-submit`);
			continue;
		}
		switch (a.type) {
			case 'setVariable': {
				const id = a.id;
				const v = typeof id === 'string' ? plan.variables[id] : undefined;
				if (typeof id !== 'string' || !decl?.writes.includes(id) || !v || v.kind !== 'hook') {
					deny(`setVariable:undeclared:${short(id)}`);
					break;
				}
				let value = a.value;
				let ok = value === null;
				if (!ok) {
					switch (v.valueType) {
						case 'boolean':
							ok = typeof value === 'boolean';
							break;
						case 'integer':
							ok = typeof value === 'number' && Number.isSafeInteger(value);
							break;
						case 'decimal':
							if (typeof value === 'number' && Number.isFinite(value)) value = String(value);
							ok = typeof value === 'string' && DECIMAL.test(value);
							break;
						case 'text':
							ok = typeof value === 'string' && value.length <= LIMITS.textLength && !UNSAFE_TEXT.test(value);
							break;
					}
				}
				if (!ok) deny(`setVariable:type:${id}`);
				else actions.push({ kind: 'setVariable', id, value: value as string | number | boolean | null });
				break;
			}
			case 'addParadata': {
				const { key, value } = a;
				if (typeof key !== 'string' || !PARADATA_KEY.test(key)) {
					deny('addParadata:key');
					break;
				}
				const prim =
					value === null ||
					typeof value === 'boolean' ||
					(typeof value === 'number' && Number.isFinite(value)) ||
					(typeof value === 'string' && value.length <= LIMITS.textLength && !UNSAFE_TEXT.test(value));
				if (!prim) deny(`addParadata:value:${key}`);
				else if (paradata >= LIMITS.paradataPerSession) deny('addParadata:rate');
				else {
					paradata++;
					actions.push({ kind: 'addParadata', key, value: value as string | number | boolean | null });
				}
				break;
			}
			case 'rejectPage': {
				if (event !== 'onPageNext') {
					deny(`rejectPage:event:${event}`);
					break;
				}
				if (rejects++) {
					deny('rejectPage:rate');
					break;
				}
				const message = typeof a.message === 'string' ? cleanMessage(a.message) : '';
				if (!message) {
					deny('rejectPage:message');
					break;
				}
				const itemId = a.itemId ?? null;
				if (itemId !== null) {
					const visible = view(state).items.some((i) => i.id === itemId && i.type !== 'note');
					if (typeof itemId !== 'string' || !visible) {
						deny(`rejectPage:item:${short(itemId)}`);
						break;
					}
				}
				actions.push({ kind: 'rejectPage', itemId: itemId as string | null, message });
				break;
			}
			case 'setEndRedirect': {
				if (!exports) {
					deny('setEndRedirect:exports-not-confirmed');
					break;
				}
				if (redirects++) {
					deny('setEndRedirect:rate');
					break;
				}
				const templateId = a.templateId;
				const params = a.params;
				if (typeof templateId !== 'string' || !isPlainObject(params) || Object.values(params).some((v) => typeof v !== 'string')) {
					deny('setEndRedirect:malformed');
					break;
				}
				const r = { templateId, params: params as Record<string, string> };
				if (buildRedirectUrl(manifest, r) === null) {
					deny(`setEndRedirect:undeclared:${short(templateId)}`);
					break;
				}
				actions.push({ kind: 'setEndRedirect', templateId, params: { ...r.params } });
				break;
			}
			case 'postToParent': {
				const type = a.messageType;
				const schema =
					typeof type === 'string' && manifest.parent && Object.prototype.hasOwnProperty.call(manifest.parent.messages, type)
						? manifest.parent.messages[type]
						: undefined;
				if (!exports) {
					deny('postToParent:exports-not-confirmed');
					break;
				}
				if (!schema) {
					deny(`postToParent:undeclared:${short(type)}`);
					break;
				}
				let size = Infinity;
				try {
					size = JSON.stringify(a.payload ?? null).length;
				} catch {
					/* refused below */
				}
				if (size > LIMITS.payloadBytes || !matchesSchema(schema, a.payload ?? null)) {
					deny(`postToParent:schema:${short(type)}`);
					break;
				}
				if (parentCall >= LIMITS.parentPerCall || parentSession >= LIMITS.parentPerSession) {
					deny('postToParent:rate');
					break;
				}
				parentCall++;
				parentSession++;
				actions.push({ kind: 'postToParent', type: type as string, payload: JSON.parse(JSON.stringify(a.payload ?? null)) });
				break;
			}
			default:
				deny(`action:unknown:${short(a.type)}`);
		}
	}
	return { actions, diagnostics: diagnostics.slice(0, 64) };
}
