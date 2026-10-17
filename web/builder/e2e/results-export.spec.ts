import { readFileSync } from 'node:fs';
import { expect, test, type Download, type Locator, type Page } from '@playwright/test';
import { pngInfo } from '../src/lib/results/export/png';
import { readZip } from '../src/lib/results/export/zip';
import { axe, signIn, writeHeaders } from './fixtures';

// Results charts and figure export (task V4), end to end against a real osp-api: V1's
// fixture survey with five fake responses. Every card draws a Vega-Lite SVG; chart type
// and split layout re-render; the Export menu's dialog downloads SVG, PNG (real pixel size
// and DPI metadata), CSV, the Vega-Lite spec with its manifest, and "Export all" a ZIP.
// Each export is audited by POST .../results/export first.

const card = (page: Page, name: string) => page.getByRole('article', { name });

async function seededSurvey(page: Page): Promise<string> {
	await signIn(page);
	const headers = await writeHeaders(page);
	const survey = await (await page.request.get('/api/e2e/results-fixture')).json();
	const created = await page.request.post('/api/surveys', { headers, data: { title: `Export e2e ${Date.now()}`, survey } });
	expect(created.status()).toBe(201);
	const id = (await created.json()).id as string;
	const seeded = await page.request.post(`/api/e2e/results-seed/${id}`, { headers });
	expect(await seeded.json()).toEqual({ version: 1, responses: 5 });
	return id;
}

async function openResults(page: Page, id: string) {
	await page.goto(`/surveys/${id}/results`);
	await expect(page.getByRole('list', { name: 'Questions' })).toBeVisible();
	await expect(page.getByTestId('results-count')).toHaveText('5 responses');
}

/** Open a card's Export menu and pick a format; the dialog opens. */
async function exportDialog(page: Page, cardName: string, item: string): Promise<Locator> {
	await card(page, cardName).getByRole('button', { name: `Export ${cardName}` }).click();
	await page.getByRole('menuitem', { name: item }).click();
	const dialog = page.getByRole('dialog', { name: `Export: ${cardName}` });
	await expect(dialog).toBeVisible();
	return dialog;
}

async function downloadFrom(page: Page, dialog: Locator, count = 1): Promise<Download[]> {
	const downloads: Download[] = [];
	const all = new Promise<void>((resolve) => {
		page.on('download', (d) => {
			downloads.push(d);
			if (downloads.length === count) resolve();
		});
	});
	const audit = page.waitForResponse((r) => r.url().endsWith('/results/export') && r.request().method() === 'POST');
	await dialog.getByRole('button', { name: 'Download', exact: true }).click();
	expect((await audit).status()).toBe(200);
	await all;
	return downloads;
}

const bytes = async (d: Download) => new Uint8Array(readFileSync((await d.path())!));
const text = async (d: Download) => new TextDecoder().decode(await bytes(d));

test('every card draws a Vega-Lite SVG; chart type and split layout re-render', async ({ page }) => {
	const errors: string[] = [];
	page.on('pageerror', (e) => errors.push(e.message));
	const id = await seededSurvey(page);
	await openResults(page, id);
	const cards = page.getByRole('list', { name: 'Questions' }).getByRole('article');
	await expect(cards).toHaveCount(10);
	await expect(page.locator('.result-card figure.osp-chart[data-status="ready"] svg.marks')).toHaveCount(10);

	const fruit = card(page, 'Fruit?');
	await expect(fruit.getByRole('figure', { name: 'Fruit?' })).toBeVisible();
	await expect(fruit.locator('[data-chart="bars"] .mark-rect path')).toHaveCount(3);
	await fruit.getByRole('combobox', { name: 'Chart' }).selectOption('donut');
	await expect(fruit.locator('[data-chart="donut"] .mark-arc path')).toHaveCount(2); // Cherry has no slice
	await expect(fruit.locator('.osp-chart-view')).toHaveCount(1); // the old view is gone

	// Grid: ordered columns, diverging bars by default.
	await expect(card(page, 'Grid').locator('[data-chart="likert"] svg.marks')).toBeVisible();

	// Split by condition: grouped, then 100 % stacked bars.
	await page.getByLabel('Split by', { exact: true }).selectOption({ label: 'arm' });
	await page.getByRole('button', { name: 'Show results' }).click();
	await expect(page.getByTestId('results-count')).toHaveText(/a: 2, b: 2, No condition: 1/);
	await fruit.getByRole('combobox', { name: 'Chart' }).selectOption('bars');
	const groups = fruit.getByRole('combobox', { name: 'Groups' });
	await expect(groups).toHaveValue('grouped');
	await expect(fruit.locator('[data-layout="grouped"] svg.marks')).toContainText('b: 100%');
	await groups.selectOption('stacked');
	await expect(fruit.locator('[data-chart="bars"][data-layout="stacked"] svg.marks')).toBeVisible();
	await expect(fruit.locator('[data-layout="stacked"] .mark-rect path')).not.toHaveCount(0);
	await groups.selectOption('multiples');
	await expect(fruit.locator('[data-layout="multiples"] svg.marks')).toContainText('No condition (n = 0)');
	expect(errors).toEqual([]);
});

