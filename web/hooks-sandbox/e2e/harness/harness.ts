/**
 * Test harness page (runtime.html, inside index.html). Exposes the package on `window.H`
 * so Playwright specs can build scenarios with hook sources as strings.
 */

import * as engine from '@osp/engine';
import { HookHost, type HookHostOptions } from '../../src/host.ts';
import { HookRunner, type FireOutcome, type InflightMarker, type InflightStore } from '../../src/runner.ts';
import { FRAME_SRCDOC } from '../../src/sandbox-source.ts';
import { sourceChecksum, type HookManifest } from '../../src/manifest.ts';
import { hookManifest, hookPlan } from '../../test/fixtures.ts';

// localStorage, so a reload after a renderer crash (even in a new tab) can resume.
const SNAP_KEY = 'osp-hooks-e2e-snapshot';
const MARK_KEY = 'osp-hooks-e2e-inflight';

const inflightStore: InflightStore = {
	get: () => JSON.parse(localStorage.getItem(MARK_KEY) ?? 'null') as InflightMarker | null,
	set: (m) => (m ? localStorage.setItem(MARK_KEY, JSON.stringify(m)) : localStorage.removeItem(MARK_KEY))
};

function clock() {
	let t = 1_000;
	return () => (t += 100);
}

interface MakeOpts {
	manifest?: Partial<HookManifest>;
	host?: Partial<HookHostOptions>;
	/** Persist every state change and the in-flight marker to localStorage (refresh tests). */
	persist?: boolean;
	/** Restore from sessionStorage instead of starting. */
	restore?: boolean;
	/** Override parent origin (defaults to this page's origin). */
	parentOrigin?: string;
}

function make(source: string, opts: MakeOpts = {}) {
	const plan = hookPlan();
	const base = hookManifest(source, {
		parent: {
			origin: opts.parentOrigin ?? location.origin,
			messages: hookManifest(source).parent!.messages
		}
	});
	// Declare only the handlers the source mentions (a declared handler the script never
	// registers is a hook error, which for a flow-critical one means retry → hook-failed).
	const handlers = Object.fromEntries(Object.entries(base.handlers).filter(([ev]) => source.includes(ev)));
	const manifest: HookManifest = { ...base, handlers, ...opts.manifest, exportsConfirmedFor: sourceChecksum(source) };
	if (opts.manifest && 'exportsConfirmedFor' in opts.manifest) manifest.exportsConfirmedFor = opts.manifest.exportsConfirmedFor;
	let state: engine.State;
	if (opts.restore) {
		const snap = JSON.parse(localStorage.getItem(SNAP_KEY) ?? 'null');
		const r = engine.restore(plan, snap, { clock: clock() });
		if (!engine.isState(r)) throw new Error(`restore failed: ${JSON.stringify(r.error)}`);
		state = r;
	} else {
		state = engine.start(plan, { sessionSeed: 7, clock: clock(), sessionId: 'sess-e2e', urlParams: { PROLIFIC_PID: 'pp1', email: 'secret@example.org' } });
	}
	const host = new HookHost({ source, ...opts.host });
	const runner = new HookRunner({
		plan,
		manifest,
		invoker: host,
		state,
		onState: opts.persist ? (s) => localStorage.setItem(SNAP_KEY, JSON.stringify(engine.snapshot(s))) : undefined,
		inflight: opts.persist ? inflightStore : undefined
	});
	if (opts.persist) {
		// Local-first: the session is saved before anything runs (runtime-design.md §5).
		localStorage.setItem(SNAP_KEY, JSON.stringify(engine.snapshot(state)));
		addEventListener('pagehide', () => runner.unloading());
	}
	return { plan, manifest, host, runner };
}

/** Draw the current page the way a runtime would: researcher text as is, values escaped. */
function render(runner: HookRunner): void {
	const v = engine.view(runner.state);
	const survey = document.getElementById('survey')!;
	const items = v.items.map((i) => `<div class="item" data-id="${i.id}"><label>${engine.toHtml(i.label)}</label></div>`).join('');
	const errors = Object.entries(v.errors)
		.map(([id, e]) => `<li data-id="${id}">${engine.toHtml(e.message)}</li>`)
		.join('');
	survey.innerHTML = `<h1>${engine.toHtml(v.title)}</h1>${items}<ul class="errors">${errors}</ul>`;
}

const hookEvents = (s: engine.State) =>
	s.data.events.filter((e) => e.type === 'resolve' && e.effect.kind === 'hook') as Array<
		Extract<engine.EngineEvent, { type: 'resolve' }>
	>;

declare global {
	interface Window {
		H: typeof H;
		__pwned?: unknown;
	}
}

const H = {
	engine,
	make,
	render,
	hookEvents,
	FRAME_SRCDOC,
	clearSnapshot: () => {
		localStorage.removeItem(SNAP_KEY);
		localStorage.removeItem(MARK_KEY);
	},
	inflight: () => inflightStore.get(),
	sleep: (ms: number) => new Promise((r) => setTimeout(r, ms)),
	outcome: (o: FireOutcome) => o
};

window.H = H;
document.documentElement.dataset.ready = 'yes';
