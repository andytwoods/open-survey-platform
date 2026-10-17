import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';
import { axe, signIn, writeHeaders } from './fixtures';

// Endings per outcome (task EN1, end-of-survey plan §4.1), end to end against a real osp-api:
// the flow's End card says which ending its outcome uses and opens it in Survey settings →
// Endings, where title, text and the status line are edited through `set_ending`.

const survey = () => {
	const s = JSON.parse(readFileSync(new URL('../../../fixtures/11-end-nodes/survey.json', import.meta.url), 'utf8'));
	s.settings = { ...(s.settings ?? {}), retention: { kind: 'indefinite' } };
	return s;
};

const saved = (page: Page) => page.getByRole('banner').getByRole('status').first();
const ending = (page: Page, outcome: string) => page.locator(`#settings-ending-${outcome}`);

async function serverEndings(page: Page, id: string) {
	const detail = await (await page.request.get(`/api/surveys/${id}`)).json();
	return detail.survey.settings.endings as Record<string, Record<string, unknown>>;
}

test('the End card opens its outcome ending, which is edited in Survey settings', async ({ page }) => {
	await signIn(page);
	const res = await page.request.post('/api/surveys', {
		headers: await writeHeaders(page),
		data: { title: `Endings e2e ${Date.now()}`, survey: survey() }
	});
	expect(res.status()).toBe(201);
	const { id } = await res.json();

	// The flow: an outcome with an ending shows its title; one without says it uses the default.
	await page.goto(`/surveys/${id}/flow`);
	await expect(page.getByRole('heading', { name: 'Survey flow', level: 2 })).toBeVisible();
	const ineligible = page.locator('article[data-node-id="end_ineligible"]').getByTestId('ending-line');
	await expect(ineligible).toContainText('“Thank you for your interest”');
	const early = page.locator('article[data-node-id="end_early_exit"]').getByTestId('ending-line');
	await expect(early).toContainText('the default screen');
	await early.getByRole('button', { name: 'Edit ending…' }).click();

	// Survey settings, scrolled to that outcome's ending.
	await expect(page).toHaveURL(new RegExp(`/surveys/${id}/settings#ending-early_exit$`));
	await expect(ending(page, 'early_exit')).toBeFocused();
	await expect(ending(page, 'early_exit')).toContainText('Used by: End node end_early_exit.');
	await expect(ending(page, 'complete')).toContainText('Used by: End of the flow, End node end_complete.');
	await ending(page, 'early_exit').getByRole('button', { name: 'Customise ending for early_exit' }).click();
	await expect(saved(page)).toHaveText(/All changes saved/);

	const title = ending(page, 'early_exit').getByLabel('Title');
	await title.fill('Sorry to hear that');
	await title.blur();
	await expect(saved(page)).toHaveText(/All changes saved/);
	const text = ending(page, 'early_exit').getByLabel('Text');
	await text.fill('You rated breakfast ${rating}.');
	await text.blur();
	await expect(saved(page)).toHaveText(/All changes saved/);
	await ending(page, 'early_exit').getByRole('checkbox', { name: 'Show the status line' }).uncheck();
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect.poll(async () => (await serverEndings(page, id)).early_exit).toEqual({
		title: { en: 'Sorry to hear that' },
		body: { en: 'You rated breakfast ${rating}.' },
		status: 'none'
	});
	// The preview shows the pipe as a token; the builder never resolves it.
	await expect(page.getByTestId('ending-preview-early_exit')).toContainText('Sorry to hear that');
	await expect(page.getByTestId('ending-preview-early_exit').locator('.pipe')).toHaveText('${rating}');

	// The existing ending of `ineligible` is shown as stored, with its status line off.
	await expect(ending(page, 'ineligible').getByLabel('Title')).toHaveValue('Thank you for your interest');
	await expect(ending(page, 'ineligible').getByRole('checkbox', { name: 'Show the status line' })).not.toBeChecked();
	expect(await axe(page)).toEqual([]);

	// Back to the default screen: the ending is removed.
	await ending(page, 'early_exit').getByRole('button', { name: 'Use the default screen' }).click();
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect.poll(async () => Object.keys(await serverEndings(page, id)).sort()).toEqual(['complete', 'ineligible']);
});
