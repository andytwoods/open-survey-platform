import { expect, test, type Page } from '@playwright/test';
import { axe } from './fixtures';

// End to end against a real osp-api on SQLite (e2e/api_server.py, started by the
// Playwright config): sign in, create a survey, edit through ops, undo/redo, reload.

const EMAIL = process.env.OSP_E2E_EMAIL ?? 'researcher@lab.example';
const PASSWORD = process.env.OSP_E2E_PASSWORD ?? 'plover tundra kettle 4417 orbit';

async function signIn(page: Page) {
	await page.goto('/');
	await expect(page).toHaveURL(/\/login\?next=/);
	await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
	await page.getByLabel('Email').fill(EMAIL);
	await page.getByLabel('Password').fill(PASSWORD);
	await page.getByRole('button', { name: 'Sign in' }).click();
	await expect(page.getByRole('heading', { name: 'Your surveys' })).toBeVisible();
}

async function createSurvey(page: Page, title: string) {
	await page.getByLabel('New survey title').fill(title);
	await page.getByRole('button', { name: 'Create survey' }).click();
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	await expect(page.getByRole('banner').getByRole('heading', { level: 1 })).toHaveText(title);
	await expect(page.getByRole('tree', { name: 'Survey outline' })).toBeVisible();
}

const saveState = (page: Page) => page.getByRole('banner').getByRole('status').first();
const tree = (page: Page) => page.getByRole('tree', { name: 'Survey outline' });
const question = (page: Page, name: string) => tree(page).getByRole('treeitem', { name, exact: true });

async function addQuestionFromPalette(page: Page) {
	await page.getByRole('main', { name: 'Canvas' }).click({ position: { x: 5, y: 5 } });
	await page.keyboard.press('ControlOrMeta+k');
	const dialog = page.getByRole('dialog', { name: 'Command palette' });
	await expect(dialog).toBeVisible();
	await page.keyboard.type('add question');
	await expect(dialog.getByRole('option', { name: /Add question/ })).toBeVisible();
	await page.keyboard.press('Enter');
	await expect(dialog).toBeHidden();
}

test('sign in, create, add, rename, undo, redo, reload', async ({ page }) => {
	await page.goto('/login');
	expect(await axe(page)).toEqual([]);
	await signIn(page);
	expect(await axe(page)).toEqual([]);

	const title = `E2E survey ${Date.now()}`;
	await createSurvey(page, title);
	await expect(saveState(page)).toHaveText(/All changes saved/);
	expect(await axe(page)).toEqual([]);

	// add_question (via the palette); the new question is selected.
	await addQuestionFromPalette(page);
	await expect(question(page, 'New question')).toHaveAttribute('aria-selected', 'true');
	await expect(saveState(page)).toHaveText(/All changes saved/);

	// Rename through the buffered text field: one set_property on blur.
	const field = page.getByLabel('Question text');
	await expect(field).toHaveValue('New question');
	await field.fill('How many hours do you sleep?');
	await field.press('Tab');
	await expect(question(page, 'How many hours do you sleep?')).toBeVisible();
	await expect(saveState(page)).toHaveText(/All changes saved/);
	expect(await axe(page)).toEqual([]);

	// Undo/redo go through the API, one transaction at a time.
	const undo = page.getByRole('banner').getByRole('button', { name: 'Undo', exact: true });
	const redo = page.getByRole('banner').getByRole('button', { name: 'Redo', exact: true });
	await undo.click();
	await expect(question(page, 'New question')).toBeVisible();
	await expect(field).toHaveValue('New question');
	await undo.click();
	await expect(question(page, 'New question')).toHaveCount(0);
	await redo.click();
	await expect(question(page, 'New question')).toBeVisible();
	await page.keyboard.press('ControlOrMeta+Shift+z');
	await expect(question(page, 'How many hours do you sleep?')).toBeVisible();
	await expect(saveState(page)).toHaveText(/All changes saved/);

	// Reload: the server has it.
	await page.reload();
	await expect(question(page, 'How many hours do you sleep?')).toBeVisible();
	await expect(page.getByRole('banner').getByRole('heading', { level: 1 })).toHaveText(title);

	// And the survey is in the list.
	await page.goto('/');
	await expect(page.getByRole('link', { name: title })).toBeVisible();
});

test('add question button on the canvas, and a 409 is replayed onto the newer revision', async ({
	page
}) => {
	await signIn(page);
	await createSurvey(page, `Conflict ${Date.now()}`);
	const surveyId = page.url().split('/').pop()!;

	await page.getByRole('button', { name: /Add question to/ }).first().click();
	await expect(question(page, 'New question')).toHaveAttribute('aria-selected', 'true');

	// Someone else edits the same draft (same account, another client).
	const csrf = (await page.context().cookies()).find((c) => c.name === '__Host-osp_csrf')!.value;
	const detail = await (await page.request.get(`/api/surveys/${surveyId}`)).json();
	const other = await page.request.post(`/api/surveys/${surveyId}/ops`, {
		headers: { 'X-CSRF-Token': csrf },
		data: {
			baseRevision: detail.revision,
			ops: [{ op: 'set_property', params: { target: 'p1', property: 'title', value: { en: 'Elsewhere' } } }]
		}
	});
	expect(other.status()).toBe(200);

	// Our stale edit gets a 409, refetches and replays: both changes land.
	const field = page.getByLabel('Question text');
	await field.fill('Replayed');
	await field.press('Tab');
	await expect(question(page, 'Replayed')).toBeVisible();
	await expect(tree(page).getByRole('treeitem', { name: 'Elsewhere' })).toBeVisible();
	await expect(saveState(page)).toHaveText(/All changes saved/);
	await expect(page.getByTestId('conflict-banner')).toHaveCount(0);
});

test('signed-out users are sent to sign in, and come back afterwards', async ({ page }) => {
	await page.goto('/surveys/does-not-exist');
	await expect(page).toHaveURL(/\/login\?next=%2Fsurveys%2Fdoes-not-exist/);
	await page.getByLabel('Email').fill(EMAIL);
	await page.getByLabel('Password').fill('wrong password, definitely');
	await page.getByRole('button', { name: 'Sign in' }).click();
	await expect(page.getByRole('alert')).toHaveText(/Sign-in failed/);
	await page.getByLabel('Password').fill(PASSWORD);
	await page.getByRole('button', { name: 'Sign in' }).click();
	await expect(page).toHaveURL(/\/surveys\/does-not-exist$/);
	await expect(page.getByRole('heading', { name: 'Could not open this survey' })).toBeVisible();
});
