/**
 * Builder ⇄ preview frame protocol (task B11). Each device frame is a same-origin iframe
 * (`/preview-frame?frame=<id>`) running `web/runtime`'s participant app in preview mode. On
 * load it finds the host on its parent window and attaches; the host tells it what to run
 * (`FrameConfig`) and the frame reports every engine change back as a snapshot.
 *
 * Everything crosses as JSON text, so no object from one window's realm is used by the
 * other's engine (big.js values, `instanceof`).
 */

export const HOST_KEY = '__ospPreviewHost';

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

export function findHost(w: Window): PreviewBridge | null {
	try {
		const host = (w.parent as unknown as Record<string, unknown>)[HOST_KEY];
		return host && typeof host === 'object' ? (host as PreviewBridge) : null;
	} catch {
		return null; // cross-origin parent: no host
	}
}
