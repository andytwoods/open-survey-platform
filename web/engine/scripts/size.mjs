// Engine bundle size: minified ES module of src/index.ts (with big.js), raw and gzip.
// Informational (runtime-design.md §3: budget 30 KB gzip is a target, not a gate).
//   make engine-size
import { readFileSync, mkdtempSync, rmSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { gzipSync } from 'node:zlib';
import { build } from 'vite';

const root = resolve(import.meta.dirname, '..');
const out = mkdtempSync(join(tmpdir(), 'osp-engine-size-'));
try {
	await build({
		root,
		logLevel: 'warn',
		configFile: false,
		build: {
			outDir: out,
			emptyOutDir: true,
			minify: true,
			lib: { entry: join(root, 'src/index.ts'), formats: ['es'], fileName: 'engine' }
		}
	});
	for (const f of readdirSync(out)) {
		const code = readFileSync(join(out, f));
		const kb = (n) => `${(n / 1024).toFixed(1)} KB`;
		console.log(`engine bundle ${f}: ${kb(code.length)} min, ${kb(gzipSync(code, { level: 9 }).length)} gzip`);
	}
} finally {
	rmSync(out, { recursive: true, force: true });
}