for (const scheme of ['light', 'dark'] as const) {
	test(`charts at 320 px and in ${scheme}: no sideways scroll, axe-clean, export dialog axe-clean`, async ({ page }) => {
		await page.emulateMedia({ colorScheme: scheme });
		await page.setViewportSize({ width: 320, height: 800 });
		const id = await seededSurvey(page);
		await openResults(page, id);
		await expect(page.locator('.result-card figure.osp-chart[data-status="ready"]')).toHaveCount(10);
		const doc = await page.evaluate(() => document.documentElement.scrollWidth);
		expect(doc).toBeLessThanOrEqual(320);
		expect(await axe(page)).toEqual([]);
		const dialog = await exportDialog(page, 'Fruit?', 'PNG image…');
		await expect(dialog.locator('figure.osp-chart[data-status="ready"] svg.marks')).toBeVisible();
		expect(await axe(page)).toEqual([]);
		await dialog.getByRole('button', { name: 'Done' }).click();
		await expect(dialog).toBeHidden();
	});
}

test('PNG: real pixel size and DPI metadata at 85 mm and 180 mm', async ({ page }) => {
	const id = await seededSurvey(page);
	await openResults(page, id);
	const dialog = await exportDialog(page, 'Fruit?', 'PNG image…');
	await expect(dialog.getByTestId('png-size')).toContainText('85 mm at 300 DPI = 1004 ×');
	await expect(dialog.locator('figure.osp-chart[data-status="ready"] svg.marks')).toContainText('Fruit? (fruit).');
	const [png] = await downloadFrom(page, dialog);
	expect(png.suggestedFilename()).toBe('fruit.png');
	const info = pngInfo(await bytes(png));
	expect(info.width).toBe(1004);
	expect(info.dpi).toBe(300);
	expect(info.chunks.slice(0, 2)).toEqual(['IHDR', 'pHYs']);
	const shown = (await dialog.getByTestId('png-size').textContent()) ?? '';
	expect(shown).toContain(`1004 × ${info.height} pixels`);

	await dialog.getByRole('radio', { name: /Double column, 180 mm/ }).check();
	await dialog.getByRole('radio', { name: '600 DPI' }).check();
	await expect(dialog.getByTestId('png-size')).toContainText('180 mm at 600 DPI = 4252');
	const [big] = await downloadFrom(page, dialog);
	expect(pngInfo(await bytes(big))).toMatchObject({ width: 4252, dpi: 600 });

	await dialog.getByRole('radio', { name: 'Custom' }).check();
	await dialog.getByLabel('Width in mm').fill('100');
	await dialog.getByRole('radio', { name: '150 DPI' }).check();
	const [custom] = await downloadFrom(page, dialog);
	expect(pngInfo(await bytes(custom))).toMatchObject({ width: 591, dpi: 150 });
});

