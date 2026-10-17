// A minimal ZIP writer for "Export all" (task V4): stored entries (no compression; PNGs are
// compressed already), UTF-8 names, CRC-32, one central directory. Every unzip tool and
// Python's zipfile read it. Pure; no dependencies, so nothing to licence-check.
import { concat, crc32, utf8 } from './bytes';

export interface ZipEntry {
	name: string;
	data: Uint8Array;
}

/** MS-DOS date and time of `d` (local time, 2-second resolution, 1980 at the earliest). */
function dosTime(d: Date): { time: number; date: number } {
	const year = Math.max(1980, d.getFullYear());
	return {
		time: (d.getHours() << 11) | (d.getMinutes() << 5) | Math.floor(d.getSeconds() / 2),
		date: ((year - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate()
	};
}

/** A store-only ZIP of `entries` (names must be unique). */
export function zipStore(entries: ZipEntry[], when: Date = new Date()): Uint8Array {
	const names = new Set<string>();
	const { time, date } = dosTime(when);
	const local: Uint8Array[] = [];
	const central: Uint8Array[] = [];
	let offset = 0;
	for (const e of entries) {
		if (names.has(e.name)) throw new Error(`duplicate ZIP entry ${e.name}`);
		names.add(e.name);
		const name = utf8(e.name);
		const crc = crc32(e.data);
		const head = new Uint8Array(30);
		const h = new DataView(head.buffer);
		h.setUint32(0, 0x04034b50, true);
		h.setUint16(4, 20, true); // version needed
		h.setUint16(6, 0x0800, true); // UTF-8 names
		h.setUint16(8, 0, true); // stored
		h.setUint16(10, time, true);
		h.setUint16(12, date, true);
		h.setUint32(14, crc, true);
		h.setUint32(18, e.data.length, true);
		h.setUint32(22, e.data.length, true);
		h.setUint16(26, name.length, true);
		h.setUint16(28, 0, true);
		local.push(head, name, e.data);

		const dir = new Uint8Array(46);
		const c = new DataView(dir.buffer);
		c.setUint32(0, 0x02014b50, true);
		c.setUint16(4, 20, true); // made by
		c.setUint16(6, 20, true);
		c.setUint16(8, 0x0800, true);
		c.setUint16(10, 0, true);
		c.setUint16(12, time, true);
		c.setUint16(14, date, true);
		c.setUint32(16, crc, true);
		c.setUint32(20, e.data.length, true);
		c.setUint32(24, e.data.length, true);
		c.setUint16(28, name.length, true);
		c.setUint32(42, offset, true);
		central.push(dir, name);
		offset += head.length + name.length + e.data.length;
	}
	const cd = concat(central);
	const end = new Uint8Array(22);
	const z = new DataView(end.buffer);
	z.setUint32(0, 0x06054b50, true);
	z.setUint16(8, entries.length, true);
	z.setUint16(10, entries.length, true);
	z.setUint32(12, cd.length, true);
	z.setUint32(16, offset, true);
	return concat([...local, cd, end]);
}

/** The entries of a store-only ZIP (reads the central directory; for checks and tests). */
export function readZip(zip: Uint8Array): ZipEntry[] {
	const dv = new DataView(zip.buffer, zip.byteOffset, zip.byteLength);
	let eocd = -1;
	for (let i = zip.length - 22; i >= 0; i--) {
		if (dv.getUint32(i, true) === 0x06054b50) {
			eocd = i;
			break;
		}
	}
	if (eocd < 0) throw new Error('not a ZIP');
	const count = dv.getUint16(eocd + 10, true);
	let at = dv.getUint32(eocd + 16, true);
	const out: ZipEntry[] = [];
	const dec = new TextDecoder();
	for (let i = 0; i < count; i++) {
		if (dv.getUint32(at, true) !== 0x02014b50) throw new Error('bad central directory');
		const method = dv.getUint16(at + 10, true);
		const crc = dv.getUint32(at + 16, true);
		const size = dv.getUint32(at + 20, true);
		const nameLen = dv.getUint16(at + 28, true);
		const extra = dv.getUint16(at + 30, true);
		const comment = dv.getUint16(at + 32, true);
		const lho = dv.getUint32(at + 42, true);
		const name = dec.decode(zip.subarray(at + 46, at + 46 + nameLen));
		if (method !== 0) throw new Error(`${name}: compressed entries are not supported`);
		const start = lho + 30 + dv.getUint16(lho + 26, true) + dv.getUint16(lho + 28, true);
		const data = zip.subarray(start, start + size);
		if (crc32(data) !== crc) throw new Error(`${name}: CRC mismatch`);
		out.push({ name, data });
		at += 46 + nameLen + extra + comment;
	}
	return out;
}
