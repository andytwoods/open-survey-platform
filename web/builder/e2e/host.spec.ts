import { readFileSync } from 'node:fs';
import { expect, test, type Page, type Request } from '@playwright/test';
import { signIn, writeHeaders } from './fixtures';

// The pages as a host embeds them (planning/pages-split.md F1–F3): a host page is just
// `<div id="osp">`, the JSON config tag and the page's files from build/manifest.json. The
// tests below serve such host pages at /host/<page> (page.route), with their own link
// templates, API base, CSRF scheme and sign-in behaviour.

type Manifest = { version: 1; pages: Record<string, { js: string; css: string[]; preload: string[] }> };
const manifest = (): Manifest =>
	JSON.parse(readFileSync(new URL('../build/manifest.json', import.meta.url), 'utf8')) as Manifest;

/** The host's link templates: every page under /host/, the survey id in the query. */
const HOST_LINKS = {
	list: '/host/list',
	editor: '/host/editor?survey={id}',
	flow: '/host/flow?survey={id}',
	settings: '/host/settings?survey={id}',
	appearance: '/host/appearance?survey={id}',
	themes: '/host/themes',
	previewFrame: '/host/preview-frame'
};

type Config = Record<string, unknown>;

function hostHtml(page: string, config: Config | null): string {
	const files = manifest().pages[page];
	const tags = [
		...files.css.map((f) => `<link rel="stylesheet" href="/${f}">`),
		...files.preload.map((f) => `<link rel="modulepreload" href="/${f}">`)
	].join('\n');
	const json = config === null ? '' : JSON.stringify(config).replace(/</g, '\\u003c');
	return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Host: ${page}</title>${tags}</head>
<body><div id="osp"></div>
${config === null ? '' : `<script type="application/json" id="osp-config">${json}</script>`}
<script type="module" src="/${files.js}"></script></body></html>`;
}

/**
 * Serve /host/<page>?survey=<id> as a host would. `config(page, surveyId)` gives the
 * config; the default is the dev scheme with HOST_LINKS.
 */
async function host(page: Page, config: (name: string, surveyId: string | null) => Config | null = baseConfig) {
	await page.route(/\/host\/[a-z-]+(\?.*)?$/, (route) => {
		const url = new URL(route.request().url());
		const name = url.pathname.split('/').pop()!;
		const survey = url.searchParams.get('survey');
		return route.fulfill({ contentType: 'text/html', body: hostHtml(name, config(name, survey)) });
	});
}

function baseConfig(name: string, surveyId: string | null): Config | null {
	if (name === 'preview-frame') return null;
	return {
		version: 1,
		apiBase: '/api',
		links: HOST_LINKS,
		// Until host-signed identity (P1): osp-api's own cookie CSRF (see fixtures.ts).
		csrf: { header: 'X-CSRF-Token', cookie: '__Host-osp_csrf' },
		onUnauthenticated: { redirect: '/host-login' },
		...(surveyId ? { surveyId } : {})
	};
}

async function createSurvey(page: Page, title: string): Promise<string> {
	const res = await page.request.post('/api/surveys', { headers: await writeHeaders(page), data: { title } });
	expect(res.status(), await res.text()).toBe(201);
	return (await res.json()).id as string;
}

test('each page mounts from a config tag', async ({ page }) => {
	await signIn(page);
	const id = await createSurvey(page, `Host ${Date.now()}`);
	await host(page);

	await page.goto('/host/list');
	await expect(page.getByRole('heading', { name: 'Your surveys' })).toBeVisible();
	await page.goto(`/host/editor?survey=${id}`);
	await expect(page.getByRole('tree', { name: 'Survey outline' })).toBeVisible();
	await page.goto(`/host/flow?survey=${id}`);
	await expect(page.getByRole('heading', { name: 'Survey flow', level: 2 })).toBeVisible();
	await page.goto(`/host/settings?survey=${id}`);
	await expect(page.getByRole('heading', { name: 'Survey settings', level: 2 })).toBeVisible();
	await page.goto(`/host/appearance?survey=${id}`);
	await expect(page.getByRole('heading', { name: 'Appearance', level: 2 })).toBeVisible();
	await page.goto('/host/themes');
	await expect(page.getByRole('heading', { name: 'Appearance', level: 2 })).toBeVisible();
	// The preview frame needs no config (and refuses an API base); alone it says where it belongs.
	await page.goto('/host/preview-frame');
	await expect(page.getByText('This page shows a survey preview inside the builder.')).toBeVisible();
});

test('links follow the host templates (full page loads)', async ({ page }) => {
	await signIn(page);
	const id = await createSurvey(page, `Links ${Date.now()}`);
	await host(page);

	await page.goto('/host/list');
	const title = page.getByRole('link', { name: /^Links / }).first();
	await expect(title).toHaveAttribute('href', `/host/editor?survey=${id}`);
	await title.click();
	await expect(page).toHaveURL(new RegExp(`/host/editor\\?survey=${id}$`));
	await expect(page.getByRole('tree', { name: 'Survey outline' })).toBeVisible();

	const views = page.getByRole('navigation', { name: 'Builder views' });
	await views.getByRole('button', { name: 'Flow' }).click();
	await expect(page).toHaveURL(new RegExp(`/host/flow\\?survey=${id}$`));
	await expect(page.getByRole('heading', { name: 'Survey flow', level: 2 })).toBeVisible();
	await views.getByRole('button', { name: 'Settings' }).click();
	await expect(page).toHaveURL(new RegExp(`/host/settings\\?survey=${id}$`));
	await page.getByRole('banner').getByRole('button', { name: 'Appearance', exact: true }).click();
	await expect(page).toHaveURL(new RegExp(`/host/appearance\\?survey=${id}$`));
	await page.getByRole('button', { name: 'Back to editor' }).click();
	await expect(page).toHaveURL(new RegExp(`/host/editor\\?survey=${id}$`));

	// The preview's device frames are the host's previewFrame page.
	await page.getByRole('banner').getByRole('button', { name: 'Preview' }).click();
	await expect(page.getByTestId('preview-frame-phone')).toHaveAttribute('src', /^\/host\/preview-frame\?frame=phone&origin=/);
});

test('a 401 with a sign-in redirect: banner with ?next=, no reload', async ({ page }) => {
	let loads = 0;
	page.on('load', () => loads++);
	await page.route('**/api/**', (route) => route.fulfill({ status: 401, json: { code: 'auth', message: 'Sign in first.' } }));
	await host(page);
	await page.goto('/host/list');
	const banner = page.getByTestId('session-ended');
	await expect(banner).toBeVisible();
	await expect(banner.getByRole('link', { name: 'Sign in again' })).toHaveAttribute(
		'href',
		'/host-login?next=%2Fhost%2Flist'
	);
	await page.waitForTimeout(1000);
	expect(loads).toBe(1);
});

test('a 403 shows "no access", not the session banner', async ({ page }) => {
	await page.route('**/api/me', (route) => route.fulfill({ json: { userId: 'u1', displayName: 'Dr Example', memberships: [] } }));
	await page.route('**/api/surveys', (route) => route.fulfill({ status: 403, json: { code: 'forbidden', message: 'No.' } }));
	await host(page);
	await page.goto('/host/list');
	await expect(page.getByTestId('no-access')).toContainText("You don't have access to this lab");
	await expect(page.getByTestId('session-ended')).toHaveCount(0);
	await expect(page.getByTestId('display-name')).toHaveText('Dr Example');
});

test("writes carry the host's CSRF header, under the host's apiBase", async ({ page }) => {
	const writes: Request[] = [];
	await page.route('**/osp-api/**', (route) => {
		const r = route.request();
		const path = new URL(r.url()).pathname;
		if (r.method() === 'POST') {
			writes.push(r);
			return route.fulfill({ status: 422, json: { code: 'rejected', message: 'Not today.', diagnostics: [] } });
		}
		if (path === '/osp-api/me') return route.fulfill({ json: { userId: 'u1', memberships: [{ tenantId: 'lab-a', role: 'owner' }] } });
		if (path === '/osp-api/surveys') return route.fulfill({ json: [] });
		return route.fulfill({ status: 404, json: { code: 'not_found', message: 'No.' } });
	});
	await host(page, (name) => ({
		version: 1,
		apiBase: '/osp-api',
		links: HOST_LINKS,
		csrf: { header: 'X-Host-CSRF', token: 'host-token-123' },
		user: { displayName: 'Host-supplied name' },
		...(name === 'list' ? {} : { surveyId: 'x' })
	}));
	await page.goto('/host/list');
	await expect(page.getByTestId('display-name')).toHaveText('Host-supplied name');
	await page.getByLabel('New survey title').fill('CSRF check');
	await page.getByRole('button', { name: 'Create survey' }).click();
	await expect(page.getByText('Not today.')).toBeVisible();
	expect(writes).toHaveLength(1);
	const headers = writes[0].headers();
	expect(headers['x-host-csrf']).toBe('host-token-123');
	expect(headers['x-csrf-token']).toBeUndefined();
	// The only lab is used without asking.
	expect(writes[0].postDataJSON()).toEqual({ title: 'CSRF check', tenantId: 'lab-a' });
});

test('a bad config is rejected: nothing runs, the page says why', async ({ page }) => {
	const api: string[] = [];
	page.on('request', (r) => {
		if (/\/api\/|evil\.example/.test(r.url())) api.push(r.url());
	});
	await host(page, () => ({ version: 1, apiBase: 'https://evil.example/api', links: HOST_LINKS }));
	await page.goto('/host/list');
	await expect(page.getByRole('alert')).toContainText('apiBase: must be same-origin');
	await expect(page.getByRole('heading', { name: 'Your surveys' })).toHaveCount(0);
	expect(api).toEqual([]);

	await page.unrouteAll();
	await host(page, () => ({ version: 1, apiBase: '/api', links: { ...HOST_LINKS, editor: '/host/editor' } }));
	await page.goto('/host/list');
	await expect(page.getByRole('alert')).toContainText('links.editor: must contain {id}');
});

test('after a 401 the editor stops sending writes and keeps the edit queued', async ({ page }) => {
	await signIn(page);
	const id = await createSurvey(page, `Expired ${Date.now()}`);
	await host(page);
	await page.goto(`/host/editor?survey=${id}`);
	await expect(page.getByRole('tree', { name: 'Survey outline' })).toBeVisible();

	let sent = 0;
	await page.route('**/api/surveys/*/ops', (route) => {
		sent++;
		return route.fulfill({ status: 401, json: { code: 'auth', message: 'Sign in first.' } });
	});
	await page.getByRole('button', { name: /Add question to/ }).first().click();
	await expect(page.getByTestId('session-ended')).toBeVisible();
	await expect(page.getByRole('banner').getByRole('status').first()).toHaveText(/session ended/);
	await page.getByRole('button', { name: /Add question to/ }).first().click();
	await page.waitForTimeout(1000);
	expect(sent).toBe(1);
});
