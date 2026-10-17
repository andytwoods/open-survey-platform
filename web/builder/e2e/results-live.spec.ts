import { expect, test, type Page } from '@playwright/test';
import { axe, signIn, writeHeaders } from './fixtures';

// Live results (task LV3, planning/live-results.md), end to end against a real osp-api on
// SQLite whose live poll interval is 1 s (e2e/api_server.py). The survey is V1's fixture
// with five fake responses; the e2e server's helper records one more while the page is
// open. Live on: the new response shows without a click, as one polite announcement, with
// `?live=1` in the URL and the choice kept in a saved layout. Busy (a menu open, filters
// being edited): "1 new response · Refresh" instead. Text answers never refresh by
// themselves (LV-D8). 320 px and axe in light and dark. Presentation mode (task LV4, LV-D5,
// lead decision 1): live in batches of five with small cells hidden on screen, a footer that
// never says how many just arrived, exact counts only through the Present dialog's switch.

const card = (page: Page, name: string) => page.getByRole('article', { name });
const count = (page: Page) => page.getByTestId('results-count');
const toggle = (page: Page) => page.getByTestId('live-toggle');
const badge = (page: Page) => page.getByTestId('live-badge');
const footer = (page: Page) => page.getByTestId('present-footer');
/** A poll a second, a refresh once the researcher has been idle 3 s: well inside this. */
const LIVE = { timeout: 15_000 };

async function seededSurvey(page: Page): Promise<string> {
	await signIn(page);
	const headers = await writeHeaders(page);
	const survey = await (await page.request.get('/api/e2e/results-fixture')).json();
	const created = await page.request.post('/api/surveys', { headers, data: { title: `Live e2e ${Date.now()}`, survey } });
	expect(created.status()).toBe(201);
	const id = (await created.json()).id as string;
	const seeded = await page.request.post(`/api/e2e/results-seed/${id}`, { headers });
	expect(await seeded.json()).toEqual({ version: 1, responses: 5 });
	return id;
}

/** One more response arrives (recorded straight into the store, as a participant's submit would). */
async function arrive(page: Page, id: string, expected: number) {
	const r = await page.request.post(`/api/e2e/results-seed-one/${id}`, { headers: await writeHeaders(page) });
	expect(await r.json()).toEqual({ version: 1, responses: expected });
}

async function openResults(page: Page, id: string, query = '') {
	await page.goto(`/surveys/${id}/results${query}`);
	await expect(page.getByRole('list', { name: 'Questions' })).toBeVisible();
	await expect(count(page)).toHaveText('5 responses');
}

test('Live on: a response that arrives shows without a click, announced once; the URL and a saved layout carry it', async ({ page }) => {
	const id = await seededSurvey(page);
	await openResults(page, id);
	await expect(toggle(page)).toHaveAttribute('aria-checked', 'false');
	await expect(page.getByTestId('live-status')).toHaveCount(0);
	expect(new URL(page.url()).searchParams.has('live')).toBe(false);

	await toggle(page).click();
	await expect(toggle(page)).toHaveAttribute('aria-checked', 'true');
	await expect(page.getByTestId('live-status')).toHaveText('Checking every 1 s');
	expect(new URL(page.url()).searchParams.get('live')).toBe('1');
	await expect(page.getByTestId('layout-unsaved')).toBeVisible(); // Live is a layout setting

	// Hands off the page: the next poll sees the change and the page refreshes by itself.
	await arrive(page, id, 6);
	await expect(count(page)).toHaveText('6 responses', LIVE);
	await expect(page.getByTestId('live-announce')).toHaveText('Results updated: 6 responses.');
	await expect(card(page, 'Fruit?').locator('[data-state="answered"] dd')).toHaveText('4');
	await expect(page.getByTestId('live-status')).toHaveText(/^Checking every 1 s · updated \d\d:\d\d$/);
	await expect(badge(page)).toHaveCount(0);
	expect(await axe(page)).toEqual([]);

	// Saved in a layout: a reload (no ?live= in the URL) opens live.
	await page.getByRole('button', { name: 'Save as…' }).click();
	const dialog = page.getByRole('dialog', { name: 'Save layout as' });
	await dialog.getByLabel('Name').fill('Lab screen');
	await dialog.getByLabel('Open this layout by default').check();
	await dialog.getByRole('button', { name: 'Save' }).click();
	await expect(page.getByTestId('layout-status')).toHaveText('Saved as “Lab screen”, the default layout.');
	await page.goto(`/surveys/${id}/results`);
	await expect(page.getByRole('list', { name: 'Questions' })).toBeVisible();
	await expect(toggle(page)).toHaveAttribute('aria-checked', 'true');
	await expect(page.getByTestId('layout-unsaved')).toBeHidden();
	// A shared link's ?live=0 wins over the layout.
	await page.goto(`/surveys/${id}/results?live=0`);
	await expect(page.getByRole('list', { name: 'Questions' })).toBeVisible();
	await expect(toggle(page)).toHaveAttribute('aria-checked', 'false');
});