test('SVG carries the edited caption and its size in mm; CSV and the spec hide small counts', async ({ page }) => {
	const id = await seededSurvey(page);
	await openResults(page, id);

	let dialog = await exportDialog(page, 'Fruit?', 'SVG image…');
	await expect(dialog.getByLabel('Caption')).toHaveValue(
		'Fruit? (fruit). Version 1; Complete responses only; Denominator: answered. n = 3 responses.'
	);
	await expect(dialog.getByTestId('small-cells')).toContainText('2 shown cells have fewer than 5 responses');
	await dialog.getByLabel('Caption').fill('Figure 1. Favourite fruit of the pilot sample.');
	const [svg] = await downloadFrom(page, dialog);
	expect(svg.suggestedFilename()).toBe('fruit.svg');
	const body = await text(svg);
	expect(body).toMatch(/<svg[^>]* width="85mm" height="[\d.]+mm"[^>]*viewBox="0 0 /);
	expect(body).toContain('Figure 1. Favourite fruit of the pilot sample.');
	await dialog.getByRole('button', { name: 'Done' }).click();

	// "Hide counts below k": CSV and spec mark the hidden cells; the caption says so.
	dialog = await exportDialog(page, 'Satisfied?', 'CSV of the numbers…');
	await dialog.getByRole('checkbox', { name: 'Hide counts below k' }).check();
	await expect(dialog.getByTestId('small-cells')).toHaveCount(0);
	const [csv] = await downloadFrom(page, dialog);
	expect(csv.suggestedFilename()).toBe('sat.csv');
	const lines = (await text(csv)).trim().split('\r\n');
	expect(lines[0]).toContain('group_n,denominator,category,label,bin_lo,bin_hi,count,percent');
	expect(lines.filter((l) => l.endsWith(',<5'))).toHaveLength(4);
	expect(lines.find((l) => l.includes(',3,')) ?? '').toMatch(/,0,0,,,$/); // a zero stays a zero
	await dialog.getByRole('button', { name: 'Done' }).click();

	dialog = await exportDialog(page, 'Satisfied?', 'Vega-Lite spec and manifest…');
	await expect(dialog.getByRole('checkbox', { name: 'Hide counts below k' })).toBeChecked(); // shared settings
	await expect(dialog.getByLabel('Caption')).toHaveValue(/Counts below 5 hidden \(shown as "n<5"; 4 cells\)\.$/);
	const files = await downloadFrom(page, dialog, 2);
	expect(files.map((f) => f.suggestedFilename()).sort()).toEqual(['sat.manifest.json', 'sat.vl.json']);
	const spec = JSON.parse(await text(files.find((f) => f.suggestedFilename() === 'sat.vl.json')!));
	expect(spec.$schema).toContain('vega-lite');
	const data = JSON.stringify(spec);
	expect(data).toContain('"text":"n<5"');
	expect(data).not.toMatch(/"count":1[,}]/);
	const manifest = JSON.parse(await text(files.find((f) => f.suggestedFilename() === 'sat.manifest.json')!));
	expect(manifest).toMatchObject({
		surveyId: id,
		versions: [1],
		denominator: 'answered',
		suppression: { hideCountsBelow: 5 },
		units: 'responses'
	});
	expect(manifest.queryHash).toMatch(/^[0-9a-f]{16}$/);
	expect(manifest.vega.vegaLite).toMatch(/^\d+\.\d+/);
	expect(manifest.figures[0]).toMatchObject({ question: 'sat', hiddenCells: 4, captionEdited: false });
	expect(manifest.figures[0].caption).toContain('Satisfied? (sat).');
});

test('Export all: one ZIP with every card’s files and one manifest', async ({ page }) => {
	test.setTimeout(120_000);
	const id = await seededSurvey(page);
	await openResults(page, id);
	await page.getByRole('button', { name: 'Export all' }).click();
	const dialog = page.getByRole('dialog', { name: 'Export all figures' });
	await expect(dialog).toBeVisible();
	expect(await axe(page)).toEqual([]);
	const downloads: Download[] = [];
	const got = new Promise<void>((resolve) => page.once('download', (d) => (downloads.push(d), resolve())));
	const audit = page.waitForResponse((r) => r.url().endsWith('/results/export'));
	await dialog.getByRole('button', { name: 'Download ZIP' }).click();
	expect((await audit).status()).toBe(200);
	await got;
	expect(downloads[0].suggestedFilename()).toMatch(/^results-[0-9a-f-]{8}-\d{4}-\d{2}-\d{2}\.zip$/);
	const entries = readZip(await bytes(downloads[0]));
	const names = entries.map((e) => e.name);
	for (const q of ['fruit', 'sat', 'col', 'age', 'price', 'sl', 'big', 'when', 'why', 'grid']) {
		for (const ext of ['svg', 'png', 'csv', 'vl.json']) expect(names, `${q}.${ext}`).toContain(`${q}.${ext}`);
	}
	expect(names.at(-1)).toBe('manifest.json');
	expect(names).toHaveLength(41);
	const png = pngInfo(entries.find((e) => e.name === 'grid.png')!.data);
	expect(png).toMatchObject({ width: 1004, dpi: 300 });
	const svg = new TextDecoder().decode(entries.find((e) => e.name === 'grid.svg')!.data);
	expect(svg).toContain('Grid (grid).');
	const manifest = JSON.parse(new TextDecoder().decode(entries.find((e) => e.name === 'manifest.json')!.data));
	expect(manifest.scope).toBe('page');
	expect(manifest.figures).toHaveLength(10);
	expect(manifest.figures.find((f: { question: string }) => f.question === 'fruit').files).toEqual([
		'fruit.svg',
		'fruit.png',
		'fruit.csv',
		'fruit.vl.json'
	]);
});
