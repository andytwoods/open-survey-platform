import { expect, test, type Page } from '@playwright/test';
import { signIn } from './fixtures';

// Survey languages (task F2), end to end against a real osp-api (e2e/api_server.py): each
// set_languages sends the whole list, so a second add or remove made before the server has
// answered the first must not undo it. The ops are held back so the clicks really overlap.

const banner = (page: Page) => page.getByRole('banner');
const saved = (page: Page) => banner(page).getByRole('status').first();
const tags = (page: Page) => page.getByRole('list', { name: 'Survey languages' }).getByRole('listitem');

test('two quick adds, then two quick removes, all land', async ({ page }) => {
	await signIn(page);
	await page.getByLabel('New survey title').fill(`Languages e2e ${Date.now()}`);
	await page.getByRole('button', { name: 'Create survey' }).click();
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	await page.goto(`${page.url()}/settings`);
	await expect(tags(page)).toHaveCount(1);
	const first = (await tags(page).first().locator('span[lang]').textContent())!;

	// Hold each op back, so the second click is made while the first is still in flight.
	await page.route('**/api/surveys/*/ops', async (route) => {
		await new Promise((r) => setTimeout(r, 400));
		await route.continue();
	});

	const input = page.getByLabel('Add a language (tag, e.g. de or pt-BR)');
	await input.fill('de');
	await input.press('Enter');
	await input.fill('fr');
	await input.press('Enter');
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect(tags(page).locator('span[lang]')).toHaveText([first, 'de', 'fr']);
	await expect(input).toHaveValue('');

	await page.getByRole('button', { name: 'Remove language de' }).click();
	await page.getByRole('button', { name: 'Remove language fr' }).click();
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect(tags(page).locator('span[lang]')).toHaveText([first]);

	// What the server kept, not just what the page shows.
	await page.unrouteAll({ behavior: 'ignoreErrors' });
	await page.reload();
	await expect(tags(page).locator('span[lang]')).toHaveText([first]);
});
