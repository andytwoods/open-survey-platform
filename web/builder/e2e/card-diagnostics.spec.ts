import { expect, test, type Page } from '@playwright/test';
import { axe, signIn, writeHeaders } from './fixtures';

// Validator error/warning counts on canvas cards (B18), against a real osp-api on SQLite
// (e2e/api_server.py, started by the Playwright config).

type Survey = { metadata: Record<string, unknown>; blocks: { pages: { items: unknown[] }[] }[]; [k: string]: unknown };

async function signInAndCreate(page: Page, title: string): Promise<string> {
	await signIn(page);
	await page.getByLabel('New survey title').fill(title);
	await page.getByRole('button', { name: 'Create survey' }).click();
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	await expect(page.getByRole('tree', { name: 'Survey outline' })).toBeVisible();
	return page.url().split('/').pop()!;
}

const card = (page: Page, id: string) => page.locator(`[data-question-card="${id}"]`);

test('cards show their own error and warning counts, go to the property, and update live', async ({ page }) => {
	const id = await signInAndCreate(page, `Card diagnostics ${Date.now()}`);
	const start = (await (await page.request.get(`/api/surveys/${id}`)).json()) as { survey: Survey };
	const survey = structuredClone(start.survey);
	// French is declared but nothing is translated: a missing-translation warning per text.
	survey.metadata = { ...survey.metadata, languages: ['en', 'fr'] };
	survey.blocks[0].pages[0].items.push(
		{ type: 'integer', id: 'age', label: { en: 'Age' }, min: 10, max: 1 }, // min > max: an error
		{ type: 'text', id: 'why', label: { en: 'Why?' } }
	);
	const r = await page.request.post(`/api/surveys/${id}/ops`, {
		headers: await writeHeaders(page),
		data: { baseRevision: 0, ops: [{ op: 'replace_survey', params: { survey } }] }
	});
	expect(r.status()).toBe(200);
	await page.reload();

	const age = card(page, 'age');
	const why = card(page, 'why');
	await expect(age.getByRole('button', { name: '1 error', exact: true })).toBeVisible();
	await expect(age.getByRole('button', { name: /^\d+ warnings?$/ })).toBeVisible();
	await expect(why.getByRole('button', { name: /error/ })).toHaveCount(0);
	await expect(why.getByRole('button', { name: /^\d+ warnings?$/ })).toBeVisible();
	// The count's description is the validator's message.
	await expect(age.getByRole('button', { name: '1 error', exact: true })).toHaveAccessibleDescription(
		/min is greater than max/
	);
	expect(await axe(page)).toEqual([]);

	// The error count goes to the property it is about, and selects the question.
	await age.getByRole('button', { name: '1 error', exact: true }).click();
	await expect(page.locator('#pane-properties :focus')).toHaveAttribute('id', /min$/);
	await expect(age).toHaveAttribute('data-selected', '');

	// A warning count on another card goes to its label.
	await why.getByRole('button', { name: /^\d+ warnings?$/ }).click();
	await expect(page.locator('#pane-properties :focus')).toHaveAttribute('id', /label/);
	await expect(why).toHaveAttribute('data-selected', '');

	// Fix the bounds in the panel: the error count disappears without a reload.
	await age.getByRole('button', { name: '1 error', exact: true }).click();
	const max = page.locator('#pane-properties').getByRole('textbox', { name: 'Maximum' });
	await max.fill('20');
	await max.press('Enter');
	await expect(age.getByRole('button', { name: /error/ })).toHaveCount(0);
	await expect(age.getByRole('button', { name: /^\d+ warnings?$/ })).toBeVisible();
	await expect(page.getByTestId('diagnostics-strip').getByTestId('count-errors')).toHaveText(/^0 errors/);
	expect(await axe(page)).toEqual([]);
});
