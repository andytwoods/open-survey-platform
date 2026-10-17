import { expect, test, type Page } from '@playwright/test';
import { axe, signIn } from './fixtures';

// Import from Qualtrics (.qsf), LimeSurvey (.lss) and SurveyJS JSON (task IM1), end to end
// against a real osp-api: the survey list's Import dialog previews the invented sample
// files (what will be created, what will not carry over), creates the draft and opens it
// in the editor with the imported questions; an unreadable file is refused with reasons.

const SAMPLES = new URL('../../../python/osp-targets/tests/data/imports/', import.meta.url);
const sample = (name: string) => new URL(name, SAMPLES).pathname.replace(/^\/([A-Za-z]:)/, '$1');

const dialog = (page: Page) => page.getByRole('dialog', { name: 'Import a survey' });

async function openDialog(page: Page) {
	await signIn(page);
	await page.getByRole('button', { name: 'Import from Qualtrics, LimeSurvey or SurveyJS…' }).click();
	await expect(dialog(page)).toBeVisible();
}

test.use({ colorScheme: 'light' });

test('a LimeSurvey file is previewed with its losses, then imported into the editor', async ({ page }) => {
	await openDialog(page);
	await dialog(page).getByLabel('Survey file').setInputFiles(sample('coffee.lss'));
	const preview = dialog(page).getByTestId('import-preview');
	await expect(preview).toBeVisible();
	await expect(preview).toContainText('Read as LimeSurvey (.lss)');
	await expect(preview.getByTestId('import-summary')).toContainText('12 questions on 5 pages in 5 blocks');
	await expect(preview.getByTestId('import-summary')).toContainText('Languages: en, de');
	const losses = preview.getByTestId('import-losses');
	await expect(losses.locator('[data-code="lss.question_type"]')).toContainText('ranking questions are not supported');
	await expect(losses.locator('[data-code="lss.other_option"]')).toBeVisible();
	await expect(preview.getByTestId('import-warnings').locator('[data-code="lss.soft_mandatory"]')).toBeVisible();
	await preview.getByText('Notes (').click();
	await expect(preview.getByTestId('import-notes').locator('[data-code="lss.hidden_field"]')).toBeVisible();
	expect(await axe(page)).toEqual([]);

	const title = `Imported LSS ${Date.now()}`;
	await dialog(page).getByLabel('Title').fill(title);
	await dialog(page).getByRole('button', { name: 'Import', exact: true }).click();
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	const outline = page.getByRole('tree', { name: 'Survey outline' });
	await expect(outline).toBeVisible();
	await expect(page.getByRole('banner')).toContainText(title);
	await expect(outline).toContainText('Do you drink coffee?');
	await expect(outline).toContainText('How much do you agree with each statement?');
	await expect(outline).not.toContainText('Rank these');
	// The imported draft is a normal survey: listed, and its draft holds both languages.
	const list = await (await page.request.get('/api/surveys')).json();
	const mine = list.find((s: { title: string }) => s.title === title);
	expect(mine).toBeTruthy();
	const detail = await (await page.request.get(`/api/surveys/${mine.id}`)).json();
	expect(detail.survey.metadata.languages).toEqual(['en', 'de']);
	expect(detail.survey.quotas).toHaveLength(1);
});

test('a Qualtrics file and a SurveyJS file import; the flow carries branches and randomisers', async ({ page }) => {
	await openDialog(page);
	await dialog(page).getByLabel('Survey file').setInputFiles(sample('coffee.qsf'));
	await expect(dialog(page).getByTestId('import-preview')).toContainText('Read as Qualtrics (.qsf)');
	await expect(dialog(page).getByTestId('import-summary')).toContainText('9 questions on 5 pages in 4 blocks');
	await expect(dialog(page).getByTestId('import-losses').locator('[data-code="qsf.question_type"]')).toContainText('rank order');
	await dialog(page).getByRole('button', { name: 'Import', exact: true }).click();
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	await expect(page.getByRole('tree', { name: 'Survey outline' })).toContainText('Which kinds of coffee do you drink?');
	const id = page.url().split('/').pop()!;
	const qsf = await (await page.request.get(`/api/surveys/${id}`)).json();
	expect(qsf.survey.flow.map((n: { type: string }) => n.type)).toEqual(['block', 'branch', 'randomiser', 'end']);

	// A second import from the list page: the dialog starts clean.
	await openDialog(page);
	await dialog(page).getByLabel('Survey file').setInputFiles(sample('coffee-surveyjs.json'));
	await expect(dialog(page).getByTestId('import-preview')).toContainText('Read as SurveyJS JSON');
	await expect(dialog(page).getByTestId('import-summary')).toContainText('12 questions on 3 pages in 1 block');
	await dialog(page).getByRole('button', { name: 'Import', exact: true }).click();
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	await expect(page.getByRole('tree', { name: 'Survey outline' })).toContainText('How well did you sleep last night?');
});

test('an unreadable file is refused with the reason and nothing is created', async ({ page }) => {
	await openDialog(page);
	const before = ((await (await page.request.get('/api/surveys')).json()) as unknown[]).length;
	await dialog(page)
		.getByLabel('Survey file')
		.setInputFiles({ name: 'broken.lss', mimeType: 'text/xml', buffer: Buffer.from('<document><LimeSurveyDocType>Nope</LimeSurveyDocType></document>') });
	const failed = dialog(page).getByTestId('import-failed');
	await expect(failed).toContainText('This file could not be read as a survey.');
	await expect(failed).toContainText('not a LimeSurvey survey structure');
	await expect(dialog(page).getByRole('button', { name: 'Import', exact: true })).toBeDisabled();
	expect(await axe(page)).toEqual([]);
	await dialog(page).getByRole('button', { name: 'Cancel' }).click();
	await expect(dialog(page)).toBeHidden();
	expect(((await (await page.request.get('/api/surveys')).json()) as unknown[]).length).toBe(before);
});
