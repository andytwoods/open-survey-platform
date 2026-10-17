/**
 * The debugger's controls (task B11): step the run with given answers, go back, load a
 * fixture-style script and jump through it, compare with an expected trace, export the run.
 * It drives the preview host's engine state; the host keeps the device frames on it.
 */
import { back, canGoBack, next, tryAnswer, tryConsent, view, type State } from '@osp/engine';
import type { PreviewHost } from '../preview/host.svelte';
import { compareStep, exportScript, parseScript, playScript, settle, startState, traceStep, type Diff, type Script } from './script';

export interface Expected {
	format?: string;
	steps: Array<Record<string, unknown>>;
}

/** An answer typed in the debugger: JSON if it reads as JSON (3, "x", ["a"], null), else text. */
export function parseAnswer(raw: string): unknown {
	const t = raw.trim();
	if (t === '') return undefined;
	try {
		return JSON.parse(t);
	} catch {
		return raw;
	}
}

export class DebuggerState {
	script = $state.raw<Script | null>(null);
	/** Actions of the script played so far (the step shown is `steps[cursor]`). */
	cursor = $state(0);
	expected = $state.raw<Expected | null>(null);
	message = $state<string | null>(null);
	/** The last action was a `next` (a trace step only reports errors after one). */
	private afterNext = $state(true);

	constructor(private host: PreviewHost) {}

	get state(): State | null {
		void this.host.version;
		return this.host.state;
	}

	/** True while the run is the loaded script's (a participant step in a frame leaves it). */
	following(): boolean {
		void this.host.version;
		return !!this.script && this.host.source === 'debugger';
	}

	/** The current step in fixture trace format (FORMAT.md §3). */
	trace() {
		const s = this.state;
		if (!s) return null;
		const index = this.following() ? this.cursor : s.data.history.length - (s.data.ended ? 0 : 1);
		return traceStep(s, index, this.following() ? this.afterNext : true);
	}

	/** Differences from the expected step (null: nothing to compare with). */
	diffs(): Diff[] | null {
		const t = this.trace();
		const want = this.expected?.steps?.[this.cursor];
		if (!t || !want || !this.following()) return null;
		return compareStep(want, t);
	}

	/** Answer the visible questions with `values` (raw text by id), then Next. */
	stepNext(values: Record<string, string>) {
		let s = this.state;
		if (!s) return;
		this.message = null;
		const problems: string[] = [];
		const visible = view(s).items.flatMap((i) => [i.id, ...(i.rows?.map((r) => r.id) ?? [])]);
		for (const [id, raw] of Object.entries(values)) {
			if (!visible.includes(id)) continue;
			const v = parseAnswer(raw);
			if (v === undefined) continue;
			const r = tryAnswer(s, id, v);
			if (r.rejected) problems.push(`${id}: ${r.rejected}`);
			else s = r.state;
		}
		const out = next(s);
		s = settle(out.state, this.host.quotas);
		if (out.result.outcome === 'invalid') problems.push('The page did not advance: see the errors.');
		if (problems.length) this.message = problems.join(' ');
		this.afterNext = true;
		this.detach();
		this.host.setState(s);
	}

	/** The consent page (semantics §11): agree or decline. */
	consent(decision: 'agree' | 'decline') {
		const s = this.state;
		if (!s) return;
		const r = tryConsent(s, decision);
		if (r.rejected) {
			this.message = `${decision}: ${r.rejected}`;
			return;
		}
		this.afterNext = false;
		this.detach();
		this.host.setState(r.state);
	}

	canBack(): boolean {
		const s = this.state;
		return !!s && canGoBack(s);
	}

	back() {
		const s = this.state;
		if (!s) return;
		this.afterNext = false;
		this.detach();
		this.host.setState(back(s));
	}

	restart() {
		this.afterNext = true;
		if (this.script) this.jump(0);
		else this.host.restart();
	}

	/** Hand-driven steps leave the script: the run no longer follows it. */
	private detach() {
		if (this.script) {
			this.script = null;
			this.expected = null;
		}
	}

	loadScript(text: string): boolean {
		const r = parseScript(text);
		if ('error' in r) {
			this.message = r.error;
			return false;
		}
		const sc = r.script;
		this.host.seed = sc.sessionSeed;
		this.host.assigned = { ...(sc.server?.conditions ?? {}) };
		this.host.quotas = { ...(sc.server?.quotas ?? {}) };
		this.host.language = sc.language;
		this.script = sc;
		this.message = `Loaded script ${sc.id ?? ''} (${sc.actions.length} actions).`.replace('  ', ' ');
		this.jump(0);
		return true;
	}

	loadExpected(text: string): boolean {
		try {
			const e = JSON.parse(text) as Expected;
			if (!e || !Array.isArray(e.steps)) throw new Error('An expected trace has a "steps" list.');
			this.expected = e;
			this.message = `Loaded expected trace (${e.steps.length} steps).`;
			return true;
		} catch (e) {
			this.message = (e as Error).message;
			return false;
		}
	}

	/** Replay the script's first `k` actions from a fresh start. */
	jump(k: number) {
		const plan = this.host.plan;
		const sc = this.script;
		if (!plan) return;
		if (!sc) {
			this.host.setState(startState(plan, { sessionSeed: this.host.seed, server: { conditions: this.host.assigned } }));
			return;
		}
		const played = playScript(plan, sc, k);
		this.cursor = played.steps.length - 1;
		this.afterNext = this.cursor === 0 || sc.actions[this.cursor - 1]?.do === 'next';
		this.message = played.error ? played.error.message : null;
		this.host.setState(played.state);
	}

	stepScript() {
		if (this.script && this.cursor < this.script.actions.length) this.jump(this.cursor + 1);
	}

	exportRun(): string {
		const s = this.state;
		return s ? JSON.stringify(exportScript(s), null, 2) : '';
	}
}
