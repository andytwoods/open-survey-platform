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
 *
 * Researcher hooks (task R10) run inside each frame, in the participant app's sandbox. Their
 * outcomes are engine events, so they arrive with the snapshot; the app's own diagnostics
 * (e.g. a refused hook manifest) arrive as `log` messages and are kept in `logs`. A change
 * made only by hooks (say `onResume` in a frame that just loaded) is not mirrored to the
 * other frames: each would answer with its own `onResume`, and so on forever.
 */
import { isState, restore, snapshot, type EngineEvent, type Plan, type State } from '@osp/engine';
import { startState } from '../debugger/script';
import { previewPlan, type LabDefaultTheme } from './compile';
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
const MAX_LOGS = 50;

export interface PreviewLog {
	frameId: string;
	message: string;
}

/** An event as JSON without its time. */
function untimed(e: unknown): string {
	if (!e || typeof e !== 'object') return JSON.stringify(e ?? null);
	const { t: _t, ...rest } = e as Record<string, unknown>;
	void _t;
	return JSON.stringify(rest);
}

/** Only the session start: nothing answered, no step taken, no hook run. */
export function pristine(state: State): boolean {
	return state.data.events.every((e) => e.type === 'start');
}

/** Events a participant (or the debugger) caused: everything but recorded hook results. */
export function participantEvents(events: readonly EngineEvent[]): number {
	return events.filter((e) => !(e.type === 'resolve' && e.effect.kind === 'hook')).length;
}

export function randomSeed(): number {
	return 1 + Math.floor(Math.random() * 1_000_000);
}

export class PreviewHost implements PreviewBridge {
	plan = $state.raw<Plan | null>(null);
	/** Condition texts by engine site (compile.ts `conditionTexts`). */
	texts = $state.raw<Record<string, string>>({});
	diagnostics = $state.raw<PreviewDiagnostic[]>([]);
	/** Diagnostics from the participant app in the frames, newest last. */
	logs = $state.raw<PreviewLog[]>([]);
	/** The store version the plan was built from. */
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

	/**
	 * Compile `survey` here (compile.ts: @osp/spec + @osp/engine, no server round trip) and
	 * restart on it. `version` is the store version it came from (to tell when the draft has
	 * moved on); `labTheme` fetches the lab default theme, asked for only when the survey has
	 * no theme of its own.
	 */
	async build(survey: unknown, version: number, labTheme: () => Promise<LabDefaultTheme | null> = async () => null): Promise<void> {
		this.loading = true;
		this.error = null;
		try {
			const settings = (survey as { settings?: { theme?: unknown } } | null)?.settings;
			const lab = settings?.theme === undefined || settings.theme === null ? await labTheme() : null;
			const r = previewPlan(survey, lab);
			this.diagnostics = r.diagnostics as PreviewDiagnostic[];
			this.logs = [];
			this.texts = r.conditions;
			this.revision = version;
			this.plan = r.plan;
			if (this.plan) this.restart();
			else this.state = null;
		} catch (e) {
			this.error = (e as Error)?.message || 'The preview could not be built.';
		} finally {
			this.loading = false;
		}
	}

	/** Use a plan directly (tests, or a plan already in hand). */
	usePlan(plan: Plan, texts: Record<string, string> = {}) {
		this.plan = plan;
		this.texts = texts;
		this.logs = [];
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
			// A run nobody has moved yet starts in the frame as a new session (the same seed and
			// conditions give the same start), so `onStart` hooks run as for a participant.
			snapshotJson: this.state && !pristine(this.state) ? JSON.stringify(snapshot(this.state)) : null,
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
		// Two frames can reach the same revision by different events (each runs its own hooks),
		// so the last event must match too, apart from its time (a frame that started the run
		// itself has its own clock).
		const events = (snap as { data?: { events?: unknown[] } }).data?.events;
		const same =
			this.state &&
			(snap as { revision?: number }).revision === this.state.data.revision &&
			events?.length === this.state.data.events.length &&
			untimed(events.at(-1)) === untimed(this.state.data.events.at(-1));
		this.phase = phase;
		if (same) {
			this.version++;
			return;
		}
		const r = restore(this.plan, snap, { clock: () => Date.now() });
		if (!isState(r)) return;
		const byParticipant = !this.state || participantEvents(r.data.events) !== participantEvents(this.state.data.events);
		this.state = r;
		// Hooks that ran as a frame loaded (or a frame starting the run itself) follow from
		// whoever moved the run last; only a participant's own step makes it the frame's run.
		if (byParticipant) this.source = 'frame';
		this.version++;
		if (this.frames.size > 1 && byParticipant) {
			if (this.mirror) clearTimeout(this.mirror);
			this.mirror = setTimeout(() => {
				this.mirror = null;
				for (const id of this.frames.keys()) if (id !== frameId) this.push(id);
			}, MIRROR_MS);
		}
	}

	log(frameId: string, key: number, message: string) {
		if (this.keys.get(frameId) !== key) return; // a frame since reloaded
		this.logs = [...this.logs, { frameId, message }].slice(-MAX_LOGS);
	}
}
