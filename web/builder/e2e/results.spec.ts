import { expect, test, type Page } from '@playwright/test';
import { axe, signIn, writeHeaders } from './fixtures';

// The Results page (task V2), end to end against a real osp-api on SQLite: V1's
// hand-checked fixture survey is created through the API, published and given its five
// fake responses by the e2e server's test helper (e2e/api_server.py), then the page is
// opened from the top bar. Cards, Table view, filters, split, denominator, text answers,
// keyboard, 320 px and axe in light and dark.

const banner = (page: Page) => page.getByRole('banner');
const card = (page: Page, name: string) => page.getByRole('article', { name });

async function seededSurvey(page: Page): Promise<string> {
	await signIn(page);
	const headers = await writeHeaders(page);
	const survey = await (await page.request.get('/api/e2e/results-fixture')).json();
	const created = await page.request.post('/api/surveys', {
		headers,
		data: { title: `Results e2e ${Date.now()}`, survey }
	});
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
}

async function noSideScroll(page: Page, width: number) {
	const doc = await page.evaluate(() => document.documentElement.scrollWidth);
	expect(doc, 'no horizontal page scroll').toBeLessThanOrEqual(width);
}

test('the top bar opens Results; cards, Table view, filters, split, denominator and text answers', async ({
	page
}) => {
	const id = await seededSurvey(page);
	await page.goto(`/surveys/${id}`);
	await expect(page.getByRole('tree', { name: 'Survey outline' })).toBeVisible();
	await banner(page).getByRole('button', { name: 'Results' }).click();
	await expect(page).toHaveURL(new RegExp(`/surveys/${id}/results$`));
	await expect(page.getByRole('list', { name: 'Questions' })).toBeVisible();
	await expect(banner(page).getByRole('button', { name: 'Results' })).toHaveAttribute('aria-current', 'page');
	await expect(page).toHaveTitle(/^Results · /);

	// One card per question, in survey order, with the server's counts.
	await expect(page.getByTestId('results-count')).toHaveText('5 responses');
	const titles = await page.getByRole('list', { name: 'Questions' }).getByRole('heading', { level: 3 }).allTextContents();
	expect(titles).toEqual(['Fruit?', 'Satisfied?', 'Colours?', 'Age?', 'Price?', 'Slide', 'Big slide', 'When?', 'Why?', 'Grid']);
	const fruit = card(page, 'Fruit?');
	await expect(fruit.locator('[data-state="answered"] dd')).toHaveText('3');
	await expect(fruit.locator('[data-state="invalid"] dd')).toHaveText('1');
	await expect(fruit.locator('[data-chart="bars"]')).toBeVisible();

	// Table view: the exact numbers.
	await fruit.getByRole('button', { name: 'Table view' }).click();
	const table = fruit.getByRole('table', { name: 'Fruit?' });
	await expect(table.getByRole('row', { name: /Apple/ })).toContainText('66.7 %');
	await expect(table.getByRole('row', { name: /n \(answered\)/ })).toContainText('3');
	expect(await axe(page)).toEqual([]);

	// Filter on an answer: only the two Apple responses remain.
	await page.getByRole('button', { name: 'Add answer filter' }).click();
	await page.getByRole('group', { name: 'Keep responses that answered' }).getByRole('checkbox', { name: 'Apple' }).check();
	await page.getByRole('button', { name: 'Show results' }).click();
	await expect(page.getByTestId('results-count')).toHaveText('2 responses');
	await expect(page.getByTestId('active-filters')).toContainText('Fruit? is Apple');

	// Split by condition, denominator "shown".
	await page.getByRole('button', { name: 'Reset filters' }).click();
	await expect(page.getByTestId('results-count')).toHaveText('5 responses');
	await page.getByLabel('Split by', { exact: true }).selectOption({ label: 'arm' });
	await page.getByRole('radio', { name: 'Shown (answered + unanswered)' }).check();
	await page.getByRole('button', { name: 'Show results' }).click();
	await expect(page.getByTestId('results-count')).toHaveText(/a: 2, b: 2, No condition: 1/);
	await expect(table.getByRole('columnheader', { name: 'a: count' })).toBeVisible();
	await expect(table.getByRole('row', { name: /n \(shown\)/ })).toBeVisible();
	await expect(fruit.getByRole('combobox', { name: 'Chart' })).toHaveValue('grouped');

	// Text: the verbatim answers on request.
	const why = card(page, 'Why?');
	await why.getByRole('button', { name: 'Show answers' }).click();
	const answers = why.getByRole('region', { name: 'Answers to Why?' });
	await expect(answers.getByRole('cell', { name: 'sunny' })).toBeVisible();
	await expect(why.getByText('Answers 1–3 of 3')).toBeVisible();
	expect(await axe(page)).toEqual([]);
});

