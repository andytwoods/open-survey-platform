/**
 * HookHost: runs researcher hooks in a sandboxed iframe + dedicated worker and talks to it
 * over one transferred MessagePort (runtime-design.md §7a).
 *
 * - The iframe has `sandbox="allow-scripts"` only (opaque origin: no same-origin, popups,
 *   navigation, forms or downloads) and a `default-src 'none'` CSP in its srcdoc.
 * - Window messages are never read: the host listens to its own end of the port only.
 * - Messages must be JSON strings within a size cap; a message that is not a well-formed
 *   reply to the invocation in flight is a violation.
 * - Deadlines are enforced from outside. On timeout, a violation or flooding the host
 *   removes the iframe (which kills its worker) and respawns on the next call. After
 *   `maxSpawns` spawns the host gives up and every call fails fast.
 */

import { FRAME_SRCDOC, workerSource } from './sandbox-source.ts';

export interface InvokeRequest {
	invocationId: string;
	event: string;
	ctx: unknown;
	data: unknown;
	seed: number;
	now: number;
	timeoutMs: number;
}

export type InvokeOutcome =
	| { status: 'ok'; actions: unknown[] }
	| { status: 'error' | 'timeout' | 'violation' | 'unavailable'; error: string };

/** What the engine integration needs from a sandbox (tests use a fake). */
export interface Invoker {
	invoke(req: InvokeRequest): Promise<InvokeOutcome>;
	dispose(): void;
}

export interface HookHostOptions {
	/** The researcher's script (the manifest's `source`). */
	source: string;
	/** Where the hidden iframe goes (default `document.body`). */
	container?: HTMLElement;
	/** Time for a fresh sandbox to report ready (its top-level code runs in this). */
	spawnTimeoutMs?: number;
	maxMessageChars?: number;
	/** More than `count` messages within `windowMs` is flooding. */
	flood?: { count: number; windowMs: number };
	maxSpawns?: number;
	/** Test only: keep the egress globals in the worker, to prove the CSP alone blocks them. */
	lockdown?: boolean;
}

export interface HostStats {
	spawns: number;
	kills: number;
	violations: string[];
}

interface Inflight {
	id: string;
	resolve: (o: InvokeOutcome) => void;
	timer: ReturnType<typeof setTimeout>;
}

export class HookHost implements Invoker {
	readonly stats: HostStats = { spawns: 0, kills: 0, violations: [] };
	private readonly opts: Required<Omit<HookHostOptions, 'container'>> & { container?: HTMLElement };
	private readonly script: string;
	private frame: HTMLIFrameElement | null = null;
	private port: MessagePort | null = null;
	private ready: Promise<boolean> | null = null;
	private onReady: ((ok: boolean) => void) | null = null;
	private inflight: Inflight | null = null;
	private queue: Promise<unknown> = Promise.resolve();
	private recent: number[] = [];
	private disposed = false;

	constructor(opts: HookHostOptions) {
		this.opts = {
			spawnTimeoutMs: 3000,
			maxMessageChars: 64 * 1024,
			flood: { count: 40, windowMs: 1000 },
			maxSpawns: 10,
			lockdown: true,
			...opts
		};
		this.script = workerSource(opts.source, { lockdown: this.opts.lockdown });
	}

	/** Run one hook. Calls are queued: one invocation in flight at a time. */
	invoke(req: InvokeRequest): Promise<InvokeOutcome> {
		const run = this.queue.then(() => this.run(req));
		this.queue = run.catch(() => undefined);
		return run;
	}

	dispose(): void {
		this.disposed = true;
		this.kill('disposed', false);
	}

	/** The live iframe (tests inspect its attributes). */
	get iframe(): HTMLIFrameElement | null {
		return this.frame;
	}

	private async run(req: InvokeRequest): Promise<InvokeOutcome> {
		if (this.disposed) return { status: 'unavailable', error: 'disposed' };
		if (!(await this.ensure())) return { status: 'unavailable', error: 'sandbox-unavailable' };
		const port = this.port!;
		return new Promise<InvokeOutcome>((resolve) => {
			const timer = setTimeout(() => {
				if (this.inflight?.id !== req.invocationId) return;
				this.inflight = null;
				this.kill('timeout');
				resolve({ status: 'timeout', error: 'timeout' });
			}, req.timeoutMs);
			this.inflight = { id: req.invocationId, resolve, timer };
			let msg: string;
			try {
				msg = JSON.stringify({
					t: 'invoke',
					id: req.invocationId,
					event: req.event,
					ctx: req.ctx,
					data: req.data,
					seed: req.seed,
					now: req.now
				});
			} catch {
				this.finish({ status: 'error', error: 'unserialisable-context' });
				return;
			}
			port.postMessage(msg);
		});
	}

