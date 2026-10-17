import { readFileSync } from 'node:fs';
import { expect, test, type Download, type Page } from '@playwright/test';
import { pngInfo } from '../src/lib/results/export/png';
import { readZip } from '../src/lib/results/export/zip';
import { axe, signIn, writeHeaders } from './fixtures';

// Results presentation (task V6), end to end against a real osp-api on SQLite: the page's
// own theme (a lab library theme recolours the charts, is kept in a saved layout and reaches
// the exports), presentation mode (only the cards; Escape or the floating button leaves it;
// `?present=1` and `?layout=` in the URL) and "Export all" as an SVG-only or PNG-only ZIP.
// The survey is V1's hand-checked fixture with five fake responses.

const card = (page: Page, name: string) => page.getByRole('article', { name });
const themePicker = (page: Page) => page.getByLabel('Theme', { exact: true });

/** Present → the Present dialog (task LV4) → Start presenting with its defaults. */
async function startPresenting(page: Page) {
	await page.getByRole('button', { name: 'Present' }).click();
	const dialog = page.getByRole('dialog', { name: 'Present results' });
	await expect(dialog).toBeVisible();
	await dialog.getByRole('button', { name: 'Start presenting' }).click();
	await expect(dialog).toBeHidden();
}

/** The Warm preset's colours, as a lab library theme document (osp-theme/0.1). */
const WARM = {
	themeVersion: 'osp-theme/0.1',
	preset: 'warm',
	colours: {
		light: { accent: '#a3431a', background: '#fdf8f1', surface: '#f5ecdf', text: '#2b2118', muted: '#65544a', error: '#a8201a', focus: '#a3431a' },
		dark: { accent: '#f2a571', background: '#1c1713', surface: '#262019', text: '#f3eadf', muted: '#c4b4a2', error: '#ff8f84', focus: '#f2a571' }
	},
	font: 'system-serif',
	mode: 'light'
};

async function seededSurvey(page: Page): Promise<string> {
	await signIn(page);
	const headers = await writeHeaders(page);
	const survey = await (await page.request.get('/api/e2e/results-fixture')).json();
	const created = await page.request.post('/api/surveys', { headers, data: { title: `Presentation e2e ${Date.now()}`, survey } });
	expect(created.status()).toBe(201);
	const id = (await created.json()).id as string;
	const seeded = await page.request.post(`/api/e2e/results-seed/${id}`, { headers });
	expect(await seeded.json()).toEqual({ version: 1, responses: 5 });
	return id;
}

async function labTheme(page: Page, name: string): Promise<string> {
	const headers = await writeHeaders(page);
	const r = await page.request.post('/api/themes', { headers, data: { name, theme: WARM } });
	expect(r.status(), await r.text()).toBe(201);
	return (await r.json()).id as string;
}

async function openResults(page: Page, id: string, query = '') {
	await page.goto(`/surveys/${id}/results${query}`);
	await expect(page.getByRole('list', { name: 'Questions' })).toBeVisible();
	await expect(page.locator('.result-card figure.osp-chart[data-status="ready"]').first()).toBeVisible();
}

const bytes = async (d: Download) => new Uint8Array(readFileSync((await d.path())!));

async function exportAllZip(page: Page, bundle: RegExp): Promise<{ name: string; data: Uint8Array }> {
	await page.getByRole('button', { name: 'Export all' }).click();
	const dialog = page.getByRole('dialog', { name: 'Export all figures' });
	await expect(dialog).toBeVisible();
	await dialog.getByRole('radio', { name: bundle }).check();
	const got = new Promise<Download>((resolve) => page.once('download', resolve));
	const audit = page.waitForResponse((r) => r.url().endsWith('/results/export') && r.request().method() === 'POST');
	await dialog.getByRole('button', { name: 'Download ZIP' }).click();
	expect((await audit).status()).toBe(200);
	const d = await got;
	await dialog.getByRole('button', { name: 'Done' }).click();
	await expect(dialog).toBeHidden();
	return { name: d.suggestedFilename(), data: await bytes(d) };
}

