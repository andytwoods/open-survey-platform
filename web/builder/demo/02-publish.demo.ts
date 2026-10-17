import { expect, test, type Page } from '@playwright/test';
import { beat, caption, click, press, recordingContext, saveRecording, type } from './overlay';
import { createSurvey, DEMO_TITLE } from './seed';

// Video 2: appearance, settings, consent, publish. Publish is refused until retention is
// set; set it and the consent page; pick a theme; publish and copy the participant link;
// open the link.

const banner = (page: Page) => page.getByRole('banner');
const saved = (page: Page) => expect(banner(page).getByRole('status').first()).toHaveText(/All changes saved/);
const publishDialog = (page: Page) => page.getByRole('dialog', { name: 'Publish' });

test('02 appearance, settings, consent, publish', async ({ browser }) => {
	const context = await recordingContext(browser, '02-settings-and-publish', {
		permissions: ['clipboard-read', 'clipboard-write']
	});
	const page = await context.newPage();
	await page.goto('/');
	const id = await createSurvey(page, DEMO_TITLE);
	await page.goto(`/surveys/${id}`);
	await expect(page.getByRole('tree', { name: 'Survey outline' })).toBeVisible();
	await expect(page.locator('#pane-canvas')).toContainText('How many cups of coffee');
	await caption(page, 'Settings, consent, a theme, then publish', 1800);

	// -- Publish is checked first ---------------------------------------------------------
	await caption(page, 'Publish checks the survey first', 500);
	await click(page, banner(page).getByRole('button', { name: 'Publish', exact: true }));
	const problems = publishDialog(page).getByTestId('publish-problems');
	await expect(problems.locator('[data-code="publish.retention_required"]')).toBeVisible();
	await caption(page, 'Data retention must be chosen before publishing', 1800);
	await click(page, problems.getByRole('button', { name: 'Choose data retention' }));
	await expect(page).toHaveURL(/\/settings#retention$/);

	// -- Retention ------------------------------------------------------------------------
	await caption(page, 'Settings: how long to keep the answers', 500);
	await click(page, page.getByRole('radio', { name: /Keep until I delete it/ }));
	await expect(page.getByTestId('retention-status')).toHaveText(/Retention is set/);
	await saved(page);
	await beat(page, 800);

	// -- Consent --------------------------------------------------------------------------
	await caption(page, 'A consent page before the first question', 500);
	await click(page, page.getByRole('checkbox', { name: 'Show a consent page before the first question' }));
	await type(page, page.getByLabel('Consent text'), 'This invented study asks about coffee and sleep. Taking part is voluntary.');
	await type(page, page.getByLabel('Agree button'), 'Yes, I take part');
	await press(page, 'Tab');
	await expect(page.getByTestId('consent-preview')).toContainText('Yes, I take part');
	await saved(page);
	await page.getByTestId('consent-preview').scrollIntoViewIfNeeded();
	await caption(page, 'The preview shows what participants will see', 1800);

	// -- Appearance -----------------------------------------------------------------------
	await caption(page, 'Appearance: pick a theme', 500);
	await click(page, banner(page).getByRole('button', { name: 'Appearance', exact: true }));
	await expect(page).toHaveURL(/\/appearance$/);
	await click(page, page.getByRole('radio', { name: 'Warm' }));
	await beat(page, 900);
	await type(page, page.getByLabel('Theme name'), 'Coffee lab warm');
	await click(page, page.getByRole('button', { name: 'Save to lab library' }));
	await expect(page.getByText('Saved "Coffee lab warm" to the lab library.')).toBeVisible();
	await click(page, page.getByRole('button', { name: 'Use for this survey' }));
	await expect(page.getByTestId('survey-theme-status')).toHaveText(/This survey uses this theme/);
	await saved(page);
	await caption(page, 'Saved to the lab library and used for this survey', 1500);

	// -- Publish --------------------------------------------------------------------------
	await caption(page, 'Publish', 500);
	await click(page, banner(page).getByRole('button', { name: 'Publish', exact: true }));
	const result = publishDialog(page).getByTestId('publish-result');
	await expect(result).toContainText('Published version 1');
	await caption(page, 'Published: the participant link, exports and a reproducibility package', 2000);
	const link = await result.getByLabel('Participant link').inputValue();
	await click(page, result.getByRole('button', { name: 'Copy link' }));
	await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(link);
	await caption(page, 'Link copied', 1200);

	// -- The link -------------------------------------------------------------------------
	await caption(page, 'Open the link: consent first, in the chosen theme', 300);
	await page.goto(link);
	await expect(page.getByText('Taking part is voluntary.')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Yes, I take part' })).toBeVisible();
	await beat(page, 600);
	await click(page, page.getByRole('button', { name: 'Yes, I take part' }));
	await expect(page.getByText('How many cups of coffee did you drink yesterday?')).toBeVisible();
	await caption(page, 'Then the first page, in the Warm theme', 2000);
	await caption(page, '', 400);
	await saveRecording(context, page, '02-settings-and-publish');
});
