import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';
import { axe, fillRich, signIn, writeHeaders } from './fixtures';

// Survey languages (task F2), end to end against a real osp-api (e2e/api_server.py): each
// set_languages sends the whole list, so a second add or remove made before the server has
// answered the first must not undo it. The ops are held back so the clicks really overlap.
// Then the editing language (planning/rich-text.md §5, task RT6): one select per page drives
// the properties pane, the flow's End cards and the consent editor; a translated field shows
// the default-language text as a reference with Copy from <default>; the choice lives in
// `?lang=` and is remembered per survey.

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

// -- the editing language (RT6) ---------------------------------------------------------------

/** The end-nodes fixture in English and German: one question label is a map, the rest plain. */
const bilingual = () => {
	const s = JSON.parse(readFileSync(new URL('../../../fixtures/11-end-nodes/survey.json', import.meta.url), 'utf8'));
	s.metadata.languages = ['en', 'de'];
	s.settings = { ...(s.settings ?? {}), retention: { kind: 'indefinite' } };
	s.blocks[0].pages[0].items[0].label = { en: 'Are you willing to answer two more questions?' };
	s.choiceLists[0].choices[0].label = { en: 'Yes' };
	return s;
};

async function createBilingual(page: Page): Promise<string> {
	await signIn(page);
	const res = await page.request.post('/api/surveys', {
		headers: await writeHeaders(page),
		data: { title: `Editing language e2e ${Date.now()}`, survey: bilingual() }
	});
	expect(res.status()).toBe(201);
	return (await res.json()).id as string;
}

const editingLanguage = (page: Page) => page.getByLabel('Editing language').first();
const labelField = (page: Page) => page.locator('[data-property="label"]');
const strip = (page: Page) => labelField(page).getByTestId('reference-strip');

test('the properties pane edits one language at a time: reference, copy, counts, URL and memory', async ({ page }) => {
	const id = await createBilingual(page);
	await page.goto(`/surveys/${id}`);
	await page.getByRole('tree', { name: 'Survey outline' }).getByRole('treeitem', { name: /Are you willing/ }).click();
	const field = page.getByLabel('Question text');
	await expect(field).toHaveText('Are you willing to answer two more questions?');
	await expect(editingLanguage(page)).toHaveValue('en');
	await expect(strip(page)).toHaveCount(0);
	await expect(labelField(page).locator('.osp-rt-count')).toHaveText(/45 \/ 2,000/);

	// German: the field is empty (missing), the English text is the placeholder and the reference.
	await editingLanguage(page).selectOption('de');
	await expect(page).toHaveURL(/\?lang=de$/);
	await expect(labelField(page)).toHaveAttribute('data-missing-translation', 'true');
	await expect(labelField(page)).toContainText('Missing translation');
	await expect(field).toHaveAttribute('lang', 'de');
	await expect(field).toHaveAttribute('aria-placeholder', 'Are you willing to answer two more questions?');
	await expect(labelField(page).locator('.osp-rt-count')).toHaveText(/0 \/ 2,000/);
	await expect(strip(page).getByRole('button', { name: 'Reference (en)' })).toHaveAttribute('aria-expanded', 'true');
	await expect(strip(page).locator('.osp-rt-ref-body')).toHaveText('Are you willing to answer two more questions?');
	await expect(strip(page).locator('.osp-rt-ref-body')).toHaveAttribute('lang', 'en');
	expect(await axe(page)).toEqual([]);

	// Copy from en, by keyboard: the English text becomes the German starting point, saved at once.
	const copy = strip(page).getByRole('button', { name: 'Copy from en' });
	await expect(copy).toBeEnabled();
	await copy.focus();
	await page.keyboard.press('Enter');
	await expect(field).toHaveText('Are you willing to answer two more questions?');
	await expect(copy).toBeDisabled();
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect(labelField(page)).not.toHaveAttribute('data-missing-translation', 'true');

	// Translate it; the count is this language's.
	await fillRich(page, field, 'Möchten Sie zwei weitere Fragen beantworten?');
	await page.keyboard.press('Tab');
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect(labelField(page).locator('.osp-rt-count')).toHaveText(/44 \/ 2,000/);
	await expect(copy).toBeEnabled();

	// The reference collapses by keyboard; the choice is remembered across a reload, as is the language.
	const toggle = strip(page).getByRole('button', { name: 'Reference (en)' });
	await toggle.focus();
	await page.keyboard.press('Enter');
	await expect(toggle).toHaveAttribute('aria-expanded', 'false');
	await expect(strip(page).locator('.osp-rt-ref-body')).toBeHidden();
	await page.reload();
	await page.getByRole('tree', { name: 'Survey outline' }).getByRole('treeitem', { name: /Are you willing/ }).click();
	await expect(editingLanguage(page)).toHaveValue('de');
	await expect(page.getByLabel('Question text')).toHaveText('Möchten Sie zwei weitere Fragen beantworten?');
	await expect(toggle).toHaveAttribute('aria-expanded', 'false');
	await toggle.focus();
	await page.keyboard.press('Space');
	await expect(toggle).toHaveAttribute('aria-expanded', 'true');
	await expect(strip(page).locator('.osp-rt-ref-body')).toBeVisible();

	// The pane's choice reaches the choice dialog: labels are edited in German there too (a
	// plain-string label counts for every language, as the validator sees it).
	await page.getByRole('button', { name: 'Edit choices…' }).click();
	const dialog = page.getByRole('dialog', { name: 'Edit choices' });
	// Choice labels are one-line rich-text fields (RT5): empty in German, with the default
	// text as the placeholder; a plain label counts for every language.
	const yes = dialog.getByRole('textbox', { name: 'Label for choice 1', exact: true });
	await expect(yes).toHaveAttribute('aria-placeholder', 'Yes');
	await expect(yes.locator('.osp-rt-placeholder')).toHaveText('Yes');
	await expect(dialog.getByRole('textbox', { name: 'Label for choice 2', exact: true })).toHaveText('No');
	await fillRich(page, yes, 'Ja');
	await page.keyboard.press('Enter');
	await expect(saved(page)).toHaveText(/All changes saved/);
	await dialog.getByRole('button', { name: 'Done' }).click();

	// Back to English: the URL drops the parameter and the field shows the English text; a
	// fresh page of the same survey without `?lang=` remembers the last choice.
	await editingLanguage(page).selectOption('en');
	await expect(page).not.toHaveURL(/lang=/);
	await expect(page.getByLabel('Question text')).toHaveText('Are you willing to answer two more questions?');
	await expect(strip(page)).toHaveCount(0);
	await page.goto(`/surveys/${id}`);
	await expect(editingLanguage(page)).toHaveValue('en');
	await page.goto(`/surveys/${id}?lang=de`);
	await expect(editingLanguage(page)).toHaveValue('de');

	// What the server holds: both languages, the English untouched.
	const detail = await (await page.request.get(`/api/surveys/${id}`)).json();
	expect(detail.survey.blocks[0].pages[0].items[0].label).toEqual({
		en: 'Are you willing to answer two more questions?',
		de: 'Möchten Sie zwei weitere Fragen beantworten?'
	});
	expect(detail.survey.choiceLists[0].choices[0].label).toEqual({ en: 'Yes', de: 'Ja' });
});

