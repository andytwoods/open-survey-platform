import { describe, expect, it } from 'vitest';
import { parseConfig, parseFrameConfig } from '../src/lib/host/config';
import { FRAME_SCRIPT_HASH } from '../../hooks-sandbox/src/sandbox-source.ts';
import { DEV_PAGES, devConfig, pageManifest, PAGES, PREVIEW_FRAME_CSP, renderPage, route, scriptJson } from './pages';

describe('dev host routes', () => {
	it("serves the pages at today's URLs", () => {
		expect(route('/', '', true)).toEqual({ page: 'list' });
		expect(route('/', '?mock', true)).toEqual({ page: 'dev-mock', mock: true });
		expect(route('/', '?mock', false)).toEqual({ page: 'list' });
		expect(route('/surveys/abc', '', false)).toEqual({ page: 'editor', surveyId: 'abc' });
		expect(route('/surveys/abc/flow', '', false)).toEqual({ page: 'flow', surveyId: 'abc' });
		expect(route('/surveys/abc/settings/', '', false)).toEqual({ page: 'settings', surveyId: 'abc' });
		expect(route('/surveys/a%20b/appearance', '', false)).toEqual({ page: 'appearance', surveyId: 'a b' });
		expect(route('/appearance', '', false)).toEqual({ page: 'themes', mock: undefined });
		expect(route('/preview-frame', '?frame=phone', false)).toEqual({ page: 'preview-frame' });
		expect(route('/dev/cards', '', true)).toEqual({ page: 'dev-cards' });
		expect(route('/dev/cards', '', false)).toBeNull();
		expect(route('/dev/mock', '', true)).toBeNull();
		expect(route('/login', '', true)).toBeNull();
		expect(route('/surveys/%E0%A4%A', '', true)).toBeNull();
		expect(route('/assets/list.js', '', true)).toBeNull();
	});

	it('every dev config is valid for its page', () => {
		for (const [r, survey] of [
			[route('/', '', true)!, false],
			[route('/', '?mock', true)!, false],
			[route('/surveys/s1/flow', '', true)!, true],
			[route('/appearance', '?mock', true)!, false]
		] as const) {
			const res = parseConfig(devConfig(r), 'http://127.0.0.1:4317', { requireSurveyId: survey });
			expect(res.ok, JSON.stringify(res)).toBe(true);
		}
		expect(parseFrameConfig(devConfig({ page: 'preview-frame' })).ok).toBe(true);
		const mock = devConfig({ page: 'dev-mock', mock: true });
		expect('links' in mock && mock.links.themes).toBe('/appearance?mock');
	});

	it('the dev config sends no CSRF token (Dev identity: nothing to protect with one)', () => {
		const c = devConfig({ page: 'list' });
		expect('csrf' in c).toBe(false);
	});
});

describe('host page rendering', () => {
	it('escapes the JSON config tag safely', () => {
		const json = scriptJson({ t: '</script><script>alert(1)</script>', s: ' &' });
		expect(json).not.toContain('<');
		expect(json).not.toContain(' ');
		expect(JSON.parse(json)).toEqual({ t: '</script><script>alert(1)</script>', s: ' &' });
	});

	it('writes the root, the config tag and the page files', () => {
		const html = renderPage({
			title: 'T <x>',
			config: { version: 1 },
			files: { js: '/assets/list.js', css: ['/assets/a.css'], preload: ['/assets/c.js'] }
		});
		expect(html).toContain('<div id="osp"></div>');
		expect(html).toContain('<script type="application/json" id="osp-config">{"version":1}</script>');
		expect(html).toContain('<script type="module" src="/assets/list.js"></script>');
		expect(html).toContain('<link rel="stylesheet" href="/assets/a.css" />');
		expect(html).toContain('<link rel="modulepreload" href="/assets/c.js" />');
		expect(html).toContain('<title>T &lt;x&gt;</title>');
	});

	it('leaves the inline theme script out of pages served with a strict CSP', () => {
		const page = (themeScript?: boolean) =>
			renderPage({ title: 'T', config: { version: 1 }, files: { js: '/a.js', css: [], preload: [] }, themeScript });
		expect(page()).toContain('osp-theme');
		const strict = page(false);
		expect(strict).not.toContain('osp-theme');
		expect(strict.match(/<script(?![^>]*type="(module|application\/json)")/g)).toBeNull();
	});
});

describe('preview-frame CSP (R10)', () => {
	const directives = Object.fromEntries(
		PREVIEW_FRAME_CSP.split('; ').map((d) => {
			const [k, ...v] = d.split(' ');
			return [k, v.join(' ')];
		})
	);

	it("allows the hooks sandbox exactly as the participant app's CSP does", () => {
		expect(directives['script-src']).toBe(`'self' ${FRAME_SCRIPT_HASH}`);
		expect(directives['worker-src']).toBe('blob:');
		expect(directives['frame-src']).toBe("'self'");
	});

	it('never lets the preview reach the API, and only the builder may embed it', () => {
		expect(directives['default-src']).toBe("'none'");
		expect(directives['connect-src']).toBe("'none'");
		expect(directives['frame-ancestors']).toBe("'self'");
		expect(PREVIEW_FRAME_CSP).not.toContain('unsafe-eval');
		expect(directives['script-src']).not.toContain('unsafe-inline');
	});
});

describe('manifest', () => {
	it('lists each page with its CSS (shared chunks too) and its imports', () => {
		const vite = {
			'src/pages/list.ts': { file: 'assets/list-1.js', isEntry: true, imports: ['_mount.js'], css: ['assets/list-1.css'] },
			'src/pages/editor.ts': { file: 'assets/editor-1.js', isEntry: true, imports: ['_mount.js', '_shell.js'] },
			'_mount.js': { file: 'assets/mount-1.js', css: ['assets/mount-1.css'], imports: ['_svelte.js'] },
			'_shell.js': { file: 'assets/shell-1.js', css: ['assets/shell-1.css'], imports: ['_mount.js'] },
			'_svelte.js': { file: 'assets/svelte-1.js' }
		};
		const m = pageManifest(vite, { list: 'src/pages/list.ts', editor: 'src/pages/editor.ts' });
		expect(m).toEqual({
			version: 1,
			pages: {
				list: {
					js: 'assets/list-1.js',
					css: ['assets/list-1.css', 'assets/mount-1.css'],
					preload: ['assets/mount-1.js', 'assets/svelte-1.js']
				},
				editor: {
					js: 'assets/editor-1.js',
					css: ['assets/mount-1.css', 'assets/shell-1.css'],
					preload: ['assets/mount-1.js', 'assets/svelte-1.js', 'assets/shell-1.js']
				}
			},
			csp: { 'preview-frame': PREVIEW_FRAME_CSP }
		});
		expect(() => pageManifest(vite, { flow: 'src/pages/flow.ts' })).toThrow(/flow/);
	});

	it('production pages and dev pages are disjoint', () => {
		expect(Object.keys(PAGES)).toEqual(['list', 'editor', 'flow', 'settings', 'appearance', 'themes', 'preview-frame']);
		for (const k of Object.keys(DEV_PAGES)) expect(k.startsWith('dev-')).toBe(true);
	});
});
