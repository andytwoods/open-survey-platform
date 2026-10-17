/**
 * The builder's pages, and the reference host used by the Vite dev and preview servers
 * (`make dev`, `make web-e2e`). Node-side only: never imported by the pages.
 *
 * A real host (planning/pages-split.md F1) does what `renderPage` does: one HTML page per
 * URL with `<div id="osp">`, the JSON config tag and the page's files from manifest.json.
 */
import { createHash } from 'node:crypto';
import { FRAME_SCRIPT } from '../../hooks-sandbox/src/frame-script.ts';
import { DEFAULT_LINKS, type OspPageConfig } from '../src/lib/host/config.ts';

/** Production pages: name → entry module. One JS entry (plus CSS) per page. */
export const PAGES = {
	list: 'src/pages/list.ts',
	editor: 'src/pages/editor.ts',
	flow: 'src/pages/flow.ts',
	settings: 'src/pages/settings.ts',
	appearance: 'src/pages/appearance.ts',
	themes: 'src/pages/themes.ts',
	'preview-frame': 'src/pages/preview-frame.ts'
} as const;

/** Dev-only pages (galleries and the mock shell): not in the production build. */
export const DEV_PAGES = {
	'dev-mock': 'src/pages/dev/mock.ts',
	'dev-cards': 'src/pages/dev/cards.ts',
	'dev-choices': 'src/pages/dev/choices.ts',
	'dev-components': 'src/pages/dev/components.ts',
	'dev-conditions': 'src/pages/dev/conditions.ts',
	'dev-properties': 'src/pages/dev/properties.ts',
	'dev-themes': 'src/pages/dev/themes.ts',
	'dev-widgets': 'src/pages/dev/widgets.ts'
} as const;

export type PageName = keyof typeof PAGES | keyof typeof DEV_PAGES;

const APP = 'Open Survey Platform';
export const TITLES: Record<PageName, string> = {
	list: APP,
	editor: `Editor · ${APP}`,
	flow: `Flow · ${APP}`,
	settings: `Settings · ${APP}`,
	appearance: `Appearance · ${APP}`,
	themes: `Appearance · ${APP}`,
	'preview-frame': `Preview · ${APP}`,
	'dev-mock': APP,
	'dev-cards': `Question cards · ${APP}`,
	'dev-choices': `Choice list editor · ${APP}`,
	'dev-components': `Components · ${APP}`,
	'dev-conditions': `Condition builder · ${APP}`,
	'dev-properties': `Property panel · ${APP}`,
	'dev-themes': `Themes · ${APP}`,
	'dev-widgets': `Widgets · ${APP}`
};

export interface Route {
	page: PageName;
	surveyId?: string;
	/** `?mock`: the dev shell over static data; its links stay in mock mode. */
	mock?: boolean;
}

const SURVEY_VIEWS: Record<string, PageName> = { '': 'editor', flow: 'flow', settings: 'settings', appearance: 'appearance' };

/** Today's URLs → page (the dev host's routing). Null: not a page. */
export function route(pathname: string, search: string, devPages: boolean): Route | null {
	const mock = new URLSearchParams(search).has('mock');
	const path = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
	if (path === '/') return mock && devPages ? { page: 'dev-mock', mock: true } : { page: 'list' };
	if (path === '/appearance') return { page: 'themes', mock: mock || undefined };
	if (path === '/preview-frame') return { page: 'preview-frame' };
	const s = /^\/surveys\/([^/]+)(?:\/(flow|settings|appearance))?$/.exec(path);
	if (s) {
		let id: string;
		try {
			id = decodeURIComponent(s[1]);
		} catch {
			return null;
		}
		return { page: SURVEY_VIEWS[s[2] ?? ''], surveyId: id };
	}
	const d = /^\/dev\/([a-z]+)$/.exec(path);
	if (d && devPages) {
		const name = `dev-${d[1]}` as PageName;
		if (name in DEV_PAGES && name !== 'dev-mock') return { page: name };
	}
	return null;
}

/**
 * The dev host's config. osp-api runs with the Dev identity (`OSP_IDENTITY=dev`): every
 * request is the dev researcher, so there is no sign-in and no CSRF token to send (the
 * API's Origin check and JSON-only bodies still apply).
 */
export function devConfig(r: Route): OspPageConfig | { version: 1 } {
	if (r.page === 'preview-frame') return { version: 1 };
	const links = { ...DEFAULT_LINKS };
	if (r.mock) {
		links.list = '/?mock';
		links.themes = '/appearance?mock';
	}
	const config: OspPageConfig = {
		version: 1,
		apiBase: '/api',
		links,
		onUnauthenticated: 'reload'
	};
	if (r.surveyId !== undefined) config.surveyId = r.surveyId;
	return config;
}

