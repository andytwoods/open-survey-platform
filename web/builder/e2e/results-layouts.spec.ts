import { expect, test, type Page } from '@playwright/test';
import { axe, signIn, writeHeaders } from './fixtures';

// Saved results layouts (task V5b), end to end against a real osp-api on SQLite (V5a's
// layouts API): save, reload and see the layout restored, switch layouts, set the default,
// delete, a duplicate name, keyboard and drag reorder, an unsuitable chart id, 320 px and
// axe in light and dark. The survey is V1's hand-checked fixture with five fake responses.

const card = (page: Page, name: string) => page.getByRole('article', { name });
const picker = (page: Page) => page.getByLabel('Layout', { exact: true });
const unsaved = (page: Page) => page.getByTestId('layout-unsaved');
const titles = (page: Page) => page.getByRole('list', { name: 'Questions' }).getByRole('heading', { level: 3 }).allTextContents();

async function seededSurvey(page: Page): Promise<string> {
	await signIn(page);
	const headers = await writeHeaders(page);
	const survey = await (await page.request.get('/api/e2e/results-fixture')).json();
	const created = await page.request.post('/api/surveys', { headers, data: { title: `Layouts e2e ${Date.now()}`, survey } });
	expect(created.status()).toBe(201);
	const id = (await created.json()).id as string;
	const seeded = await page.request.post(`/api/e2e/results-seed/${id}`, { headers });
	expect(await seeded.json()).toEqual({ version: 1, responses: 5 });
	return id;
}

async function openResults(page: Page, id: string) {
	await page.goto(`/surveys/${id}/results`);
	await expect(page.getByRole('heading', { name: 'Results', level: 2 })).toBeVisible();
	await expect(page.getByRole('list', { name: 'Questions' })).toBeVisible();
	await expect(page.getByTestId('results-count')).toHaveText('5 responses');
}

async function saveAs(page: Page, name: string, makeDefault = false) {
	await page.getByRole('button', { name: 'Save as…' }).click();
	const dialog = page.getByRole('dialog', { name: 'Save layout as' });
	await dialog.getByLabel('Name').fill(name);
	if (makeDefault) await dialog.getByLabel('Open this layout by default').check();
	await dialog.getByRole('button', { name: 'Save' }).click();
	return dialog;
}

test('save a layout, reload: restored; switch layouts, set the default, delete', async ({ page }) => {
	const id = await seededSurvey(page);
	await openResults(page, id);
	await expect(picker(page)).toHaveValue('');
	await expect(unsaved(page)).toBeHidden();

	// Change the page: a chart, a hidden card, the order (keyboard), the denominator.
	await card(page, 'Fruit?').getByRole('combobox', { name: 'Chart' }).selectOption('donut');
	await expect(unsaved(page)).toBeVisible();
	await card(page, 'Why?').getByRole('button', { name: 'Hide Why?' }).click();
	await expect(page.getByTestId('hidden-card')).toContainText('Why?');
	await expect(page.getByRole('button', { name: 'Show Why?' })).toBeFocused();
	const move = page.getByRole('button', { name: 'Move Grid' });
	await move.focus();
	await page.keyboard.press('Home');
	await expect(page.getByRole('button', { name: 'Move Grid' })).toBeFocused();
	await expect(page.getByTestId('move-status')).toHaveText('Grid moved to position 1 of 10.');
	await page.getByRole('radio', { name: 'Shown (answered + unanswered)' }).check();
	await page.getByRole('button', { name: 'Show results' }).click();
	await expect(page.getByTestId('active-filters')).toContainText('Denominator: shown');

	await saveAs(page, 'Paper', true);
	await expect(page.getByTestId('layout-status')).toHaveText('Saved as “Paper”, the default layout.');
	await expect(unsaved(page)).toBeHidden();

	// Reload: the default layout opens, as saved.
	await page.reload();
	await expect(page.getByRole('list', { name: 'Questions' })).toBeVisible();
	await expect(picker(page).locator('option:checked')).toHaveText('Paper (opens by default)');
	await expect.poll(() => titles(page)).toEqual(['Grid', 'Fruit?', 'Satisfied?', 'Colours?', 'Age?', 'Price?', 'Slide', 'Big slide', 'When?']);
	await expect(page.getByTestId('hidden-card')).toContainText('Why?');
	await expect(card(page, 'Fruit?').getByRole('combobox', { name: 'Chart' })).toHaveValue('donut');
	await expect(card(page, 'Fruit?').locator('[data-chart="donut"] svg.marks')).toBeVisible();
	await expect(page.getByRole('radio', { name: 'Shown (answered + unanswered)' })).toBeChecked();
	await expect(unsaved(page)).toBeHidden();

	// A second layout; a duplicate name is refused with a clear message.
	await page.getByRole('button', { name: 'Show Why?' }).click();
	const dup = await saveAs(page, 'Paper');
	await expect(dup.getByTestId('layout-dialog-error')).toHaveText('There is already a layout called “Paper”. Choose another name.');
	await dup.getByLabel('Name').fill('Talk');
	await dup.getByRole('button', { name: 'Save' }).click();
	await expect(dup).toBeHidden();
	await expect(picker(page).locator('option:checked')).toHaveText('Talk');
	await expect(card(page, 'Why?')).toBeVisible();

	// Switch: each layout brings its own cards back.
	await picker(page).selectOption({ label: 'Paper (opens by default)' });
	await expect(page.getByTestId('hidden-card')).toContainText('Why?');
	await expect(unsaved(page)).toBeHidden();
	await picker(page).selectOption({ label: 'Talk' });
	await expect(card(page, 'Why?')).toBeVisible();
	await expect(page.getByTestId('hidden-card')).toHaveCount(0);

	// Make Talk the default: a reload opens it.
	await page.getByRole('button', { name: 'Open by default' }).click();
	await expect(picker(page).locator('option:checked')).toHaveText('Talk (opens by default)');
	await page.reload();
	await expect(picker(page).locator('option:checked')).toHaveText('Talk (opens by default)');
	await expect(card(page, 'Why?')).toBeVisible();

	// Delete it: gone for good, and the next visit has no default.
	await page.getByRole('button', { name: 'Delete…' }).click();
	await page.getByRole('dialog', { name: 'Delete layout?' }).getByRole('button', { name: 'Delete layout' }).click();
	await expect(page.getByTestId('layout-status')).toHaveText('Deleted “Talk”.');
	await expect(picker(page).locator('option')).toHaveText(['Default view (no saved layout)', 'Paper']);
	await page.reload();
	await expect(page.getByRole('list', { name: 'Questions' })).toBeVisible();
	await expect(picker(page)).toHaveValue('');
	await expect.poll(async () => (await titles(page))[0]).toBe('Fruit?');
	expect(await axe(page)).toEqual([]);
});

