// The app icons (G1): generated from brand/mark.svg by web/builder/scripts/icons.mjs and
// committed. Checks they are all there, the right size, and from the current mark.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const root = join(import.meta.dirname, '..', '..');
const mark = readFileSync(join(root, 'brand', 'mark.svg'), 'utf8');

/** Width and height from a PNG's IHDR chunk. */
function pngSize(path: string): [number, number] {
	const b = readFileSync(path);
	expect(b.subarray(1, 4).toString('latin1'), path).toBe('PNG');
	expect(b.subarray(12, 16).toString('latin1'), path).toBe('IHDR');
	return [b.readUInt32BE(16), b.readUInt32BE(20)];
}

interface WebManifest {
	name: string;
	short_name: string;
	theme_color: string;
	background_color: string;
	icons: { src: string; sizes: string; type: string; purpose?: string }[];
}

const APPS = {
	builder: join(root, 'web', 'builder', 'static'),
	runtime: join(root, 'web', 'runtime', 'public')
};

describe('the source mark', () => {
	it('is self-contained SVG: no scripts, images, fonts or external references', () => {
		expect(mark).toMatch(/^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg"/);
		expect(mark).not.toMatch(/<script|<image|<text|<foreignObject|href=|url\(|@import/i);
	});

	it('has a dark-scheme variant, so the favicon stays visible on dark tab bars', () => {
		expect(mark).toContain('@media (prefers-color-scheme: dark)');
	});
});

describe.each(Object.entries(APPS))('%s icons', (_app, dir) => {
	it('favicon.svg is the current mark', () => {
		expect(readFileSync(join(dir, 'favicon.svg'), 'utf8')).toBe(mark);
	});

	it('PNGs have their sizes', () => {
		for (const [f, n] of [
			['favicon-32.png', 32],
			['apple-touch-icon.png', 180],
			['icon-192.png', 192],
			['icon-512.png', 512],
			['icon-maskable-512.png', 512]
		] as const) {
			expect(pngSize(join(dir, f)), f).toEqual([n, n]);
		}
	});

	it('site.webmanifest names the app and lists icons that exist at their stated sizes', () => {
		const m = JSON.parse(readFileSync(join(dir, 'site.webmanifest'), 'utf8')) as WebManifest;
		expect(m.name).toBeTruthy();
		expect(m.short_name).toBeTruthy();
		expect(m.theme_color).toMatch(/^#[0-9a-f]{6}$/);
		expect(m.background_color).toMatch(/^#[0-9a-f]{6}$/);
		expect(m.icons.some((i) => i.purpose === 'maskable')).toBe(true);
		for (const i of m.icons) {
			expect(i.src, 'relative to the manifest').not.toMatch(/^\/|:/);
			if (i.type === 'image/png') {
				const [w, h] = pngSize(join(dir, i.src));
				expect(i.sizes).toBe(`${w}x${h}`);
			} else {
				expect(readFileSync(join(dir, i.src), 'utf8')).toBe(mark);
			}
		}
	});
});

describe('participant app page', () => {
	it('links the icons and manifest in public/', () => {
		const html = readFileSync(join(root, 'web', 'runtime', 'index.html'), 'utf8');
		for (const f of ['favicon.svg', 'favicon-32.png', 'apple-touch-icon.png', 'site.webmanifest']) {
			expect(html).toContain(`href="/${f}"`);
		}
		expect(html).toContain('<meta name="theme-color"');
	});
});

it('the GitHub social preview is 1280×640', () => {
	expect(pngSize(join(root, 'brand', 'social-preview.png'))).toEqual([1280, 640]);
});
