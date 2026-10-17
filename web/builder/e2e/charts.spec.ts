import { expect, test, type Page } from '@playwright/test';
import { axe } from './fixtures';

// Results charts gallery (/dev/charts, task V3): every chart from the fixture cards in the
// app theme (light, dark) and the export theme; axe, visual snapshots, re-embed hygiene and
// rendering under the builder pages' CSP (script-src 'self': no eval, V-D1 interpreter).

async function open(page: Page, query = '') {
	await page.setViewportSize({ width: 1440, height: 900 });
	await page.goto(`/dev/charts${query}`);
	await expect(page.getByRole('heading', { level: 1, name: 'Results charts' })).toBeVisible();
	await expect(page.locator('main')).toHaveAttribute('data-ready', 'true', { timeout: 30_000 });
	await expect(page.locator('figure.osp-chart[data-status="ready"]')).toHaveCount(await page.locator('figure.osp-chart').count());
	await page.evaluate(() => document.fonts.ready);
}

test('every chart draws one SVG, labelled and described', async ({ page }) => {
	const errors: string[] = [];
	page.on('pageerror', (e) => errors.push(e.message));
	await open(page);
	const figures = page.locator('figure.osp-chart');
	const n = await figures.count();
	expect(n).toBeGreaterThan(40);
	await expect(page.locator('figure.osp-chart svg.marks')).toHaveCount(n);
	await expect(page.getByRole('figure', { name: 'single · Bars: How do you usually travel to work?', exact: true })).toBeVisible();
	// Vega labels its container (role graphics-document) with the spec description.
	const view = page.locator('[data-chart="matrixOrdered-likert"] .osp-chart-view');
	await expect(view).toHaveAttribute('role', 'graphics-document');
	await expect(view).toHaveAttribute('aria-label', /How much do you agree with each statement\?/);
	// No actions menu.
	await expect(page.locator('.vega-actions, details[title="Click to view actions"]')).toHaveCount(0);
	expect(errors).toEqual([]);
});

test('switching light/dark re-embeds each chart once and finalizes the old view', async ({ page }) => {
	await open(page, '?only=single-');
	const label = page.locator('[data-chart="single-bars"] svg.marks .role-axis-label text').first();
	const before = await label.getAttribute('fill');
	await page.evaluate(() => (document.documentElement.dataset.theme = 'dark'));
	await expect(label).not.toHaveAttribute('fill', before ?? '');
	await page.evaluate(() => (document.documentElement.dataset.theme = 'light'));
	await expect(label).toHaveAttribute('fill', before ?? '');
	const figures = await page.locator('figure.osp-chart').count();
	await expect(page.locator('.osp-chart-view')).toHaveCount(figures);
	await expect(page.locator('svg.marks')).toHaveCount(figures);
});

test("charts draw under the builder CSP (script-src 'self', no eval)", async ({ page }) => {
	const violations: string[] = [];
	page.on('console', (m) => {
		if (m.type() === 'error' && /unsafe-eval|EvalError/i.test(m.text())) violations.push(m.text());
	});
	page.on('pageerror', (e) => violations.push(e.message));
	await page.route('**/dev/charts*', async (route) => {
		const res = await route.fetch();
		await route.fulfill({
			response: res,
			headers: { ...res.headers(), 'content-security-policy': "script-src 'self'; object-src 'none'; base-uri 'none'" }
		});
	});
	await open(page, '?only=matrix');
	expect(violations).toEqual([]);
});

for (const [name, query, scheme] of [
	['app-light', '', 'light'],
	['app-dark', '', 'dark'],
	['export', '?theme=export', 'light']
] as const) {
	test(`gallery ${name}: axe-clean, snapshot`, async ({ page }) => {
		// 55 charts: axe and a full-page screenshot take a while on a busy machine.
		test.setTimeout(120_000);
		await page.emulateMedia({ colorScheme: scheme });
		await open(page, query);
		expect(await axe(page)).toEqual([]);
		await expect(page).toHaveScreenshot(`charts-${name}.png`, { fullPage: true });
	});
}
