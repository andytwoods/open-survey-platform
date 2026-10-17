/**
 * Vite plugin: the multi-page build's manifest, and the reference host for `vite dev` and
 * `vite preview` (pages served at today's URLs with the dev config). See ./pages.ts.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { join, resolve } from 'node:path';
import type { Connect, Plugin, ResolvedConfig } from 'vite';
import { DESCRIPTIONS, devConfig, pageManifest, renderPage, route, TITLES, type PageManifest, type PageName } from './pages.ts';

export const MANIFEST = 'manifest.json';

function send(res: ServerResponse, html: string, csp?: string) {
	res.statusCode = 200;
	if (csp) res.setHeader('Content-Security-Policy', csp);
	res.setHeader('Content-Type', 'text/html; charset=utf-8');
	res.setHeader('Cache-Control', 'no-store');
	res.end(html);
}

export function ospPages(opts: { entries: Record<string, string>; devPages: boolean }): Plugin {
	let config: ResolvedConfig;
	const outDir = () => resolve(config.root, config.build.outDir);

	const preview = (): Connect.NextHandleFunction => {
		let manifest: PageManifest | null = null;
		return (req: IncomingMessage, res: ServerResponse, next) => {
			const url = new URL(req.url ?? '/', 'http://host.invalid');
			const r = route(url.pathname, url.search, opts.devPages);
			if (!r || (req.method !== 'GET' && req.method !== 'HEAD')) return next();
			manifest ??= JSON.parse(readFileSync(join(outDir(), MANIFEST), 'utf8')) as PageManifest;
			const files = manifest.pages[r.page];
			if (!files) return next();
			const abs = (f: string) => `/${f}`;
			// The built pages get the CSP a host must send (manifest `csp`, docs/hosting.md §5).
			// The dev server does not: Vite injects inline scripts and a websocket there.
			const csp = manifest.csp?.[r.page];
			send(
				res,
				renderPage({
					title: TITLES[r.page],
					description: DESCRIPTIONS[r.page],
					config: devConfig(r),
					files: { js: abs(files.js), css: files.css.map(abs), preload: files.preload.map(abs) },
					themeScript: !csp
				}),
				csp
			);
		};
	};

	return {
		name: 'osp-pages',
		configResolved(c) {
			config = c;
		},
		configureServer(server) {
			server.middlewares.use(async (req, res, next) => {
				const url = new URL(req.url ?? '/', 'http://host.invalid');
				const r = route(url.pathname, url.search, true);
				if (!r || req.method !== 'GET') return next();
				const entry = opts.entries[r.page as PageName];
				if (!entry) return next();
				try {
					const html = renderPage({
						title: TITLES[r.page],
						description: DESCRIPTIONS[r.page],
						config: devConfig(r),
						files: { js: `/${entry}`, css: [], preload: [] }
					});
					send(res, await server.transformIndexHtml(req.url ?? '/', html));
				} catch (e) {
					next(e);
				}
			});
		},
		configurePreviewServer(server) {
			server.middlewares.use(preview());
		},
		// Vite's own manifest (.vite/manifest.json) → ours: page → js, css, preloads.
		writeBundle() {
			const vite = JSON.parse(readFileSync(join(outDir(), '.vite', 'manifest.json'), 'utf8'));
			const m = pageManifest(vite, opts.entries);
			writeFileSync(join(outDir(), MANIFEST), JSON.stringify(m, null, '\t') + '\n');
		}
	};
}
