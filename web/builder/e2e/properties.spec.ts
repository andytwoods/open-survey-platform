import { expect, test, type Locator, type Page } from '@playwright/test';
import { axe } from './fixtures';

// Property panel (/dev/properties, task B4): axe in light and dark for every entity, edits
// become set_property ops, focus and caret survive the echoed patch, keyboard-only use,
// and a diagnostic elsewhere focuses its field.

async function open(page: Page, type = 'single') {
	await page.goto('/dev/properties');
	await expect(page.getByRole('heading', { level: 1, name: 'Property panel' })).toBeVisible();
	if (type !== 'single') await page.getByTestId('type').selectOption(type);
}

const log = (page: Page) => page.getByTestId('op-log');
// (The End key doesn't move the caret on macOS.)
const toEnd = (field: Locator) =>
	field.evaluate((el: HTMLTextAreaElement) => el.setSelectionRange(el.value.length, el.value.length));

for (const scheme of ['light', 'dark'] as const) {
	test.describe(`property panel, ${scheme}`, () => {
		test.use({ colorScheme: scheme });
		for (const type of ['single', 'page', 'block', 'survey']) {
			test(`${type} is axe-clean`, async ({ page }) => {
				await open(page, type);
				expect(await axe(page)).toEqual([]);
			});
		}
	});
}

test('typing sends one set_property after a pause; focus and caret survive the patch', async ({ page }) => {
	await open(page);
	const field = page.getByLabel('Question text');
	await field.click();
	await toEnd(field);
	await field.pressSequentially(' Really', { delay: 20 });
	await expect(log(page).getByRole('listitem')).toHaveCount(1);
	await expect(log(page)).toContainText('"property":"label","value":{"en":"How many hours do you sleep? Really"}');
	// Put the caret mid-text; the echoed patch (150 ms later) must not move it or focus.
	await field.evaluate((el: HTMLTextAreaElement) => el.setSelectionRange(4, 8));
	await page.waitForTimeout(400);
	await expect(field).toBeFocused();
	expect(await field.evaluate((el: HTMLTextAreaElement) => [el.selectionStart, el.selectionEnd])).toEqual([4, 8]);
	// Keep typing straight through the next echo.
	await toEnd(field);
	await field.pressSequentially('!', { delay: 20 });
	await field.press('Tab');
	await expect(log(page).getByRole('listitem')).toHaveCount(2);
	await expect(field).toHaveValue('How many hours do you sleep? Really!');
});

test('switch, select and editor buttons work from the keyboard', async ({ page }) => {
	await open(page);
	const required = page.getByRole('switch', { name: 'Required' });
	await required.focus();
	await page.keyboard.press('Space');
	await expect(required).toHaveAttribute('aria-checked', 'true');
	await expect(required).toBeFocused();
	await expect(log(page)).toContainText('"property":"required","value":true');

	await page.getByLabel('Choice order').selectOption('shuffle');
	await expect(log(page)).toContainText('"property":"choiceOrder","value":"shuffle"');

	await page.getByRole('button', { name: 'Choices Edit choices…' }).press('Enter');
	await expect(log(page)).toContainText('openEditor choicelist choices on q_sleep');
	await page.getByRole('button', { name: 'Show if Edit condition…' }).click();
	await expect(log(page)).toContainText('openEditor condition showIf on q_sleep');
});

test('groups collapse, and a diagnostic elsewhere focuses its field', async ({ page }) => {
	await open(page);
	const validation = page.getByRole('button', { name: 'Validation' });
	await validation.focus();
	await page.keyboard.press('Enter');
	await expect(validation).toHaveAttribute('aria-expanded', 'false');
	await expect(page.getByRole('switch', { name: 'Required' })).toBeHidden();

	await page.getByTestId('diagnostic-link').click();
	await expect(validation).toHaveAttribute('aria-expanded', 'true');
	const constraint = page.getByRole('button', { name: 'Constraint Edit condition…' });
	await expect(constraint).toBeFocused();
	await expect(constraint).toHaveAccessibleDescription(/refers to q_missing/);
});

test('translatable fields show the language and a missing-translation hint', async ({ page }) => {
	await open(page);
	await page.getByTestId('language').selectOption('de');
	const field = page.getByLabel('Question text');
	await expect(field).toHaveValue('');
	await expect(field).toHaveAttribute('placeholder', 'How many hours do you sleep?');
	await expect(field).toHaveAccessibleDescription(/de\s*Missing translation/);
	await field.fill('Wie viele Stunden schlafen Sie?');
	await field.press('Tab');
	await expect(log(page)).toContainText(
		'"value":{"en":"How many hours do you sleep?","de":"Wie viele Stunden schlafen Sie?"}'
	);
	await expect(page.locator('[data-property="label"]')).not.toHaveAttribute('data-missing-translation', 'true');
});

test('survey settings write to /metadata and /settings', async ({ page }) => {
	await open(page, 'survey');
	await page.getByRole('switch', { name: 'Allow going back' }).click();
	await expect(log(page)).toContainText('{"target":"/settings","property":"backNavigation","value":false}');
	await page.getByLabel('Default language').selectOption('de');
	await expect(log(page)).toContainText('{"target":"/metadata","property":"defaultLanguage","value":"de"}');
});

test('in the editor against a real osp-api: the panel edits a question through the op client', async ({ page }) => {
	await page.goto('/');
	await expect(page).toHaveURL(/\/login\?next=/);
	await page.getByLabel('Email').fill(process.env.OSP_E2E_EMAIL ?? 'researcher@lab.example');
	await page.getByLabel('Password').fill(process.env.OSP_E2E_PASSWORD ?? 'plover tundra kettle 4417 orbit');
	await page.getByRole('button', { name: 'Sign in' }).click();
	await page.getByLabel('New survey title').fill(`Properties ${Date.now()}`);
	await page.getByRole('button', { name: 'Create survey' }).click();
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	await page.getByRole('button', { name: /Add question to/ }).first().click();

	const saved = page.getByRole('banner').getByRole('status').first();
	const required = page.getByRole('switch', { name: 'Required' });
	await expect(required).toHaveAttribute('aria-checked', 'false');
	await required.click();
	await expect(required).toHaveAttribute('aria-checked', 'true');
	await page.getByLabel('Variable name').fill('sleep_hours');
	await page.getByLabel('Variable name').press('Enter');
	await expect(saved).toHaveText(/All changes saved/);
	expect(await axe(page)).toEqual([]);

	await page.reload();
	await page.getByRole('tree', { name: 'Survey outline' }).getByRole('treeitem', { name: 'New question' }).click();
	await expect(page.getByRole('switch', { name: 'Required' })).toHaveAttribute('aria-checked', 'true');
	await expect(page.getByLabel('Variable name')).toHaveValue('sleep_hours');
});