test('busy: a menu open or filters being edited gets the badge, not a yank; Refresh applies it; text answers wait for Reload', async ({ page }) => {
	test.setTimeout(90_000);
	const id = await seededSurvey(page);
	await openResults(page, id);
	const why = card(page, 'Why?');
	await why.getByRole('button', { name: 'Show answers' }).click();
	await expect(why.getByText('Answers 1–3 of 3')).toBeVisible();
	await toggle(page).click();
	await expect(page.getByTestId('live-status')).toHaveText('Checking every 1 s');

	// A card's Export menu is open: the badge appears and the numbers stay put.
	await card(page, 'Fruit?').getByRole('button', { name: 'Export Fruit?' }).click();
	await expect(page.getByRole('menu')).toBeVisible();
	await arrive(page, id, 6);
	await expect(badge(page)).toHaveText('1 new response', LIVE);
	await expect(count(page)).toHaveText('5 responses');
	await expect(page.getByRole('menu')).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(page.getByRole('menu')).toHaveCount(0);
	// Idle again (3 s after the last key): the page catches up by itself.
	await expect(count(page)).toHaveText('6 responses', LIVE);
	await expect(badge(page)).toHaveCount(0);

	// Filters being edited (not applied) are work in progress too: badge, then the Refresh button.
	await page.getByLabel('Responses', { exact: true }).selectOption('all');
	await expect(page.getByText('Changes not applied yet.')).toBeVisible();
	await arrive(page, id, 7);
	await expect(badge(page)).toHaveText('1 new response', LIVE);
	await expect(count(page)).toHaveText('6 responses');
	await page.getByRole('button', { name: 'Refresh' }).click();
	await expect(count(page)).toHaveText('7 responses');
	await expect(badge(page)).toHaveCount(0);
	await expect(page.getByText('Changes not applied yet.')).toBeVisible(); // the draft stays a draft
	await expect(page.getByTestId('active-filters')).toContainText('Complete responses only');

	// LV-D8: the text page kept its three answers and says new ones are waiting.
	await expect(why.getByText('Answers 1–3 of 3')).toBeVisible();
	await expect(why.getByTestId('text-stale')).toContainText('New answers have arrived');
	await why.getByRole('button', { name: 'Reload answers' }).click();
	await expect(why.getByText('Answers 1–5 of 5')).toBeVisible();
	await expect(why.getByTestId('text-stale')).toHaveCount(0);
	expect(await axe(page)).toEqual([]);
});

