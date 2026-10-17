// Byte helpers for the figure exports (task V4): CRC-32 (PNG chunks and ZIP entries) and
// big/little-endian writers. Pure; no dependencies.

const TABLE = (() => {
	const t = new Uint32Array(256);
	for (let n = 0; n < 256; n++) {
		let c = n;
		for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
		t[n] = c >>> 0;
	}
	return t;
})();

/** CRC-32 (ISO 3309, as used by PNG and ZIP) of `parts` taken as one byte string. */
export function crc32(...parts: Uint8Array[]): number {
	let c = 0xffffffff;
	for (const bytes of parts) {
		for (let i = 0; i < bytes.length; i++) c = TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
	}
	return (c ^ 0xffffffff) >>> 0;
}

export const utf8 = (s: string): Uint8Array => new TextEncoder().encode(s);

export function concat(parts: Uint8Array[]): Uint8Array {
	const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
	let at = 0;
	for (const p of parts) {
		out.set(p, at);
		at += p.length;
	}
	return out;
}
