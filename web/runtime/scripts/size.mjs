// Runtime bundle size (gzip), informational. Target (runtime-design §3): <= 90 KB gzip total.
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { gzipSync } from 'node:zlib';

const dist = new URL('../dist/', import.meta.url).pathname;
let raw = 0;
let gz = 0;
for (const f of readdirSync(dist)) {
	if (!/\.(js|css|html)$/.test(f)) continue;
	const buf = readFileSync(join(dist, f));
	const z = gzipSync(buf, { level: 9 }).length;
	raw += buf.length;
	gz += z;
	console.log(`${f.padEnd(28)} ${(buf.length / 1024).toFixed(1).padStart(7)} KB  ${(z / 1024).toFixed(1).padStart(6)} KB gzip`);
}
const kb = gz / 1024;
console.log(`total ${(raw / 1024).toFixed(1)} KB, ${kb.toFixed(1)} KB gzip (target <= 90 KB): ${kb <= 90 ? 'within' : 'OVER'}`);
