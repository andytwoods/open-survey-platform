// Generates the app icons from the one source mark (brand/mark.svg): favicon.svg, PNGs,
// the apple-touch-icon and a web manifest for the builder (static/) and the participant app
// (runtime/public/), plus the GitHub social preview (brand/social-preview.png).
// Rendered with Playwright's Chromium, so no image library is needed. The outputs are
// committed; rerun after editing the mark: `pnpm -C web/builder exec node scripts/icons.mjs`.
// web/tooling/icons.test.ts checks they exist, have the right sizes and match the mark.
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const brand = join(root, 'brand');
const mark = readFileSync(join(brand, 'mark.svg'), 'utf8');
const TILE = '<rect class="tile" width="64" height="64" rx="14" />';
if (!mark.includes(TILE)) throw new Error(`icons: brand/mark.svg must contain ${TILE}`);
/** Square corners: iOS rounds the apple-touch-icon itself, and maskable icons get cropped. */
const fullBleed = mark.replace(TILE, TILE.replace('rx="14"', 'rx="0"'));

const sized = (svg, size) => svg.replace('width="64" height="64"', `width="${size}" height="${size}"`);

/** name → [svg source, size] */
const PNGS = {
	'favicon-32.png': [mark, 32],
	'apple-touch-icon.png': [fullBleed, 180],
	'icon-192.png': [mark, 192],
	'icon-512.png': [mark, 512],
	'icon-maskable-512.png': [fullBleed, 512]
};

const ICONS = [
	{ src: 'favicon.svg', sizes: 'any', type: 'image/svg+xml' },
	{ src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
	{ src: 'icon-512.png', sizes: '512x512', type: 'image/png' },
	{ src: 'icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' }
];

/** Icon `src`s are relative to the manifest, so each app's folder can be served under any prefix. */
const TARGETS = [
	{ dir: join(root, 'web', 'builder', 'static'), name: 'Open Survey Platform', short_name: 'OSP' },
	{ dir: join(root, 'web', 'runtime', 'public'), name: 'Survey', short_name: 'Survey' }
];

const SOCIAL = `<!doctype html><html><head><style>
	body { margin: 0; width: 1280px; height: 640px; display: flex; align-items: center; gap: 72px;
		padding: 0 120px; box-sizing: border-box; background: #ffffff; color: #1d2433;
		font-family: 'Segoe UI', system-ui, -apple-system, Roboto, 'Helvetica Neue', Arial, sans-serif; }
	h1 { font-size: 76px; line-height: 1.05; margin: 0 0 24px; font-weight: 650; }
	p { font-size: 34px; line-height: 1.35; margin: 0; color: #505a6b; }
	.bar { position: absolute; left: 0; right: 0; bottom: 0; height: 20px; background: #5b3fd1; }
</style></head><body>
	${sized(mark, 260)}
	<div><h1>Open Survey Platform</h1><p>A survey builder for academic research.<br />MIT-licensed; exports to other platforms.</p></div>
	<div class="bar"></div>
</body></html>`;

const browser = await chromium.launch();
try {
	const page = await browser.newPage({ colorScheme: 'light' });
	const shots = {};
	for (const [name, [svg, size]] of Object.entries(PNGS)) {
		await page.setViewportSize({ width: size, height: size });
		await page.setContent(`<!doctype html><body style="margin:0;background:transparent">${sized(svg, size)}</body>`);
		shots[name] = await page.screenshot({ omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } });
	}
	for (const t of TARGETS) {
		mkdirSync(t.dir, { recursive: true });
		copyFileSync(join(brand, 'mark.svg'), join(t.dir, 'favicon.svg'));
		for (const [name, png] of Object.entries(shots)) writeFileSync(join(t.dir, name), png);
		const manifest = {
			name: t.name,
			short_name: t.short_name,
			icons: ICONS,
			theme_color: '#5b3fd1',
			background_color: '#ffffff'
		};
		writeFileSync(join(t.dir, 'site.webmanifest'), JSON.stringify(manifest, null, '\t') + '\n');
	}
	await page.setViewportSize({ width: 1280, height: 640 });
	await page.setContent(SOCIAL);
	writeFileSync(join(brand, 'social-preview.png'), await page.screenshot({ clip: { x: 0, y: 0, width: 1280, height: 640 } }));
} finally {
	await browser.close();
}
console.log(`icons: ${Object.keys(PNGS).length} PNGs + favicon.svg + site.webmanifest for ${TARGETS.length} apps, social preview`);