test('presenting live (LV4): batched at five, small cells hidden, the footer never counts the delta; exact counts only via the dialog, with a warning', async ({ page }) => {
	test.setTimeout(120_000);
	const id = await seededSurvey(page);
	await openResults(page, id);
	await card(page, 'Fruit?').getByRole('button', { name: 'Table view' }).click();

	await page.getByRole('button', { name: 'Present' }).click();
	const dialog = page.getByRole('dialog', { name: 'Present results' });
	await expect(dialog).toBeVisible();
	await expect(dialog.getByTestId('present-live')).not.toBeChecked();
	await expect(dialog.getByTestId('present-hide')).toBeChecked();
	await dialog.getByTestId('present-live').check();
	await expect(dialog.getByTestId('present-batched')).toBeChecked();
	await dialog.getByRole('button', { name: 'Start presenting' }).click();
	await expect(page.getByTestId('exit-presentation')).toBeVisible();
	expect(new URL(page.url()).searchParams.get('live')).toBe('1');
	expect(new URL(page.url()).searchParams.get('present')).toBe('1');

	// The suppressed look: Apple (2) and Banana (1) read "n<5" in the table; the footer says so.
	const fruit = card(page, 'Fruit?');
	const table = fruit.getByRole('table', { name: 'Fruit?' });
	await expect(table.getByRole('row', { name: /^Apple/ })).toContainText('n<5');
	await expect(table.getByRole('row', { name: /^Banana/ })).toContainText('n<5');
	await expect(table.getByRole('row', { name: /^Cherry/ })).toContainText('0');
	await expect(fruit.getByTestId('card-caption')).toContainText('Counts below 5 hidden (shown as "n<5"; 2 cells).');
	await expect(footer(page)).toHaveText(/^5 responses · updated \d\d:\d\d · live · counts below 5 hidden$/);
	expect(await axe(page)).toEqual([]);

	// Four responses arrive: the screen keeps what it shows; nothing says "4 new".
	for (let n = 6; n <= 9; n++) await arrive(page, id, n);
	await page.waitForTimeout(3000); // three polls at 1 s
	await expect(footer(page)).toContainText('5 responses');
	await expect(table.getByRole('row', { name: /^Apple/ })).toContainText('n<5');
	await expect(page.getByText(/new response/)).toHaveCount(0);
	// The fifth: one redraw. Each arrival answered Apple, so Apple is 7 (shown); Banana still 1 (hidden).
	await arrive(page, id, 10);
	await expect(footer(page)).toHaveText(/^10 responses · updated \d\d:\d\d · live · counts below 5 hidden$/, LIVE);
	await expect(table.getByRole('row', { name: /^Apple/ })).toContainText('7');
	await expect(table.getByRole('row', { name: /^Banana/ })).toContainText('n<5');
	await expect(fruit.getByTestId('card-caption')).toContainText('1 cell');
	await expect(page.getByTestId('live-announce')).toHaveText('Results updated: 10 responses.');
	await expect(page.getByText(/new response/)).toHaveCount(0);

	// Leaving: back to exact numbers and immediate refreshes; Live stays on.
	await page.getByTestId('exit-presentation').click();
	await expect(toggle(page)).toHaveAttribute('aria-checked', 'true');
	await expect(table.getByRole('row', { name: /^Banana/ })).toContainText('1');
	await expect(footer(page)).toHaveCount(0);

	// Exact counts: only through the dialog's switch, which warns; the URL does not carry it.
	await page.getByRole('button', { name: 'Present' }).click();
	await expect(dialog).toBeVisible();
	await expect(dialog.getByTestId('present-hide')).toBeChecked();
	await dialog.getByTestId('present-hide').uncheck();
	await expect(dialog.getByTestId('present-exact-warning')).toContainText('the person who just pressed Submit');
	await dialog.getByTestId('present-every').check();
	await dialog.getByRole('button', { name: 'Start presenting' }).click();
	await expect(page.getByTestId('exit-presentation')).toBeVisible();
	await expect(table.getByRole('row', { name: /^Banana/ })).toContainText('1');
	await expect(footer(page)).toHaveText(/^10 responses · updated \d\d:\d\d · live$/);
	expect(new URL(page.url()).searchParams.get('live')).toBe('every');
	expect(page.url()).not.toMatch(/exact/);
	// On every change: one response redraws at once.
	await arrive(page, id, 11);
	await expect(footer(page)).toContainText('11 responses', LIVE);
	expect(await axe(page)).toEqual([]);

	// The same link opened afresh is suppressed again: the switch is never in the URL.
	await page.goto(page.url());
	await expect(page.getByTestId('exit-presentation')).toBeVisible();
	await expect(footer(page)).toHaveText(/^11 responses · updated \d\d:\d\d · live · counts below 5 hidden$/);
	await expect(card(page, 'Fruit?').getByTestId('card-caption')).toContainText('Counts below 5 hidden');
});

for (const scheme of ['light', 'dark'] as const) {
	test(`320 px, ${scheme}: the live bar and badge wrap, no sideways scroll, axe-clean`, async ({ page }) => {
		await page.emulateMedia({ colorScheme: scheme });
		await page.setViewportSize({ width: 320, height: 800 });
		const id = await seededSurvey(page);
		await openResults(page, id, '?live=1');
		await expect(toggle(page)).toHaveAttribute('aria-checked', 'true');
		await expect(page.getByTestId('live-status')).toHaveText('Checking every 1 s');
		// Busy (filters open and edited on a phone): the badge.
		await page.getByRole('button', { name: 'Show filters' }).click();
		await page.getByLabel('Responses', { exact: true }).selectOption('all');
		await arrive(page, id, 6);
		await expect(badge(page)).toHaveText('1 new response', LIVE);
		const doc = await page.evaluate(() => document.documentElement.scrollWidth);
		expect(doc, 'no horizontal page scroll').toBeLessThanOrEqual(320);
		expect(await axe(page)).toEqual([]);
	});
}
