import { expect, test, type Page } from '@playwright/test';
import { axe, pickQuestionType, signIn } from './fixtures';

// Survey settings, Appearance save actions and Publish (task B12), end to end against a
// real osp-api on SQLite (e2e/api_server.py, which also serves the participant app):
// publish is refused without retention and links to the fix; set retention, consent and a
// theme; publish; the participant link opens the survey in the chosen theme.

const WARM_LIGHT_ACCENT = '#a3431a';

test.use({ colorScheme: 'light' });

async function signInAndCreate(page: Page, title: string) {
	await signIn(page);
	await page.getByLabel('New survey title').fill(title);
	await page.getByRole('button', { name: 'Create survey' }).click();
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	await expect(page.getByRole('tree', { name: 'Survey outline' })).toBeVisible();
}

const banner = (page: Page) => page.getByRole('banner');
const saved = (page: Page) => banner(page).getByRole('status').first();
const publishDialog = (page: Page) => page.getByRole('dialog', { name: 'Publish' });

test('settings → theme → publish → the participant link shows the survey in that theme', async ({ page }) => {
	await signInAndCreate(page, `Publish e2e ${Date.now()}`);
	// A question, so the survey has something to answer.
	await page.getByRole('button', { name: /Add question to/ }).first().click();
	await pickQuestionType(page);
	await expect(saved(page)).toHaveText(/All changes saved/);

	// Publishing without retention is refused, with a link to the retention control.
	await banner(page).getByRole('button', { name: 'Publish', exact: true }).click();
	const problems = publishDialog(page).getByTestId('publish-problems');
	await expect(problems).toBeVisible();
	await expect(problems.locator('[data-code="publish.retention_required"]')).toBeVisible();
	await expect(problems.locator('[data-code="publish.consent_missing"]')).toContainText('Warning');
	expect(await axe(page)).toEqual([]);
	await problems.getByRole('button', { name: 'Choose data retention' }).click();
	await expect(page).toHaveURL(/\/settings#retention$/);
	await expect(page.locator('#settings-retention')).toBeFocused();
	expect(await axe(page)).toEqual([]);

	// Save mode: switching it shows what the mode costs.
	const explanation = page.getByTestId('save-mode-explanation');
	await expect(explanation).toContainText('Drop-outs are visible');
	await page.getByRole('combobox', { name: 'Saving', exact: true }).selectOption('end-only');
	await expect(explanation).toContainText('Drop-outs are invisible');
	await expect(explanation).toContainText('Refreshing the page');
	await expect(saved(page)).toHaveText(/All changes saved/);
	await page.getByRole('combobox', { name: 'Saving', exact: true }).selectOption('every-page');
	await expect(explanation).toContainText('Drop-outs are visible');

	// Retention.
	await page.getByRole('radio', { name: /Keep until I delete it/ }).check();
	await expect(page.getByTestId('retention-status')).toHaveText(/Retention is set/);

	// Consent: text, labels, decline counting, preview.
	await page.getByRole('checkbox', { name: 'Show a consent page before the first question' }).check();
	const text = page.getByLabel('Consent text');
	await text.fill('This study asks about sleep. Taking part is voluntary.');
	await text.blur();
	await page.getByLabel('Agree button').fill('Yes, I take part');
	await page.getByLabel('Agree button').blur();
	await page.getByRole('checkbox', { name: 'Count declines' }).check();
	await expect(page.getByTestId('consent-preview')).toContainText('Taking part is voluntary.');
	await expect(page.getByTestId('consent-preview')).toContainText('Yes, I take part');
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect(await axe(page)).toEqual([]);

	// Appearance: pick the Warm preset, save it to the library, use it for this survey.
	await banner(page).getByRole('button', { name: 'Appearance', exact: true }).click();
	await expect(page).toHaveURL(/\/appearance$/);
	await page.getByRole('radio', { name: 'Warm' }).check();
	await page.getByLabel('Theme name').fill('Lab warm');
	await page.getByRole('button', { name: 'Save to lab library' }).click();
	await expect(page.getByText('Saved "Lab warm" to the lab library.')).toBeVisible();
	await page.getByRole('button', { name: 'Make lab default' }).click();
	await expect(page.getByText('"Lab warm" is now the lab default theme.')).toBeVisible();
	await page.getByRole('button', { name: 'Use for this survey' }).click();
	await expect(page.getByTestId('survey-theme-status')).toHaveText(/This survey uses this theme/);
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect(await axe(page)).toEqual([]);

	// Publish: the link, its copy button, the version and the export links.
	await banner(page).getByRole('button', { name: 'Publish', exact: true }).click();
	const result = publishDialog(page).getByTestId('publish-result');
	await expect(result).toContainText('Published version 1');
	const link = await result.getByLabel('Participant link').inputValue();
	expect(link).toMatch(/\/s\/[^/]+$/);
	await expect(result.getByRole('button', { name: 'Copy link' })).toBeVisible();
	await expect(result.getByRole('link', { name: 'XLSForm (.xlsx)' })).toHaveAttribute('href', /export\/xlsform$/);
	await expect(result.getByRole('link', { name: 'LimeSurvey (.lss)' })).toHaveAttribute('href', /export\/lss$/);
	const repro = result.getByRole('link', { name: 'Reproducibility package' });
	await expect(repro).toHaveAttribute('href', /\/versions\/1\/repro-package$/);
	expect((await page.request.get((await repro.getAttribute('href'))!)).status()).toBe(200);
	expect(await axe(page)).toEqual([]);

	// The participant link: consent first, in the chosen theme.
	const participant = await page.context().newPage();
	await participant.goto(link);
	await expect(participant.getByText('Taking part is voluntary.')).toBeVisible({ timeout: 20_000 });
	await expect(participant.getByRole('button', { name: 'Yes, I take part' })).toBeVisible();
	const accent = await participant.evaluate(() =>
		document.documentElement.style.getPropertyValue('--color-accent').trim()
	);
	expect(accent).toBe(WARM_LIGHT_ACCENT);
	await participant.close();
});