test('the flow and the settings page share the editing language: End message and consent', async ({ page }) => {
	const id = await createBilingual(page);

	// The flow, opened in German from the URL: the End card's message is missing, with the
	// English as reference; Copy from en fills it.
	await page.goto(`/surveys/${id}/flow?lang=de`);
	await expect(page.getByRole('heading', { name: 'Survey flow', level: 2 })).toBeVisible();
	await expect(editingLanguage(page)).toHaveValue('de');
	const card = page.locator('article[data-node-id="end_ineligible"]');
	await expect(card).toContainText('Missing translation');
	const message = card.getByRole('textbox', { name: 'Message' });
	await expect(message.locator('.osp-rt-placeholder')).toHaveText('You chose not to go on.');
	await expect(message).toHaveAttribute('aria-placeholder', 'You chose not to go on.');
	await expect(card.getByTestId('reference-strip').locator('.osp-rt-ref-body')).toHaveText('You chose not to go on.');
	expect(await axe(page)).toEqual([]);
	await card.getByRole('button', { name: 'Copy from en' }).click();
	await expect(message).toHaveText('You chose not to go on.');
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect(card).not.toContainText('Missing translation');

	// Survey settings remembers German; the consent and endings editors' selects are the same choice.
	await page.goto(`/surveys/${id}/settings`);
	await expect(page.locator('#endings-editing-language')).toHaveValue('de');
	await page.locator('#endings-editing-language').selectOption('en');
	await page.getByRole('checkbox', { name: 'Show a consent page before the first question' }).check();
	await expect(page.locator('#consent-editing-language')).toHaveValue('en');
	await fillRich(page, page.getByLabel('Consent text'), 'Taking part is voluntary.');
	await page.keyboard.press('Tab');
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect(page.getByTestId('consent-missing')).toHaveText('Not translated yet: de.');

	await page.locator('#consent-editing-language').selectOption('de');
	await expect(page).toHaveURL(/\?lang=de$/);
	await expect(page.locator('#endings-editing-language')).toHaveValue('de');
	const consent = page.locator('#settings-consent');
	await expect(consent.getByTestId('reference-strip').first().locator('.osp-rt-ref-body')).toHaveText('Taking part is voluntary.');
	expect(await axe(page)).toEqual([]);
	await consent.getByRole('button', { name: 'Copy from en' }).first().click();
	await expect(page.getByLabel('Consent text')).toHaveText('Taking part is voluntary.');
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect(page.getByTestId('consent-missing')).toHaveCount(0);

	const detail = await (await page.request.get(`/api/surveys/${id}`)).json();
	expect(detail.survey.consent.text).toEqual({ en: 'Taking part is voluntary.', de: 'Taking part is voluntary.' });
	const end = detail.survey.flow[1].then[0];
	expect(end.message).toEqual({ en: 'You chose not to go on.', de: 'You chose not to go on.' });
});