test('a lab theme recolours the charts, is saved in the layout, and colours the exports', async ({ page }) => {
	test.setTimeout(120_000);
	const id = await seededSurvey(page);
	const themeId = await labTheme(page, `Warm e2e ${Date.now()}`);
	await openResults(page, id);

	const fruit = card(page, 'Fruit?');
	const bar = fruit.locator('[data-chart="bars"] .mark-rect path').first();
	await expect(bar).toHaveAttribute('fill', /^(#2456c7|#[0-9a-f]{6})$/); // the app's accent
	const appFill = await bar.getAttribute('fill');
	expect(appFill).not.toBe('#a3431a');
	await expect(page.getByTestId('theme-note')).toContainText('App colours.');

	// Pick the lab theme: the cards take its tokens and the bars its accent.
	await themePicker(page).selectOption({ value: `library:${themeId}` });
	await expect(page.getByTestId('theme-note')).toContainText(/Lab theme “Warm e2e \d+”, light colours\./);
	await expect(page.getByRole('list', { name: 'Questions' })).toHaveAttribute('data-theme-mode', 'light');
	await expect(fruit.locator('[data-chart="bars"] .mark-rect path').first()).toHaveAttribute('fill', '#a3431a');
	await expect(page.getByTestId('theme-contrast')).toHaveCount(0);
	await expect(page.getByTestId('layout-unsaved')).toBeVisible();

	// Saved in a layout; a reload restores it.
	await page.getByRole('button', { name: 'Save as…' }).click();
	const dialog = page.getByRole('dialog', { name: 'Save layout as' });
	await dialog.getByLabel('Name').fill('Warm paper');
	await dialog.getByLabel('Open this layout by default').check();
	await dialog.getByRole('button', { name: 'Save' }).click();
	await expect(page.getByTestId('layout-status')).toHaveText('Saved as “Warm paper”, the default layout.');
	await page.reload();
	await expect(page.getByRole('list', { name: 'Questions' })).toBeVisible();
	await expect(themePicker(page)).toHaveValue(`library:${themeId}`);
	await expect(card(page, 'Fruit?').locator('[data-chart="bars"] .mark-rect path').first()).toHaveAttribute('fill', '#a3431a');
	await expect(page.getByTestId('layout-unsaved')).toBeHidden();

	// The per-card export preview and the whole-page ZIPs use the theme's colours.
	await fruit.getByRole('button', { name: 'Export Fruit?' }).click();
	await page.getByRole('menuitem', { name: 'SVG image…' }).click();
	const exportDialog = page.getByRole('dialog', { name: 'Export: Fruit?' });
	await expect(exportDialog.getByTestId('export-theme')).toContainText('light colours');
	await expect(exportDialog.locator('figure.osp-chart[data-status="ready"] .mark-rect path').first()).toHaveAttribute('fill', '#a3431a');
	await exportDialog.getByRole('button', { name: 'Done' }).click();
	await expect(exportDialog).toBeHidden();

	const svgZip = await exportAllZip(page, /SVG only/);
	expect(svgZip.name).toMatch(/^results-[0-9a-f-]{8}-\d{4}-\d{2}-\d{2}-svg\.zip$/);
	const svgEntries = readZip(svgZip.data);
	const svgNames = svgEntries.map((e) => e.name);
	expect(svgNames.filter((n) => n.endsWith('.svg'))).toHaveLength(10);
	expect(svgNames).toHaveLength(11);
	expect(svgNames.at(-1)).toBe('manifest.json');
	const fruitSvg = new TextDecoder().decode(svgEntries.find((e) => e.name === 'fruit.svg')!.data);
	expect(fruitSvg).toContain('#a3431a');
	expect(fruitSvg).toContain('width="85mm"');
	const manifest = JSON.parse(new TextDecoder().decode(svgEntries.find((e) => e.name === 'manifest.json')!.data));
	expect(manifest.theme).toMatch(/^Lab theme “Warm e2e \d+” \(light colours; text >= 8 pt at final size\)$/);
	expect(manifest.figures.map((f: { files: string[] }) => f.files)).toEqual(Array.from({ length: 10 }, () => [expect.stringMatching(/\.svg$/)]));

	const pngZip = await exportAllZip(page, /PNG only/);
	expect(pngZip.name).toMatch(/-png\.zip$/);
	const pngEntries = readZip(pngZip.data);
	expect(pngEntries.map((e) => e.name).filter((n) => n.endsWith('.png'))).toHaveLength(10);
	expect(pngEntries).toHaveLength(11);
	expect(pngInfo(pngEntries.find((e) => e.name === 'fruit.png')!.data)).toMatchObject({ width: 1004, dpi: 300 });

	// Delete the lab theme: the layout falls back to the app colours and says so.
	const headers = await writeHeaders(page);
	expect((await page.request.delete(`/api/themes/${themeId}`, { headers })).status()).toBe(204);
	await page.reload();
	await expect(page.getByRole('list', { name: 'Questions' })).toBeVisible();
	await expect(page.getByTestId('theme-notice')).toContainText('no longer in the lab library');
	await expect(card(page, 'Fruit?').locator('[data-chart="bars"] .mark-rect path').first()).toHaveAttribute('fill', appFill!);
});

test('presentation mode: only the cards; Escape and the floating button leave; the URL carries it', async ({ page }) => {
	const id = await seededSurvey(page);
	await openResults(page, id);
	await expect(page.locator('header.topbar')).toBeVisible();

	await startPresenting(page);
	const exit = page.getByTestId('exit-presentation');
	await expect(exit).toBeVisible();
	await expect(exit).toBeFocused();
	expect(new URL(page.url()).searchParams.get('present')).toBe('1');
	await expect(page.locator('header.topbar')).toHaveCount(0);
	await expect(page.getByTestId('layout-bar')).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Show results' })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Export all' })).toHaveCount(0);
	await expect(page.getByRole('list', { name: 'Questions' }).getByRole('article')).toHaveCount(10);
	const fruit = card(page, 'Fruit?');
	await expect(fruit.getByRole('combobox', { name: 'Chart' })).toHaveCount(0);
	await expect(fruit.getByRole('button', { name: 'Export Fruit?' })).toHaveCount(0);
	await expect(fruit.locator('[data-chart="bars"] svg.marks')).toBeVisible();
	// On screen, cells below 5 are hidden by default (LV4, LV-D5): Apple (2) and Banana (1).
	await expect(fruit.getByTestId('card-caption')).toHaveText(
		'Fruit? (fruit). Version 1; Complete responses only; Denominator: answered. n = 3 responses. Counts below 5 hidden (shown as "n<5"; 2 cells).'
	);
	await expect(fruit.locator('[data-chart="bars"] svg.marks text', { hasText: 'n<5' }).first()).toBeVisible();
	await expect(page.getByTestId('present-footer')).toHaveText(/^5 responses · updated \d\d:\d\d · counts below 5 hidden$/);
	expect(await axe(page)).toEqual([]);

	await page.keyboard.press('Escape');
	await expect(page.locator('header.topbar')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Present' })).toBeFocused();
	expect(new URL(page.url()).searchParams.has('present')).toBe(false);
	await expect(fruit.getByRole('combobox', { name: 'Chart' })).toBeVisible();

	// The floating button leaves too.
	await startPresenting(page);
	await expect(exit).toBeVisible();
	await exit.click();
	await expect(page.locator('header.topbar')).toBeVisible();
	await expect(page.getByTestId('exit-presentation')).toHaveCount(0);
});

