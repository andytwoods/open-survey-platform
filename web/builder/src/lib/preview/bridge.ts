/**
 * Builder ⇄ preview frame protocol (task B11, planning/pages-split.md D10). Each device
 * frame is a sandboxed iframe (the `previewFrame` page, `?frame=<id>&origin=<builder
 * origin>`) running `web/runtime`'s participant app in preview mode. The two sides talk
 * only through `postMessage`, and each checks every message's origin, source window and
 * schema before acting on it. The frame never gets the API base or a CSRF token: it is
 * handed a compiled plan and reports engine snapshots back.
 *
 * Everything crosses as JSON text, so no object from one window's realm is used by the
 * other's engine (big.js values, `instanceof`).
 */

export const PROTOCOL = 'osp-preview';
export const PROTOCOL_VERSION = 1;

/** Caps, so a hostile or broken peer cannot make us parse megabytes per message. */
const MAX_FRAME_ID = 40;
const MAX_JSON = 20_000_000;
const MAX_PHASE = 40;

export interface FrameConfig {
	/** Bumped on every load: the frame remounts the participant app. */
	key: number;
	planJson: string;
	sessionSeed: number;
	assigned: Record<string, string | number>;
	quotas: Record<string, 'open' | 'full'>;
	/** Start from this engine snapshot (JSON), or null for the first page. */
	snapshotJson: string | null;
	language?: string;
}

export interface FrameHandle {
	load(cfg: FrameConfig): void;
}

export interface PreviewBridge {
	/** A frame is ready; returns what it should run now (null: nothing yet). */
	attach(frameId: string, frame: FrameHandle): FrameConfig | null;
	detach(frameId: string): void;
	/** The engine in `frameId` changed: its snapshot (JSON) and the app's phase. */
	changed(frameId: string, key: number, snapshotJson: string, phase: string): void;
}

/** Frame → builder. */
export type FrameMessage =
	| { protocol: typeof PROTOCOL; v: 1; type: 'attach'; frameId: string }
	| { protocol: typeof PROTOCOL; v: 1; type: 'detach'; frameId: string }
	| { protocol: typeof PROTOCOL; v: 1; type: 'changed'; frameId: string; key: number; snapshotJson: string; phase: string };

/** Builder → frame. */
export interface HostMessage {
	protocol: typeof PROTOCOL;
	v: 1;
	type: 'load';
	cfg: FrameConfig;
}

function isObj(v: unknown): v is Record<string, unknown> {
	return typeof v === 'object' && v !== null && !Array.isArray(v);
}

const isStr = (v: unknown, max: number): v is string => typeof v === 'string' && v.length <= max;
const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v);

export function isFrameId(v: unknown): v is string {
	return isStr(v, MAX_FRAME_ID) && /^[A-Za-z0-9_-]+$/.test(v);
}

/** A message from a frame, or null if it is not one of ours (or malformed). */
export function parseFrameMessage(data: unknown): FrameMessage | null {
	if (!isObj(data) || data.protocol !== PROTOCOL || data.v !== PROTOCOL_VERSION) return null;
	if (!isFrameId(data.frameId)) return null;
	if (data.type === 'attach' || data.type === 'detach') {
		return { protocol: PROTOCOL, v: 1, type: data.type, frameId: data.frameId };
	}
	if (data.type === 'changed') {
		if (!isInt(data.key) || !isStr(data.snapshotJson, MAX_JSON) || !isStr(data.phase, MAX_PHASE)) return null;
		return {
			protocol: PROTOCOL,
			v: 1,
			type: 'changed',
			frameId: data.frameId,
			key: data.key,
			snapshotJson: data.snapshotJson,
			phase: data.phase
		};
	}
	return null;
}

function isScalarMap(v: unknown): v is Record<string, string | number> {
	return isObj(v) && Object.values(v).every((x) => typeof x === 'string' || (typeof x === 'number' && Number.isFinite(x)));
}

/** A message from the builder, or null if it is not one of ours (or malformed). */
export function parseHostMessage(data: unknown): HostMessage | null {
	if (!isObj(data) || data.protocol !== PROTOCOL || data.v !== PROTOCOL_VERSION || data.type !== 'load') return null;
	const c = data.cfg;
	if (!isObj(c)) return null;
	if (!isInt(c.key) || !isStr(c.planJson, MAX_JSON) || !isInt(c.sessionSeed)) return null;
	if (!isScalarMap(c.assigned)) return null;
	if (!isObj(c.quotas) || !Object.values(c.quotas).every((q) => q === 'open' || q === 'full')) return null;
	if (c.snapshotJson !== null && !isStr(c.snapshotJson, MAX_JSON)) return null;
	if (c.language !== undefined && !isStr(c.language, 40)) return null;
	return {
		protocol: PROTOCOL,
		v: 1,
		type: 'load',
		cfg: {
			key: c.key,
			planJson: c.planJson,
			sessionSeed: c.sessionSeed,
			assigned: { ...c.assigned },
			quotas: { ...(c.quotas as Record<string, 'open' | 'full'>) },
			snapshotJson: c.snapshotJson,
			language: c.language
		}
	};
}

export function hostMessage(cfg: FrameConfig): HostMessage {
	return { protocol: PROTOCOL, v: 1, type: 'load', cfg };
}

/** The frame's URL: the host's previewFrame link plus the frame id and our origin. */
export function frameUrl(template: string, frameId: string, builderOrigin: string): string {
	const sep = template.includes('?') ? '&' : '?';
	const q = new URLSearchParams({ frame: frameId, origin: builderOrigin }).toString();
	const hashAt = template.indexOf('#');
	return hashAt < 0 ? `${template}${sep}${q}` : `${template.slice(0, hashAt)}${sep}${q}${template.slice(hashAt)}`;
}

/**
 * The builder side: listen for frame messages on `w`, accept only those from `frameOrigin`
 * whose source is the iframe registered for that frame id, and route them to `bridge`.
 */
export function listenForFrames(
	w: Window,
	frameOrigin: string,
	frameWindow: (frameId: string) => Window | null,
	bridge: PreviewBridge
): () => void {
	const onMessage = (e: MessageEvent) => {
		if (e.origin !== frameOrigin) return;
		const msg = parseFrameMessage(e.data);
		if (!msg) return;
		const source = frameWindow(msg.frameId);
		if (!source || e.source !== source) return;
		if (msg.type === 'attach') {
			const handle: FrameHandle = {
				load: (cfg) => source.postMessage(hostMessage(cfg), frameOrigin)
			};
			const cfg = bridge.attach(msg.frameId, handle);
			if (cfg) handle.load(cfg);
		} else if (msg.type === 'detach') bridge.detach(msg.frameId);
		else bridge.changed(msg.frameId, msg.key, msg.snapshotJson, msg.phase);
	};
	w.addEventListener('message', onMessage);
	return () => w.removeEventListener('message', onMessage);
}