test('drag a card by its handle to reorder; Save keeps the order', async ({ page }) => {
	// dragTo does not autoscroll: both the handle and the drop target must be on screen at once.
	await page.setViewportSize({ width: 1280, height: 1400 });
	const id = await seededSurvey(page);
	await openResults(page, id);
	await saveAs(page, 'Order');
	await expect(unsaved(page)).toBeHidden();
	await page.getByRole('button', { name: 'Move Satisfied?' }).dragTo(card(page, 'Fruit?'));
	await expect.poll(async () => (await titles(page))[0]).toBe('Satisfied?');
	await expect(unsaved(page)).toBeVisible();
	await page.getByRole('button', { name: 'Save layout' }).click();
	await expect(page.getByTestId('layout-status')).toHaveText('Saved “Order”.');
	await page.reload();
	await expect(page.getByRole('list', { name: 'Questions' })).toBeVisible();
	await picker(page).selectOption({ label: 'Order' });
	await expect.poll(async () => (await titles(page))[0]).toBe('Satisfied?');
});

async function layoutWithNotice(page: Page, id: string) {
	const headers = await writeHeaders(page);
	const r = await page.request.post(`/api/surveys/${id}/results/layouts`, {
		headers,
		data: {
			name: 'Old',
			isDefault: true,
			settings: { cards: [{ question: 'age', chart: 'likert' }, { question: 'why', hidden: true }] }
		}
	});
	expect(r.status()).toBe(201);
}

test('an unsuitable chart id falls back to the default with a notice; unknown fields are refused', async ({ page }) => {
	const id = await seededSurvey(page);
	const headers = await writeHeaders(page);
	const bad = await page.request.post(`/api/surveys/${id}/results/layouts`, {
		headers,
		data: { name: 'Data', settings: { cards: [{ question: 'age', counts: [1, 2] }] } }
	});
	expect(bad.status()).toBe(422);
	await layoutWithNotice(page, id);
	await openResults(page, id);
	await expect(picker(page).locator('option:checked')).toHaveText('Old (opens by default)');
	await expect(page.getByTestId('layout-notices')).toContainText(
		'Age?: the layout\'s chart “Diverging stacked bars” does not suit this question, so it shows Histogram instead.'
	);
	await expect(card(page, 'Age?').getByRole('combobox', { name: 'Chart' })).toHaveValue('histogram');
	await expect(card(page, 'Age?').locator('[data-chart="histogram"] svg.marks')).toBeVisible();
});

for (const scheme of ['light', 'dark'] as const) {
	test(`320 px, ${scheme}: the layout bar wraps, no sideways scroll, axe-clean`, async ({ page }) => {
		await page.emulateMedia({ colorScheme: scheme });
		await page.setViewportSize({ width: 320, height: 800 });
		const id = await seededSurvey(page);
		await layoutWithNotice(page, id);
		await openResults(page, id);
		await expect(page.getByTestId('layout-notices')).toBeVisible();
		await expect(page.getByTestId('hidden-card')).toBeVisible();
		await card(page, 'Fruit?').getByRole('button', { name: 'Hide Fruit?' }).click();
		await expect(unsaved(page)).toBeVisible();
		const doc = await page.evaluate(() => document.documentElement.scrollWidth);
		expect(doc, 'no horizontal page scroll').toBeLessThanOrEqual(320);
		expect(await axe(page)).toEqual([]);
		await page.getByRole('button', { name: 'Save as…' }).click();
		await expect(page.getByRole('dialog', { name: 'Save layout as' })).toBeVisible();
		expect(await axe(page)).toEqual([]);
	});
}