test('a shared link: ?present=1 opens the cards only, ?layout= the saved layout; 320 px and axe, light and dark', async ({ page }) => {
	const id = await seededSurvey(page);
	const headers = await writeHeaders(page);
	const r = await page.request.post(`/api/surveys/${id}/results/layouts`, {
		headers,
		data: { name: 'Talk', settings: { theme: { kind: 'preset', id: 'dark' }, cards: [{ question: 'why', hidden: true }, { question: 'fruit', chart: 'donut' }] } }
	});
	expect(r.status()).toBe(201);
	const layoutId = (await r.json()).id as string;

	for (const scheme of ['light', 'dark'] as const) {
		await page.emulateMedia({ colorScheme: scheme });
		await page.setViewportSize({ width: 320, height: 800 });
		await openResults(page, id, `?present=1&layout=${layoutId}`);
		await expect(page.getByTestId('exit-presentation')).toBeVisible();
		await expect(page.locator('header.topbar')).toHaveCount(0);
		await expect(page.getByRole('list', { name: 'Questions' }).getByRole('article')).toHaveCount(9); // Why? is hidden
		await expect(card(page, 'Fruit?').locator('[data-chart="donut"] svg.marks')).toBeVisible();
		// A link alone never shows exact counts (LV4, lead decision 1).
		await expect(page.getByTestId('present-footer')).toHaveText(/counts below 5 hidden$/);
		// The dark preset is dark-only: the page shows it dark whatever the device prefers.
		await expect(page.locator('.results[data-presenting]')).toHaveAttribute('style', /color-scheme: dark/);
		const doc = await page.evaluate(() => document.documentElement.scrollWidth);
		expect(doc, 'no horizontal page scroll').toBeLessThanOrEqual(320);
		expect(await axe(page)).toEqual([]);
	}

	// Leaving keeps the layout in the URL and shows the layout bar with it open.
	await page.setViewportSize({ width: 1280, height: 800 });
	await page.getByTestId('exit-presentation').click();
	await expect(page.getByLabel('Layout', { exact: true }).locator('option:checked')).toHaveText('Talk');
	expect(new URL(page.url()).searchParams.get('layout')).toBe(layoutId);
	expect(new URL(page.url()).searchParams.has('present')).toBe(false);
	await expect(page.getByLabel('Theme', { exact: true })).toHaveValue('preset:dark');
	expect(await axe(page)).toEqual([]);
});
