/**
 * Researcher hooks in the participant app (runtime-design.md §7a): when the plan declares
 * hooks (`plan.hooks`, an `osp-hooks/1` manifest that is part of the plan checksum), the
 * session drives a `HookRunner` from `@osp/hooks-sandbox` over a `HookHost` (a sandboxed
 * iframe + worker). The package is loaded only then (a separate chunk), so surveys without
 * custom code don't download it.
 *
 * Production: the sandbox document can be served from a separate site, so a hook that
 * exhausts memory crashes only that process (site isolation). Build the app with
 * `OSP_HOOKS_FRAME_URL=https://sandbox.example.org/hooks-frame.html` and serve
 * `dist/hooks-frame.html` (written by the build) at that URL; the CSP in `index.html` then
 * allows that origin in `frame-src`. Without it the frame is a `srcdoc` iframe, which the
 * page CSP allows through the frame script's hash and `worker-src blob:`.
 */
import type { Plan, State } from '@osp/engine';
import type { HookManifest, InflightMarker, InflightStore } from '@osp/hooks-sandbox';
import type { HookDriver, HookFactory } from './session';

/** Set at build time (vite `define`); empty means `srcdoc`. */
declare const __OSP_HOOKS_FRAME_URL__: string;

export function hooksFrameUrl(): string | undefined {
	try {
		return typeof __OSP_HOOKS_FRAME_URL__ === 'string' && __OSP_HOOKS_FRAME_URL__ ? __OSP_HOOKS_FRAME_URL__ : undefined;
	} catch {
		return undefined;
	}
}

/** The hook call in flight, kept synchronously in this tab (crash recovery, §7a). */
function sessionInflight(key: string): InflightStore | undefined {
	let ss: Storage;
	try {
		ss = globalThis.sessionStorage;
		if (!ss) return undefined;
	} catch {
		return undefined;
	}
	return {
		get() {
			try {
				const raw = ss.getItem(key);
				return raw ? (JSON.parse(raw) as InflightMarker) : null;
			} catch {
				return null;
			}
		},
		set(m) {
			try {
				if (m) ss.setItem(key, JSON.stringify(m));
				else ss.removeItem(key);
			} catch {
				/* blocked: a crash mid-hook then re-runs it, as after a clean unload */
			}
		}
	};
}

export interface HookFactoryOptions {
	slug: string;
	frameUrl?: string;
	log?: (msg: string, detail?: unknown) => void;
}

/** The session's `Env.hooks`: a runner for a plan with hooks. Throws if it can't run. */
export function browserHooks(o: HookFactoryOptions): HookFactory {
	return async (plan: Plan, state: State, onState: (s: State) => void): Promise<HookDriver | null> => {
		if (!plan.hooks) return null;
		const { HookHost, HookRunner } = await import('@osp/hooks-sandbox');
		const manifest = plan.hooks as unknown as HookManifest;
		const host = new HookHost({ source: manifest.source, frameUrl: o.frameUrl ?? hooksFrameUrl() });
		try {
			return new HookRunner({
				plan,
				manifest,
				invoker: host,
				state,
				onState,
				inflight: sessionInflight(`osp-runtime:hook:${o.slug}`)
			});
		} catch (e) {
			// An invalid manifest: never run the survey without its hooks (that could silently
			// take another path, §7a). The session stops with a message instead.
			host.dispose();
			o.log?.('hook manifest refused', e);
			throw e;
		}
	};
}
