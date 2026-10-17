// PNG physical size (task V4, V-D6): a canvas PNG carries no DPI, so the exported file
// gets a pHYs chunk (pixels per metre) right after IHDR, replacing any existing one.
// Journals read it to place the figure at 85 / 180 mm. Pure; no dependencies.
import { concat, crc32 } from './bytes';

const SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10];
const ascii = (s: string) => Uint8Array.from(s, (c) => c.charCodeAt(0));

export interface PngInfo {
	width: number;
	height: number;
	/** From pHYs (unit: metre), rounded to a whole DPI; null when there is none. */
	dpi: number | null;
	chunks: string[];
}

function isPng(b: Uint8Array): boolean {
	return b.length >= 33 && SIGNATURE.every((v, i) => b[i] === v);
}

const u32 = (b: Uint8Array, at: number) => new DataView(b.buffer, b.byteOffset + at, 4).getUint32(0);

/** Pixels per metre for a DPI (300 dpi = 11811). */
export const pixelsPerMetre = (dpi: number): number => Math.round(dpi / 0.0254);

function chunk(type: string, data: Uint8Array): Uint8Array {
	const head = new Uint8Array(8);
	const dv = new DataView(head.buffer);
	dv.setUint32(0, data.length);
	head.set(ascii(type), 4);
	const tail = new Uint8Array(4);
	new DataView(tail.buffer).setUint32(0, crc32(ascii(type), data));
	return concat([head, data, tail]);
}

/** The PNG with a pHYs chunk for `dpi`. Throws on bytes that are not a PNG. */
export function withDpi(png: Uint8Array, dpi: number): Uint8Array {
	if (!isPng(png)) throw new Error('not a PNG');
	if (!(dpi > 0) || !Number.isFinite(dpi)) throw new Error('dpi must be a positive number');
	const ppm = pixelsPerMetre(dpi);
	const data = new Uint8Array(9);
	const dv = new DataView(data.buffer);
	dv.setUint32(0, ppm);
	dv.setUint32(4, ppm);
	data[8] = 1; // unit: metre
	const parts: Uint8Array[] = [png.subarray(0, 8)];
	let at = 8;
	while (at + 12 <= png.length) {
		const len = u32(png, at);
		const type = String.fromCharCode(...png.subarray(at + 4, at + 8));
		const end = at + 12 + len;
		if (end > png.length) throw new Error('truncated PNG');
		if (type !== 'pHYs') parts.push(png.subarray(at, end));
		if (type === 'IHDR') parts.push(chunk('pHYs', data));
		at = end;
	}
	return concat(parts);
}

/** Width, height, DPI and chunk order of a PNG (for checks and tests). */
export function pngInfo(png: Uint8Array): PngInfo {
	if (!isPng(png)) throw new Error('not a PNG');
	const chunks: string[] = [];
	let dpi: number | null = null;
	let at = 8;
	while (at + 12 <= png.length) {
		const len = u32(png, at);
		const type = String.fromCharCode(...png.subarray(at + 4, at + 8));
		chunks.push(type);
		if (type === 'pHYs' && png[at + 16] === 1) dpi = Math.round(u32(png, at + 8) * 0.0254);
		at += 12 + len;
	}
	return { width: u32(png, 16), height: u32(png, 20), dpi, chunks };
}
