/**
 * Start one page of the serverless demo (task DEMO2; web/builder/demo-site/).
 *
 * Each demo page is a static HTML file with `<div id="osp">` and a
 * `<meta name="osp-demo-root" content="../">` that says where the demo's root is relative to
 * it, so the build works under any base path (GitHub Pages: /open-survey-platform/demo/).
 * Boot then:
 *
 * 1. loads `data/demo-data.json` (static metadata from the Python packages,
 *    scripts/demo_data.py) next to the pages;
 * 2. builds the in-memory backend on the bundled study (or the draft carried over from the
 *    previous demo page: see `restoreDraft`) and routes the API client to it
 *    (`setLocalBackend`), so no request reaches a network;
 * 3. mounts the builder page with a config whose links point at the other demo pages.
 *
 * The draft survives moving between the demo's own pages (sessionStorage, this tab only)
 * and is dropped on a reload, so a reload always starts from the prespecified study.
 */
import { setLocalBackend } from '../api';
import type { OspPageConfig } from '../host/config';
import type { MountPage } from '../host/mount';
import { createDemoBackend, type DemoData } from './backend';
import { MemorySurveyTransport } from './memory-transport';
import { dropDraft, keepDraft, restoreDraft } from './state';
import { DEMO_SURVEY_ID, demoDraft } from './study';

export type DemoPage = 'list' | 'editor' | 'flow' | 'settings' | 'appearance' | 'themes';

const SURVEY_PAGES: readonly DemoPage[] = ['editor', 'flow', 'settings', 'appearance'];

/** The demo's root URL (with a trailing slash), from the page's `osp-demo-root` meta tag. */
export function demoRoot(doc: Document = document): URL {
	const rel = doc.querySelector<HTMLMetaElement>('meta[name="osp-demo-root"]')?.content || './';
	return new URL(rel, doc.baseURI);
}

/** The page config for one demo page: links to the other demo pages under `root`. */
export function demoConfig(page: DemoPage, root: URL): OspPageConfig {
	const r = root.href;
	const config: OspPageConfig = {
		version: 1,
		// Never fetched: the local backend answers every call.
		apiBase: `${r}api`,
		links: {
			list: `${r}list/`,
			editor: `${r}?survey={id}`,
			flow: `${r}flow/?survey={id}`,
			settings: `${r}settings/?survey={id}`,
			appearance: `${r}appearance/?survey={id}`,
			themes: `${r}themes/`,
			previewFrame: `${r}preview-frame/`
		},
		user: { displayName: 'Demo researcher' }
	};
	if (SURVEY_PAGES.includes(page)) config.surveyId = DEMO_SURVEY_ID;
	return config;
}

/** Drop the carried-over draft and open the editor on the prespecified study again. */
export function startOver(root: URL) {
	dropDraft();
	location.assign(root.href);
}

async function loadData(root: URL): Promise<DemoData> {
	const res = await fetch(new URL('data/demo-data.json', root));
	if (!res.ok) throw new Error(`demo data: ${res.status}`);
	return (await res.json()) as DemoData;
}

function banner(root: URL): HTMLElement {
	const aside = document.createElement('aside');
	aside.className = 'osp-demo-banner';
	aside.setAttribute('aria-label', 'Demo');
	aside.dataset.testid = 'demo-banner';
	const p = document.createElement('p');
	const b = document.createElement('strong');
	b.textContent = 'Demo:';
	p.append(b, ' runs entirely in your browser; changes vanish when you reload.');
	const nav = document.createElement('p');
	nav.className = 'osp-demo-links';
	const take = document.createElement('a');
	take.href = new URL('take/', root).href;
	take.textContent = 'Take the study';
	const again = document.createElement('a');
	again.href = root.href;
	again.textContent = 'Start over';
	again.addEventListener('click', (e) => {
		e.preventDefault();
		startOver(root);
	});
	const docs = document.createElement('a');
	docs.href = new URL('../', root).href;
	docs.textContent = 'Docs';
	nav.append(take, again, docs);
	aside.append(p, nav);
	return aside;
}

/** The banner's height, so the full-height builder shell fits under it. */
function trackBanner(el: HTMLElement) {
	const set = () => document.documentElement.style.setProperty('--osp-demo-banner', `${el.offsetHeight}px`);
	set();
	if (typeof ResizeObserver !== 'undefined') new ResizeObserver(set).observe(el);
}

export async function bootDemo(page: DemoPage, mount: MountPage): Promise<void> {
	const el = document.getElementById('osp');
	if (!el) return;
	const root = demoRoot();
	const top = banner(root);
	el.before(top);
	trackBanner(top);
	let data: DemoData;
	try {
		data = await loadData(root);
	} catch (e) {
		console.error(e);
		el.textContent = 'The demo could not load its data. Reload the page to try again.';
		return;
	}
	const transport = new MemorySurveyTransport(restoreDraft() ?? demoDraft(), { onChange: keepDraft });
	setLocalBackend(createDemoBackend({ data, transport }));
	mount(el, demoConfig(page, root));
}
