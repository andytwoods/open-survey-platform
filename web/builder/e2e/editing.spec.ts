import { expect, test, type Page } from '@playwright/test';
import { axe, fillRich, pickQuestionType, runFromPalette, signIn, writeHeaders } from './fixtures';

// End to end against a real osp-api on SQLite (e2e/api_server.py, started by the
// Playwright config): create a survey, edit through ops, undo/redo, reload. Sign-in is the
// host's (fixtures.ts signs in through the API); the pages have no sign-in UI.


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
	await runFromPalette(page, 'add question', /^Add question…/);
	await pickQuestionType(page);
}

test('create, add, rename, undo, redo, reload', async ({ page }) => {
	await signIn(page);
	await expect(page.getByTestId('display-name')).toHaveText('Dev researcher');
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
	await expect(field).toHaveText('New question');
	await fillRich(page, field, 'How many hours do you sleep?');
	await page.keyboard.press('Tab');
	await expect(question(page, 'How many hours do you sleep?')).toBeVisible();
	await expect(saveState(page)).toHaveText(/All changes saved/);
	expect(await axe(page)).toEqual([]);

	// Undo/redo go through the API, one transaction at a time.
	const undo = page.getByRole('banner').getByRole('button', { name: 'Undo', exact: true });
	const redo = page.getByRole('banner').getByRole('button', { name: 'Redo', exact: true });
	await undo.click();
	await expect(question(page, 'New question')).toBeVisible();
	await expect(field).toHaveText('New question');
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
	await pickQuestionType(page);
	await expect(question(page, 'New question')).toHaveAttribute('aria-selected', 'true');

	// Someone else edits the same draft (same account, another client).
	const detail = await (await page.request.get(`/api/surveys/${surveyId}`)).json();
	const other = await page.request.post(`/api/surveys/${surveyId}/ops`, {
		headers: await writeHeaders(page),
		data: {
			baseRevision: detail.revision,
			ops: [{ op: 'set_property', params: { target: 'p1', property: 'title', value: { en: 'Elsewhere' } } }]
		}
	});
	expect(other.status()).toBe(200);

	// Our stale edit gets a 409, refetches and replays: both changes land.
	const field = page.getByLabel('Question text');
	await fillRich(page, field, 'Replayed');
	await page.keyboard.press('Tab');
	await expect(question(page, 'Replayed')).toBeVisible();
	await expect(tree(page).getByRole('treeitem', { name: 'Elsewhere' })).toBeVisible();
	await expect(saveState(page)).toHaveText(/All changes saved/);
	await expect(page.getByTestId('conflict-banner')).toHaveCount(0);
});

test('when the host session ends: one reload, then the session-ended banner; back, the page works', async ({
	page
}) => {
	let loads = 0;
	page.on('load', () => loads++);
	// The Dev identity never answers 401, so the ended host session is simulated.
	await page.route('**/api/**', (route) => route.fulfill({ status: 401, json: { code: 'auth', message: 'Sign in first.' } }));
	await page.goto('/surveys/does-not-exist');
	// The dev config says "reload": the page reloads once (the host's login would run), then
	// shows the banner instead of reloading again.
	await expect(page.getByTestId('session-ended')).toBeVisible();
	await expect(page.getByTestId('session-ended')).toContainText('Your session ended');
	await page.waitForTimeout(1500);
	expect(loads).toBe(2);
	await expect(page).toHaveURL(/\/surveys\/does-not-exist$/);

	await page.unrouteAll();
	await page.getByRole('button', { name: 'Reload to sign in' }).click();
	await expect(page.getByRole('heading', { name: 'Could not open this survey' })).toBeVisible();
	await expect(page.getByTestId('session-ended')).toHaveCount(0);
});
