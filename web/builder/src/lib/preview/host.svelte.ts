/**
 * The preview host (task B11): owns the draft plan, the seed and the debugger's engine
 * state, and keeps every device frame on that state.
 *
 * - A frame reports each engine change (the participant answered, pressed Next …); the host
 *   restores the snapshot into its own engine state, which the debugger reads.
 * - The debugger changes the state (step, back, replay a script); the host loads the new
 *   snapshot into every frame, which boots from it exactly as after a refresh.
 * - Side by side, the other frames follow the one in use shortly after it changes.
 *
 * Nothing is saved anywhere: the frames run `web/runtime` in preview mode (memory only).
 */
import { isState, restore, snapshot, type Plan, type State } from '@osp/engine';
import { api } from '../api';
import { startState } from '../debugger/script';
import { listenForFrames, type FrameConfig, type FrameHandle, type PreviewBridge } from './bridge';

export interface PreviewDiagnostic {
	severity: string;
	code: string;
	message: string;
	pointer?: string;
}

export type Device = 'phone' | 'tablet' | 'desktop';
export const DEVICES: ReadonlyArray<{ id: Device; label: string; width: number; height: number }> = [
	{ id: 'phone', label: 'Phone', width: 375, height: 667 },
	{ id: 'tablet', label: 'Tablet', width: 768, height: 1024 },
	{ id: 'desktop', label: 'Desktop', width: 1280, height: 800 }
];

const MIRROR_MS = 250;

export function randomSeed(): number {
	return 1 + Math.floor(Math.random() * 1_000_000);
}

export class PreviewHost implements PreviewBridge {
	plan = $state.raw<Plan | null>(null);
	/** Condition texts by engine site (from the server). */
	texts = $state.raw<Record<string, string>>({});
	diagnostics = $state.raw<PreviewDiagnostic[]>([]);
	revision = $state<number | null>(null);
	loading = $state(false);
	error = $state<string | null>(null);

	seed = $state(1);
	assigned = $state.raw<Record<string, string | number>>({});
	quotas = $state.raw<Record<string, 'open' | 'full'>>({});
	language = $state<string | undefined>(undefined);

	/** The debugger's engine state: the same run the frames show. */
	state = $state.raw<State | null>(null);
	/** The participant app's phase in the frame last used (page, pending, submitting, done). */
	phase = $state('page');
	/** Bumped on every state change (frames and debugger). */
	version = $state(0);
	/** Who moved the run last: a participant in a frame, or the debugger. */
	source = $state<'frame' | 'debugger'>('debugger');

	// Plain maps: frame bookkeeping, never rendered.
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	private frames = new Map<string, FrameHandle>();
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	private keys = new Map<string, number>();
	private nextKey = 1;
	private mirror: ReturnType<typeof setTimeout> | null = null;

	constructor(seed = 1) {
		this.seed = seed;
	}

	/**
	 * Listen for the frames' messages (bridge.ts checks origin, source window and schema).
	 * `frameWindow` gives the iframe window registered for a frame id.
	 */
	install(w: Window, frameOrigin: string, frameWindow: (frameId: string) => Window | null): () => void {
		const off = listenForFrames(w, frameOrigin, frameWindow, this);
		return () => {
			off();
			if (this.mirror) clearTimeout(this.mirror);
		};
	}

	/** Compile the current draft (`POST /preview-plan`) and restart on it. */
	async fetch(surveyId: string): Promise<void> {
		this.loading = true;
		this.error = null;
		try {
			const { data, error } = await api.POST('/api/surveys/{survey_id}/preview-plan', {
				params: { path: { survey_id: surveyId } }
			});
			if (!data) {
				const m = (error as { message?: unknown } | undefined)?.message;
				this.error = typeof m === 'string' ? m : 'The preview could not be built.';
				return;
			}
			this.diagnostics = (data.diagnostics ?? []) as PreviewDiagnostic[];
			this.texts = data.conditions ?? {};
			this.revision = data.revision;
			this.plan = (data.plan as unknown as Plan | null) ?? null;
			if (this.plan) this.restart();
			else this.state = null;
		} catch (e) {
			this.error = (e as Error)?.message || 'Network error';
		} finally {
			this.loading = false;
		}
	}

	/** Use a plan directly (tests, or a plan already in hand). */
	usePlan(plan: Plan, texts: Record<string, string> = {}) {
		this.plan = plan;
		this.texts = texts;
		this.restart();
	}

	/** Start again from the first page with the current seed and conditions. */
	restart() {
		if (!this.plan) return;
		this.setState(startState(this.plan, { sessionSeed: this.seed, language: this.language, server: { conditions: this.assigned } }));
	}

	/** The debugger moved the run: show it in every frame. */
	setState(state: State) {
		this.state = state;
		this.source = 'debugger';
		this.phase = state.data.ended ? 'done' : state.data.pending ? 'pending' : 'page';
		this.version++;
		for (const id of this.frames.keys()) this.push(id);
	}

	private config(frameId: string): FrameConfig | null {
		if (!this.plan) return null;
		const key = this.nextKey++;
		this.keys.set(frameId, key);
		return {
			key,
			planJson: JSON.stringify(this.plan),
			sessionSeed: this.seed,
			assigned: { ...this.assigned },
			quotas: { ...this.quotas },
			snapshotJson: this.state ? JSON.stringify(snapshot(this.state)) : null,
			language: this.language
		};
	}

	private push(frameId: string) {
		const cfg = this.config(frameId);
		if (cfg) this.frames.get(frameId)?.load(cfg);
	}

	// -- PreviewBridge (called by the frames) ---------------------------------------------

	attach(frameId: string, frame: FrameHandle): FrameConfig | null {
		this.frames.set(frameId, frame);
		return this.config(frameId);
	}

	detach(frameId: string) {
		this.frames.delete(frameId);
		this.keys.delete(frameId);
	}

	changed(frameId: string, key: number, snapshotJson: string, phase: string) {
		if (this.keys.get(frameId) !== key || !this.plan) return; // a frame since reloaded
		let snap: unknown;
		try {
			snap = JSON.parse(snapshotJson);
		} catch {
			return;
		}
		const same =
			this.state &&
			(snap as { revision?: number }).revision === this.state.data.revision &&
			(snap as { data?: { events?: unknown[] } }).data?.events?.length === this.state.data.events.length;
		this.phase = phase;
		if (same) {
			this.version++;
			return;
		}
		const r = restore(this.plan, snap, { clock: () => Date.now() });
		if (!isState(r)) return;
		this.state = r;
		this.source = 'frame';
		this.version++;
		if (this.frames.size > 1) {
			if (this.mirror) clearTimeout(this.mirror);
			this.mirror = setTimeout(() => {
				this.mirror = null;
				for (const id of this.frames.keys()) if (id !== frameId) this.push(id);
			}, MIRROR_MS);
		}
	}
}