test('keyboard only: chart menu, Table view and the filters', async ({ page }) => {
	const id = await seededSurvey(page);
	await openResults(page, id);
	const when = card(page, 'When?');
	const menu = when.getByRole('combobox', { name: 'Chart' });
	await menu.focus();
	await menu.selectOption('week'); // a date card per week re-asks the server
	await expect(when.getByRole('table', { name: 'Statistics' })).toBeVisible();
	await expect(when.locator('[data-chart="week"]')).toBeVisible();
	await expect(when.locator('[data-chart="week"]')).toContainText('2026-W');
	const tableButton = when.getByRole('button', { name: 'Table view' });
	await tableButton.focus();
	await page.keyboard.press('Enter');
	await expect(tableButton).toHaveAttribute('aria-pressed', 'true');
	await expect(when.getByRole('columnheader', { name: 'Period (per week)' })).toBeVisible();
	await page.getByLabel('Responses', { exact: true }).focus();
	await page.getByLabel('Responses', { exact: true }).selectOption('all');
	await page.getByRole('button', { name: 'Show results' }).focus();
	await page.keyboard.press('Enter');
	await expect(page.getByTestId('active-filters')).toContainText('All submitted responses');
});

for (const scheme of ['light', 'dark'] as const) {
	test(`320 px, ${scheme}: no sideways scroll, filters fold away, Results in the menu, axe-clean`, async ({
		page
	}) => {
		await page.emulateMedia({ colorScheme: scheme });
		await page.setViewportSize({ width: 320, height: 800 });
		const id = await seededSurvey(page);
		await openResults(page, id);
		await noSideScroll(page, 320);
		// The filters fold behind a button.
		const toggle = page.getByRole('button', { name: 'Show filters' });
		await expect(toggle).toHaveAttribute('aria-expanded', 'false');
		await expect(page.getByRole('button', { name: 'Show results' })).toBeHidden();
		await toggle.click();
		await expect(page.getByRole('button', { name: 'Hide filters' })).toHaveAttribute('aria-expanded', 'true');
		await expect(page.getByRole('button', { name: 'Show results' })).toBeVisible();
		await card(page, 'Grid').getByRole('button', { name: 'Table view' }).click();
		await noSideScroll(page, 320);
		expect(await axe(page)).toEqual([]);

		// The way back to Results from the editor is in "More actions" on a phone.
		await page.goto(`/surveys/${id}`);
		await expect(page.getByRole('button', { name: /Add question to/ }).first()).toBeVisible();
		await expect(banner(page).getByRole('button', { name: 'Results' })).toHaveCount(0);
		await banner(page).getByRole('button', { name: 'More actions' }).click();
		await page.getByRole('menuitem', { name: 'Results' }).click();
		await expect(page).toHaveURL(new RegExp(`/surveys/${id}/results$`));
		await expect(page.getByRole('list', { name: 'Questions' })).toBeVisible();
	});
}

test('an unpublished survey says so instead of asking for results', async ({ page }) => {
	await signIn(page);
	await page.getByLabel('New survey title').fill(`Unpublished results ${Date.now()}`);
	await page.getByRole('button', { name: 'Create survey' }).click();
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	await banner(page).getByRole('button', { name: 'Results' }).click();
	await expect(page.getByTestId('results-unpublished')).toContainText('Nothing is published yet');
	expect(await axe(page)).toEqual([]);
});
