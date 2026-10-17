import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

// G1: every icon, the web manifest and the icons it lists load (no 404s), for the builder
// pages and for the participant app (served under /r/ by the e2e API host, as in production).

/** Fetches every icon and manifest a page links, and every icon its manifest lists. */
async function checkIcons(page: Page, request: APIRequestContext) {
	const hrefs = await page
		.locator('link[rel="icon"], link[rel="apple-touch-icon"], link[rel="manifest"]')
		.evaluateAll((links) => links.map((l) => (l as HTMLLinkElement).href));
	expect(hrefs).toHaveLength(4);
	for (const href of hrefs) {
		const res = await request.get(href);
		expect(res.status(), href).toBe(200);
		if (href.endsWith('.webmanifest')) {
			const m = (await res.json()) as { name: string; icons: { src: string }[] };
			expect(m.name).toBeTruthy();
			for (const i of m.icons) {
				const icon = new URL(i.src, href).href;
				const r = await request.get(icon);
				expect(r.status(), icon).toBe(200);
				expect(r.headers()['content-type'], icon).toMatch(/^image\//);
			}
		} else {
			expect(res.headers()['content-type'], href).toMatch(/^image\//);
		}
	}
}

test('builder pages link the favicon, touch icon and manifest, and say what they are', async ({ page, request }) => {
	const failed: string[] = [];
	page.on('response', (r) => {
		if (r.status() >= 400) failed.push(`${r.status()} ${r.url()}`);
	});
	for (const [path, title] of [
		['/', /^Open Survey Platform$/],
		['/appearance', /^Appearance · /]
	] as const) {
		await page.goto(path);
		await expect(page).toHaveTitle(title);
		await expect(page.locator('meta[name="description"]')).toHaveAttribute('content', /\w/);
		await checkIcons(page, request);
	}
	expect(failed).toEqual([]);
});

test('the participant app links its own icons and manifest under /r/', async ({ page, request }) => {
	// Any /s/{slug} serves the app's index.html; the survey need not exist for its head.
	await page.goto('/s/no-such-survey');
	await expect(page.locator('link[rel="manifest"]')).toHaveAttribute('href', '/r/site.webmanifest');
	await checkIcons(page, request);
});