	private finish(o: InvokeOutcome): void {
		const f = this.inflight;
		if (!f) return;
		this.inflight = null;
		clearTimeout(f.timer);
		f.resolve(o);
	}

	private ensure(): Promise<boolean> {
		if (this.ready) return this.ready;
		if (this.stats.spawns >= this.opts.maxSpawns) return Promise.resolve(false);
		this.ready = this.spawn();
		return this.ready;
	}

	private spawn(): Promise<boolean> {
		this.stats.spawns++;
		this.recent = [];
		const doc = (this.opts.container ?? document.body).ownerDocument;
		const frame = doc.createElement('iframe');
		frame.setAttribute('sandbox', 'allow-scripts');
		frame.setAttribute('referrerpolicy', 'no-referrer');
		frame.setAttribute('allow', "camera 'none'; microphone 'none'; geolocation 'none'; usb 'none'; payment 'none'; clipboard-read 'none'; clipboard-write 'none'");
		frame.setAttribute('aria-hidden', 'true');
		frame.setAttribute('tabindex', '-1');
		frame.setAttribute('title', 'hooks');
		frame.style.cssText = 'position:absolute;width:0;height:0;border:0;visibility:hidden';
		frame.srcdoc = FRAME_SRCDOC;
		const channel = new MessageChannel();
		const port = channel.port1;
		this.frame = frame;
		this.port = port;
		port.onmessage = (e) => this.receive(port, e.data);
		port.onmessageerror = () => this.violation(port, 'messageerror');
		const ready = new Promise<boolean>((resolve) => {
			const timer = setTimeout(() => {
				if (this.port !== port) return;
				this.onReady = null;
				this.kill('spawn-timeout');
				resolve(false);
			}, this.opts.spawnTimeoutMs);
			this.onReady = (ok) => {
				clearTimeout(timer);
				this.onReady = null;
				resolve(ok);
			};
		});
		frame.addEventListener(
			'load',
			() => {
				if (this.frame !== frame) return;
				// The target is the frame we created, never a window that messaged us.
				frame.contentWindow?.postMessage({ osp: 'hooks-init', workerSource: this.script }, '*', [channel.port2]);
			},
			{ once: true }
		);
		(this.opts.container ?? doc.body).appendChild(frame);
		return ready;
	}

	private receive(port: MessagePort, data: unknown): void {
		if (port !== this.port) return;
		const t = Date.now();
		this.recent.push(t);
		while (this.recent.length && this.recent[0]! < t - this.opts.flood.windowMs) this.recent.shift();
		if (this.recent.length > this.opts.flood.count) return this.violation(port, 'flood');
		if (typeof data !== 'string') return this.violation(port, 'not-a-string');
		if (data.length > this.opts.maxMessageChars) return this.violation(port, 'too-large');
		let m: unknown;
		try {
			m = JSON.parse(data);
		} catch {
			return this.violation(port, 'not-json');
		}
		if (!m || typeof m !== 'object' || Array.isArray(m)) return this.violation(port, 'not-an-object');
		const msg = m as Record<string, unknown>;
		if (msg.t === 'ready' && this.onReady) return this.onReady(true);
		if (msg.t !== 'result' || !this.inflight || msg.id !== this.inflight.id) return this.violation(port, 'unexpected-message');
		if (msg.ok === true) {
			if (!Array.isArray(msg.actions)) return this.violation(port, 'bad-result');
			this.finish({ status: 'ok', actions: msg.actions });
		} else {
			this.finish({ status: 'error', error: typeof msg.error === 'string' ? msg.error.slice(0, 80) : 'error' });
		}
	}

	private violation(port: MessagePort, why: string): void {
		if (port !== this.port) return;
		this.stats.violations.push(why);
		this.finish({ status: 'violation', error: why });
		this.kill(why);
	}

	/** Remove the iframe (its worker dies with it). The next call respawns. */
	private kill(why: string, count = true): void {
		void why;
		if (count && this.frame) this.stats.kills++;
		const port = this.port;
		this.port = null;
		if (port) {
			port.onmessage = null;
			port.close();
		}
		this.frame?.remove();
		this.frame = null;
		this.ready = null;
		this.onReady?.(false);
		this.onReady = null;
		this.recent = [];
		const f = this.inflight;
		if (f) this.finish({ status: 'violation', error: why });
	}
}