/** JSON for inside a `<script>` tag: `<`, `>`, `&` and line separators escaped (D7). */
export function scriptJson(value: unknown): string {
	return JSON.stringify(value)
		.replace(/</g, '\\u003c')
		.replace(/>/g, '\\u003e')
		.replace(/&/g, '\\u0026')
		.replaceAll(String.fromCharCode(0x2028), '\\u2028')
		.replaceAll(String.fromCharCode(0x2029), '\\u2029');
}

const escapeHtml = (s: string) =>
	s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

export interface PageFiles {
	js: string;
	css: string[];
	preload: string[];
}

/** One host page (what a host's view renders). URLs in `files` are used as given. */
export function renderPage(opts: { title: string; config: unknown; files: PageFiles; themeScript?: boolean }): string {
	const { title, config, files } = opts;
	// The inline theme script is the dev host's shortcut (not for real hosts, §5); pages
	// served with a strict CSP leave it out.
	const theme =
		opts.themeScript === false
			? ''
			: `
		<script>
			// Apply a saved theme before first paint (see ui-components/src/theme.svelte.ts).
			try {
				var t = localStorage.getItem('osp-theme');
				if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t;
			} catch (e) {}
		</script>`;
	const css = files.css.map((h) => `\t\t<link rel="stylesheet" href="${escapeHtml(h)}" />`).join('\n');
	const pre = files.preload.map((h) => `\t\t<link rel="modulepreload" href="${escapeHtml(h)}" />`).join('\n');
	return `<!doctype html>
<html lang="en">
	<head>
		<meta charset="utf-8" />
		<meta name="viewport" content="width=device-width, initial-scale=1" />
		<meta name="text-scale" content="scale" />
		<title>${escapeHtml(title)}</title>
		<link rel="icon" href="/favicon.svg" />${theme}
${css}
${pre}
	</head>
	<body>
		<div id="osp"></div>
		<script type="application/json" id="osp-config">${scriptJson(config)}</script>
		<script type="module" src="${escapeHtml(files.js)}"></script>
	</body>
</html>
`;
}

// -- CSP --------------------------------------------------------------------------------

/** The researcher-hooks sandbox frame's only script, by hash (runtime-design §7a). */
export const HOOKS_FRAME_SCRIPT_HASH = `'sha256-${createHash('sha256').update(FRAME_SCRIPT).digest('base64')}'`;

/**
 * The `preview-frame` page's CSP (task R10, docs/hosting.md §5). The page runs the
 * participant app, and with it the survey's researcher hooks in their sandbox: a `srcdoc`
 * iframe (it inherits this policy, then narrows itself to `default-src 'none'`) that starts
 * a `blob:` worker. So, as in the participant app's own CSP (`web/runtime/vite.config.ts`),
 * it allows the frame script by hash and `blob:` workers. `connect-src 'none'`: the
 * preview never calls the API (pages-split D10); everything it runs on comes by
 * `postMessage`. `frame-ancestors 'self'`: only the builder on this origin may embed it.
 */
export const PREVIEW_FRAME_CSP = [
	"default-src 'none'",
	`script-src 'self' ${HOOKS_FRAME_SCRIPT_HASH}`,
	'worker-src blob:',
	"style-src 'self' 'unsafe-inline'",
	"img-src 'self' data: blob:",
	"font-src 'self'",
	"connect-src 'none'",
	"frame-src 'self'",
	"object-src 'none'",
	"base-uri 'none'",
	"form-action 'none'",
	"frame-ancestors 'self'"
].join('; ');

// -- manifest -------------------------------------------------------------------------

/** One entry of Vite's own `.vite/manifest.json`. */
export interface ViteManifestChunk {
	file: string;
	name?: string;
	src?: string;
	isEntry?: boolean;
	imports?: string[];
	css?: string[];
}

export interface PageManifest {
	version: 1;
	/** Page name → its entry module, its CSS (shared chunks' too) and chunks to preload. */
	pages: Record<string, PageFiles>;
	/** Page name → the Content-Security-Policy header it needs beyond a host's default. */
	csp: Record<string, string>;
}

/** Our `manifest.json` from Vite's: every page's JS, all the CSS it needs, its imports. */
export function pageManifest(vite: Record<string, ViteManifestChunk>, entries: Record<string, string>): PageManifest {
	const pages: Record<string, PageFiles> = {};
	for (const [name, src] of Object.entries(entries)) {
		const chunk = vite[src];
		if (!chunk?.isEntry) throw new Error(`manifest: no entry chunk for page "${name}" (${src})`);
		const css: string[] = [];
		const preload: string[] = [];
		const seen = new Set<string>();
		const walk = (key: string, top: boolean) => {
			if (seen.has(key)) return;
			seen.add(key);
			const c = vite[key];
			if (!c) return;
			if (!top) preload.push(c.file);
			for (const f of c.css ?? []) if (!css.includes(f)) css.push(f);
			for (const i of c.imports ?? []) walk(i, false);
		};
		walk(src, true);
		pages[name] = { js: chunk.file, css, preload };
	}
	return { version: 1, pages, csp: { 'preview-frame': PREVIEW_FRAME_CSP } };
}
