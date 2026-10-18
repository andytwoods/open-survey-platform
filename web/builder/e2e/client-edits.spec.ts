import { expect, test, type Page, type Route } from '@playwright/test';
import { fillRich, pickQuestionType, saveStatus, signIn, writeHeaders } from './fixtures';

// Edits in the browser (task CE5, planning/client-edits.md): the builder applies every op
// with @osp/ops at once and saves the document with PUT /api/surveys/{id}/draft; undo and
// redo are local; Preview compiles in the browser. Against the real osp-api (api_server.py).

const tree = (page: Page) => page.getByRole('tree', { name: 'Survey outline' });
const question = (page: Page, name: string) => tree(page).getByRole('treeitem', { name, exact: true });
const toasts = (page: Page) => page.getByRole('region', { name: 'Notifications' });

async function createSurvey(page: Page, title: string): Promise<string> {
	await signIn(page);
	const r = await page.request.post('/api/surveys', { headers: await writeHeaders(page), data: { title } });
	expect(r.status()).toBe(201);
	const { id } = await r.json();
	return id as string;
}

async function open(page: Page, id: string) {
	await page.goto(`/surveys/${id}`);
	await expect(tree(page)).toBeVisible();
	await expect(saveStatus(page)).toHaveAttribute('data-state', 'saved');
}

async function addQuestion(page: Page) {
	await page.getByRole('button', { name: /Add question to/ }).first().click();
	await pickQuestionType(page);
}

const draftOf = async (page: Page, id: string) => (await page.request.get(`/api/surveys/${id}`)).json();

/** Hold every PUT /draft until `release()`; counts them. */
async function holdSaves(page: Page) {
	const held: Route[] = [];
	let release = () => {};
	const gate = new Promise<void>((r) => (release = r));
	await page.route('**/api/surveys/*/draft', async (route) => {
		held.push(route);
		await gate;
		await route.continue();
	});
	return { held, release };
}

test('an edit shows at once while its save is held back, then lands', async ({ page }) => {
	const id = await createSurvey(page, `Instant ${Date.now()}`);
	await open(page, id);
	const { held, release } = await holdSaves(page);

	await addQuestion(page);
	await expect(question(page, 'New question')).toBeVisible();
	await expect(question(page, 'New question')).toHaveAttribute('aria-selected', 'true');
	await expect(saveStatus(page)).toHaveAttribute('data-state', 'saving');
	await expect.poll(() => held.length).toBe(1);
	expect((await draftOf(page, id)).revision).toBe(0); // nothing saved yet

	// Rename it too, while the first save is still held: shown at once as well.
	await fillRich(page, page.getByLabel('Question text'), 'Held back');
	await page.keyboard.press('Tab');
	await expect(question(page, 'Held back')).toBeVisible();

	release();
	await expect(saveStatus(page)).toHaveAttribute('data-state', 'saved');
	expect(held.map((r) => r.request().method())).toEqual(['PUT', 'PUT']);
	const body = held[0]!.request().postDataJSON();
	expect(body).toMatchObject({ baseRevision: 0, ops: [{ op: 'add_question' }], transactionId: expect.any(String) });
	expect(Array.isArray(body.patch) && body.patch.length).toBeTruthy();
	const saved = await draftOf(page, id);
	expect(saved.revision).toBe(2);
	expect(JSON.stringify(saved.survey)).toContain('Held back');
	// The edit flow no longer calls the server's ops endpoints.
	const history = await (await page.request.get(`/api/surveys/${id}/history`)).json();
	expect(history.map((h: { ops: string[] }) => h.ops)).toEqual([['add_question'], ['set_property']]);
});

test('offline: edits are shown and queued, and sent when the network is back', async ({ page }) => {
	const id = await createSurvey(page, `Offline ${Date.now()}`);
	await open(page, id);
	let down = true;
	let tries = 0;
	await page.route('**/api/surveys/*/draft', (route) => {
		tries++;
		return down ? route.abort('internetdisconnected') : route.continue();
	});
	await addQuestion(page);
	await expect(question(page, 'New question')).toBeVisible();
	await expect(saveStatus(page)).toHaveAttribute('data-state', 'offline');
	await addQuestion(page); // still editable while offline
	await expect(tree(page).getByRole('treeitem', { name: 'New question', exact: true })).toHaveCount(2);
	expect((await draftOf(page, id)).revision).toBe(0);

	down = false;
	await expect(saveStatus(page)).toHaveAttribute('data-state', 'saved', { timeout: 20_000 });
	expect(tries).toBeGreaterThanOrEqual(3);
	await page.reload();
	await expect(tree(page).getByRole('treeitem', { name: 'New question', exact: true })).toHaveCount(2);
});

