/**
 * Preview mode (task B11, runtime-design §9): the participant app exactly as participants
 * see it, run on a plan handed in directly. Nothing reaches a server and nothing is stored
 * beyond memory: `previewEnv` gives the session an in-memory `Api` (start/resume answer from
 * the given plan and seed, saves and the submit are acknowledged and dropped, quota checks
 * answer from `quotas`) and a memory-only store.
 *
 * The builder's preview frame mounts `App` with `preview={previewEnv(cfg)}`; the participant
 * entry (`main.ts`) never imports this file.
 *
 * Researcher hooks (task R10, runtime-design §7a) run exactly as for participants: the same
 * `browserHooks` factory, so the same sandboxed iframe + worker from `@osp/hooks-sandbox`.
 * Only two things differ: the hook call in flight is not kept in `sessionStorage` (the
 * builder remounts the app on every debugger step, which must not look like a crash), and
 * `postToParent` is never delivered (the parent here is the builder, not the lab's page);
 * it is reported through `log` instead. Hook outcomes themselves are in the engine's event
 * log, which the debugger reads.
 *
 * The store reports itself as `indexeddb` although it only keeps memory: the "your answers
 * are not kept on this device" notice is about a participant's blocked browser storage, so
 * showing it in every preview would make the preview differ from the real page.
 */
import type { Plan, Snapshot } from '@osp/engine';
import type { Api, QuotaResponse, ResumeResponse, SnapshotResponse, StartResponse, SubmitResponse } from './lib/api';
import type { PreviewMount } from './lib/preview-mount';
import { browserHooks } from './lib/hooks';
import type { Env, Session } from './lib/session';
import { MemoryStore, type LocalRecord, type LocalStore } from './lib/storage';

export { default as RuntimeApp } from './App.svelte';
export type { Session } from './lib/session';
export type { PreviewMount } from './lib/preview-mount';

export const PREVIEW_SLUG = 'preview';
const ID = 'preview';

export interface PreviewConfig {
	plan: Plan;
	/** The session seed (1 … 2^53 − 1): change it to try other randomisations. */
	sessionSeed: number;
	/** Conditions as the server would assign them at start; missing ones the engine draws. */
	assigned?: Record<string, string | number>;
	/** What a quota check answers, by quota id (default `open`). */
	quotas?: Record<string, 'open' | 'full'>;
	/** Start from this engine snapshot (a debugger step) instead of the first page. */
	snapshot?: Snapshot | null;
	language?: string;
	/** Called with the session once it has booted (the debugger follows it). */
	onSession?: (s: Session) => void;
	/** The app's diagnostics (e.g. a refused hook manifest), for the debugger. */
	log?: (msg: string, detail?: unknown) => void;
}

class PreviewStore implements LocalStore {
	readonly kind = 'indexeddb' as const;
	private mem = new MemoryStore();
	get(slug: string) {
		return this.mem.get(slug);
	}
	put(rec: LocalRecord) {
		return this.mem.put(rec);
	}
	delete(slug: string) {
		return this.mem.delete(slug);
	}
	async purge() {
		return 0;
	}
}

function quotaOf(plan: Plan, nodeId: string): string | null {
	const walk = (ns: Plan['flow']): string | null => {
		for (const n of ns) {
			if (n.id === nodeId && n.type === 'quotaCheck') return n.quota;
			const sub = n.type === 'branch' ? [...n.then, ...n.else] : n.type === 'randomiser' ? n.children : [];
			const hit = walk(sub);
			if (hit) return hit;
		}
		return null;
	};
	return walk(plan.flow);
}

export function previewApi(cfg: PreviewConfig): Api {
	const plan = JSON.parse(JSON.stringify(cfg.plan)) as Plan;
	const saveMode = plan.settings.saveMode;
	const assigned = { ...(cfg.assigned ?? {}) };
	let revision = 0;
	const session = {
		sessionId: ID,
		sessionSeed: cfg.sessionSeed,
		assigned,
		planUrl: 'preview:plan',
		planChecksum: plan.checksum,
		saveMode,
		localCopy: plan.settings.localCopy
	};
	const now = () => new Date(0).toISOString();
	return {
		start: async () => ({ ...session, resumeToken: ID, revision }) as unknown as StartResponse,
		resume: async () =>
			({ ...session, revision, snapshot: cfg.snapshot ?? null, submitted: false }) as unknown as ResumeResponse,
		plan: async () => JSON.parse(JSON.stringify(plan)),
		save: async () => ({ revision: ++revision, replay: false }) as unknown as SnapshotResponse,
		quota: async (_sid, _token, nodeId) => {
			const quota = quotaOf(plan, nodeId);
			const result = (quota && cfg.quotas?.[quota]) || 'open';
			return { nodeId, quota, result, replay: false } as unknown as QuotaResponse;
		},
		submit: async () => ({ responseId: ID, submittedAt: now(), late: false, replay: false }) as unknown as SubmitResponse,
		consent: async () => ({ ok: true }),
		decline: async () => ({ ok: true }),
		withdraw: async () => ({ ok: true })
	};
}

/** Everything `App` needs to run on `cfg` with no server and no persistent storage. */
export async function previewEnv(cfg: PreviewConfig): Promise<PreviewMount> {
	const store = new PreviewStore();
	if (cfg.snapshot) {
		// A local copy: boot restores it, exactly as after a refresh.
		const t = Date.now();
		await store.put({
			slug: PREVIEW_SLUG,
			sessionId: ID,
			resumeToken: ID,
			sessionSeed: cfg.sessionSeed,
			assigned: { ...(cfg.assigned ?? {}) },
			planUrl: 'preview:plan',
			planChecksum: cfg.plan.checksum,
			saveMode: cfg.plan.settings.saveMode,
			plan: null,
			snapshot: cfg.snapshot,
			serverRevision: 0,
			syncedEngineRev: cfg.snapshot.revision,
			inflight: null,
			conflicts: [],
			submitting: null,
			createdAt: t,
			updatedAt: t
		});
	}
	const log = cfg.log ?? (() => undefined);
	const env: Env = {
		api: previewApi(cfg),
		store,
		hooks: browserHooks({
			slug: PREVIEW_SLUG,
			log,
			persistInflight: false,
			deliverToParent: (origin, msg) => log(`postToParent "${msg.type}" to ${origin} (not sent from the preview)`, msg.payload)
		}),
		now: () => Date.now(),
		random: Math.random,
		setTimer: (fn, ms) => setTimeout(fn, ms),
		clearTimer: (h) => clearTimeout(h as number),
		debounceMs: 50,
		log
	};
	return { env, slug: PREVIEW_SLUG, language: cfg.language, onSession: cfg.onSession };
}
