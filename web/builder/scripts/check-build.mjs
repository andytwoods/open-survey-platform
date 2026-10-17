// Checks the production build (`make web-build`): build/manifest.json lists exactly one
// entry per page (no dev-only pages), every listed file exists, each entry module exports
// `mount`, and pages share chunks rather than each carrying its own copy.
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const PAGES = ['list', 'editor', 'flow', 'settings', 'appearance', 'themes', 'preview-frame'];
const build = join(dirname(fileURLToPath(import.meta.url)), '..', process.argv[2] ?? 'build');
const fail = (msg) => {
	console.error(`check-build: ${msg}`);
	process.exit(1);
};

const path = join(build, 'manifest.json');
if (!existsSync(path)) fail(`no ${path}`);
const manifest = JSON.parse(readFileSync(path, 'utf8'));
if (manifest.version !== 1) fail('manifest version must be 1');
const names = Object.keys(manifest.pages ?? {}).sort();
if (JSON.stringify(names) !== JSON.stringify([...PAGES].sort())) {
	fail(`pages must be exactly ${PAGES.join(', ')}; got ${names.join(', ')}`);
}
const shared = new Map();
for (const name of PAGES) {
	const p = manifest.pages[name];
	for (const f of [p.js, ...p.css, ...p.preload]) {
		if (!existsSync(join(build, f))) fail(`${name}: missing ${f}`);
	}
	const js = readFileSync(join(build, p.js), 'utf8');
	if (!/export\s*\{[^}]*\bmount\b[^}]*\}|export\s+(const|function)\s+mount\b/.test(js)) {
		fail(`${name}: ${p.js} does not export mount`);
	}
	for (const c of p.preload) shared.set(c, (shared.get(c) ?? 0) + 1);
}
if (![...shared.values()].some((n) => n === PAGES.length)) fail('no chunk is shared by every page');
console.log(`check-build: ${PAGES.length} pages, ${shared.size} shared chunks, manifest ok`);