test('a 409 from a second tab: the edit is rebased onto the other tab’s save', async ({ page, context }) => {
	const id = await createSurvey(page, `Two tabs ${Date.now()}`);
	await open(page, id);
	const other = await context.newPage();
	await open(other, id);

	await addQuestion(other);
	await expect(saveStatus(other)).toHaveAttribute('data-state', 'saved');
	expect((await draftOf(page, id)).revision).toBe(1);

	// This tab still has revision 0: its save is refused (409), refetched, rebased, saved.
	const answers: number[] = [];
	page.on('response', (r) => {
		if (r.url().endsWith('/draft')) answers.push(r.status());
	});
	await addQuestion(page);
	await expect(saveStatus(page)).toHaveAttribute('data-state', 'saved');
	expect(answers).toEqual([409, 200]);
	await expect(tree(page).getByRole('treeitem', { name: 'New question', exact: true })).toHaveCount(2);
	await expect(page.getByTestId('conflict-banner')).toHaveCount(0);
	expect((await draftOf(page, id)).revision).toBe(2);
	await other.reload();
	await expect(tree(other).getByRole('treeitem', { name: 'New question', exact: true })).toHaveCount(2);
});

test('a 409 whose rebase no longer applies shows the conflict banner and the latest draft', async ({ page }) => {
	const id = await createSurvey(page, `Conflict ${Date.now()}`);
	await open(page, id);
	await addQuestion(page);
	await expect(saveStatus(page)).toHaveAttribute('data-state', 'saved');

	// Another client deletes the question; this tab, not knowing, renames it.
	const draft = await draftOf(page, id);
	const qid = draft.survey.blocks[0].pages[0].items.at(-1).id as string;
	const del = await page.request.post(`/api/surveys/${id}/ops`, {
		headers: await writeHeaders(page),
		data: { baseRevision: draft.revision, ops: [{ op: 'delete_question', params: { id: qid } }] }
	});
	expect(del.status()).toBe(200);

	await fillRich(page, page.getByLabel('Question text'), 'Renamed here');
	await page.keyboard.press('Tab');
	await expect(page.getByTestId('conflict-banner')).toContainText('changed elsewhere');
	await expect(question(page, 'Renamed here')).toHaveCount(0);
	await expect(question(page, 'New question')).toHaveCount(0); // the latest draft
	await page.getByTestId('conflict-banner').getByRole('button', { name: 'Dismiss' }).click();
	await expect(saveStatus(page)).toHaveAttribute('data-state', 'saved');
	expect((await draftOf(page, id)).revision).toBe(draft.revision + 1);
});

test('a 422 from the server rolls the edit back and shows why', async ({ page }) => {
	const id = await createSurvey(page, `Refused ${Date.now()}`);
	await open(page, id);
	let refused = false;
	await page.route('**/api/surveys/*/draft', (route) => {
		if (refused) return route.continue();
		refused = true;
		return route.fulfill({
			status: 422,
			json: {
				code: 'rejected',
				message: 'The survey would hold text the model refuses.',
				diagnostics: [{ severity: 'error', code: 'op.invalid_text', message: 'the edit would add: a refused link', pointer: '' }],
				failedIndex: null
			}
		});
	});
	await addQuestion(page);
	await expect(toasts(page)).toContainText('The survey would hold text the model refuses. the edit would add: a refused link');
	await expect(question(page, 'New question')).toHaveCount(0);
	await expect(saveStatus(page)).toHaveAttribute('data-state', 'saved');
	await page.getByRole('banner').getByRole('button', { name: 'Undo', exact: true }).click();
	await expect(toasts(page)).toContainText(/nothing to undo/i);
	expect((await draftOf(page, id)).revision).toBe(0);

	// The next edit goes through.
	await addQuestion(page);
	await expect(question(page, 'New question')).toBeVisible();
	await expect(saveStatus(page)).toHaveAttribute('data-state', 'saved');
	expect((await draftOf(page, id)).revision).toBe(1);
});

test('undo and redo are local and saved; the history starts again on each page load', async ({ page }) => {
	const id = await createSurvey(page, `Undo ${Date.now()}`);
	await open(page, id);
	const undo = page.getByRole('banner').getByRole('button', { name: 'Undo', exact: true });
	const redo = page.getByRole('banner').getByRole('button', { name: 'Redo', exact: true });
	const calls: string[] = [];
	page.on('request', (r) => {
		const path = new URL(r.url()).pathname;
		if (/\/(ops|undo|redo|draft)$/.test(path)) calls.push(`${r.method()} ${path.split('/').pop()}`);
	});

	await addQuestion(page);
	await expect(saveStatus(page)).toHaveAttribute('data-state', 'saved');
	await undo.click();
	await expect(question(page, 'New question')).toHaveCount(0);
	await expect(saveStatus(page)).toHaveAttribute('data-state', 'saved');
	expect((await draftOf(page, id)).revision).toBe(2);
	await redo.click();
	await expect(question(page, 'New question')).toBeVisible();
	await expect(saveStatus(page)).toHaveAttribute('data-state', 'saved');
	expect(calls).toEqual(['PUT draft', 'PUT draft', 'PUT draft']);

	await page.reload();
	await expect(question(page, 'New question')).toBeVisible();
	await undo.click();
	await expect(toasts(page)).toContainText(/nothing to undo/i);
	await redo.click();
	await expect(toasts(page)).toContainText(/nothing to redo/i);
	await expect(question(page, 'New question')).toBeVisible();
	expect((await draftOf(page, id)).revision).toBe(3);
});
