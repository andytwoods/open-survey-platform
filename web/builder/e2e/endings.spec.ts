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
	// EN5: the answers list, with its shared-device privacy note.
	const answers = ending(page, 'early_exit').getByRole('checkbox', { name: 'Show participants their answers' });
	await expect(ending(page, 'early_exit')).toContainText('On a shared device the answers stay on screen');
	await answers.check();
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect.poll(async () => (await serverEndings(page, id)).early_exit).toEqual({
		title: { en: 'Sorry to hear that' },
		body: { en: 'You rated breakfast ${rating}.' },
		status: 'none',
		summary: 'answers'
	});
	await answers.uncheck();
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect.poll(async () => (await serverEndings(page, id)).early_exit.summary).toBeUndefined();
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

// End redirects (task EN2, end-of-survey plan §4.2): a redirect template is declared once
// (`set_redirect_template`), an ending points at it with literal or piped values
// (`set_ending`), the URL preview keeps pipes as tokens, a piped answer is flagged as a data
// export, a template that could change the site is refused, and the preview never navigates.
test('an ending redirects to a declared template; piped answers are flagged; bad templates refused', async ({ page }) => {
	await signIn(page);
	const res = await page.request.post('/api/surveys', {
		headers: await writeHeaders(page),
		data: { title: `Redirects e2e ${Date.now()}`, survey: survey() }
	});
	expect(res.status()).toBe(201);
	const { id } = await res.json();
	await page.goto(`/surveys/${id}/settings#redirect-templates`);
	const templates = page.getByTestId('redirect-templates');
	await expect(templates).toBeVisible();

	// A template with a placeholder in the site is refused before anything is sent.
	await templates.getByLabel('Template name').fill('evil');
	await templates.getByLabel('Address').fill('https://{host}/done');
	await templates.getByRole('button', { name: 'Add template' }).click();
	await expect(templates.getByRole('alert')).toContainText('placeholder cannot be part of the site');
	await expect(templates.locator('[data-template]')).toHaveCount(0);

	// A good one: the pattern fields appear per placeholder.
	await templates.getByLabel('Template name').fill('prolific');
	await templates.getByLabel('Address').fill('https://app.prolific.com/submissions/complete?cc={cc}&r={r}');
	await templates.getByLabel('Pattern for {cc} (optional)').fill('[A-Z0-9]{4,8}');
	await templates.getByRole('button', { name: 'Add template' }).click();
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect(templates.locator('[data-template="prolific"]')).toContainText('app.prolific.com/submissions/complete');

	// The complete ending sends participants there: a literal code and a piped answer.
	const complete = ending(page, 'complete');
	const afterwards = complete.getByTestId('redirect-complete');
	await afterwards.getByLabel('Send participants to').selectOption('prolific');
	await expect(saved(page)).toHaveText(/All changes saved/);
	await afterwards.getByLabel('Value for {cc}').fill('C1AB2');
	await afterwards.getByLabel('Value for {cc}').blur();
	await expect(saved(page)).toHaveText(/All changes saved/);
	await afterwards.getByLabel('Value for {r}').fill('${rating}');
	await afterwards.getByLabel('Value for {r}').blur();
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect(page.getByTestId('redirect-url-complete')).toHaveText('https://app.prolific.com/submissions/complete?cc=C1AB2&r=${rating}');
	// A piped answer is a data export: the server says so, inline.
	await expect(complete.locator('[data-code="redirect.param_question"]')).toContainText("'rating' is an answer");
	// Mode, delay and label.
	await afterwards.getByLabel('Go there').selectOption('link');
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect(afterwards.getByLabel(/Countdown/)).toHaveCount(0);
	await afterwards.getByLabel('Go there').selectOption('auto');
	await expect(saved(page)).toHaveText(/All changes saved/);
	await afterwards.getByLabel(/Countdown/).fill('0');
	await afterwards.getByLabel(/Countdown/).blur();
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect(afterwards).toContainText('With 0 seconds this screen is never seen');
	await expect(complete.locator('[data-code="redirect.immediate"]')).toBeVisible();
	await afterwards.getByLabel('Button label').fill('Back to Prolific');
	await afterwards.getByLabel('Button label').blur();
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect.poll(async () => (await serverEndings(page, id)).complete.redirect).toEqual({
		template: 'prolific',
		params: { cc: 'C1AB2', r: '${rating}' },
		delay: 0,
		label: { en: 'Back to Prolific' }
	});
	expect(await axe(page)).toEqual([]);

	// A literal that can never pass its pattern is an error; removing the template leaves
	// the ending with an "unknown template" error rather than a silent drop.
	await afterwards.getByLabel('Value for {cc}').fill('../evil');
	await afterwards.getByLabel('Value for {cc}').blur();
	await expect(complete.locator('[data-code="redirect.param_literal"]')).toBeVisible();
	await templates.getByRole('button', { name: 'Remove prolific' }).click();
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect(complete.locator('[data-code="redirect.unknown_template"]')).toBeVisible();
	await afterwards.getByLabel('Send participants to').selectOption('');
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect.poll(async () => (await serverEndings(page, id)).complete.redirect).toBeUndefined();
});
