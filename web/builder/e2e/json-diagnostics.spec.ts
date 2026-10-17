import { expect, test, type Page } from '@playwright/test';
import { axe, signIn, writeHeaders } from './fixtures';

// JSON view (B9) and diagnostics strip + export badges (B10), against a real osp-api on
// SQLite (e2e/api_server.py, started by the Playwright config).

type Survey = { blocks: { pages: { items: unknown[] }[] }[]; [k: string]: unknown };

async function signInAndCreate(page: Page, title: string): Promise<string> {
	await signIn(page);
	await page.getByLabel('New survey title').fill(title);
	await page.getByRole('button', { name: 'Create survey' }).click();
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	await expect(page.getByRole('tree', { name: 'Survey outline' })).toBeVisible();
	return page.url().split('/').pop()!;
}

async function draft(page: Page, id: string): Promise<{ revision: number; survey: Survey }> {
	return (await page.request.get(`/api/surveys/${id}`)).json();
}

const QUESTION = {
	type: 'single',
	id: 'fav',
	label: { en: 'Favourite colour' },
	choices: [
		{ value: 'r', label: { en: 'Red' } },
		{ value: 'g', label: { en: 'Green' } }
	],
	choiceOrder: 'shuffle'
};

const editor = (page: Page) => page.getByRole('textbox', { name: 'Survey JSON' });
const tree = (page: Page) => page.getByRole('tree', { name: 'Survey outline' });

async function replaceEditorText(page: Page, text: string) {
	await editor(page).click();
	await page.keyboard.press('ControlOrMeta+a');
	await page.keyboard.insertText(text);
}

test('JSON view: invalid JSON and rejected surveys never change the draft; Apply, undo, redo', async ({
	page
}) => {
	const id = await signInAndCreate(page, `JSON ${Date.now()}`);
	const start = await draft(page, id);

	await page.getByRole('tab', { name: 'JSON' }).click();
	await expect(editor(page)).toContainText('"blocks"');
	await expect(page.getByTestId('json-state')).toHaveText(/Revision 0/);
	expect(await axe(page)).toEqual([]);

	// Invalid JSON: refused locally with its position, nothing sent.
	await replaceEditorText(page, '{\n  "metadata": \n');
	await expect(page.getByTestId('json-state')).toHaveText('Unapplied edits');
	await page.getByRole('button', { name: 'Apply', exact: true }).click();
	await expect(page.getByTestId('json-syntax-error')).toContainText('Invalid JSON');
	await expect(page.getByTestId('json-syntax-error')).toContainText('line 3');
	expect(await draft(page, id)).toEqual(start);
	expect(await axe(page)).toEqual([]);

	// Valid JSON the server rejects (422): diagnostics inline, draft untouched.
	await replaceEditorText(page, JSON.stringify({ ...start.survey, specVersion: 'nope' }, null, 2));
	await page.getByRole('button', { name: 'Apply', exact: true }).click();
	const diags = page.getByTestId('json-diagnostics');
	await expect(diags).toBeVisible();
	await expect(diags.getByRole('button', { name: /Line \d+, column \d+/ }).first()).toBeVisible();
	await expect(page.getByTestId('json-message')).toHaveText(/Not applied.*unchanged/);
	expect((await draft(page, id)).revision).toBe(0);
	expect(await axe(page)).toEqual([]);

	// Revert discards local edits.
	await page.getByRole('button', { name: 'Revert' }).click();
	await expect(page.getByTestId('json-state')).toHaveText(/Revision 0/);
	await expect(diags).toHaveCount(0);

	// A valid Apply: one replace_survey, one undo step.
	const next = structuredClone(start.survey);
	next.blocks[0].pages[0].items.push(QUESTION);
	await replaceEditorText(page, JSON.stringify(next, null, 2));
	await page.getByRole('button', { name: 'Apply', exact: true }).click();
	await expect(page.getByTestId('json-message')).toHaveText('Applied.');
	await expect(page.getByTestId('json-state')).toHaveText(/Revision 1/);
	await expect(tree(page).getByRole('treeitem', { name: 'Favourite colour' })).toBeVisible();
	expect((await draft(page, id)).survey.blocks[0].pages[0].items).toHaveLength(next.blocks[0].pages[0].items.length);

	const undo = page.getByRole('banner').getByRole('button', { name: 'Undo', exact: true });
	const redo = page.getByRole('banner').getByRole('button', { name: 'Redo', exact: true });
	await undo.click();
	await expect(tree(page).getByRole('treeitem', { name: 'Favourite colour' })).toHaveCount(0);
	await expect(editor(page)).not.toContainText('Favourite colour');
	await redo.click();
	await expect(tree(page).getByRole('treeitem', { name: 'Favourite colour' })).toBeVisible();
	await expect(editor(page)).toContainText('Favourite colour');
});

test('JSON view warns when the survey changed on the server while editing', async ({ page }) => {
	const id = await signInAndCreate(page, `Stale ${Date.now()}`);
	await page.getByRole('tab', { name: 'JSON' }).click();
	const start = await draft(page, id);
	await replaceEditorText(page, JSON.stringify({ ...start.survey, version: 7 }, null, 2));

	// Someone else edits; a later edit here makes the store pick up the new revision.
	const other = await page.request.post(`/api/surveys/${id}/ops`, {
		headers: await writeHeaders(page),
		data: {
			baseRevision: 0,
			ops: [{ op: 'set_property', params: { target: 'p1', property: 'title', value: { en: 'Elsewhere' } } }]
		}
	});
	expect(other.status()).toBe(200);
	await page.getByRole('tab', { name: 'Canvas' }).click();
	await page.getByRole('button', { name: /Add question to/ }).first().click();
	await expect(tree(page).getByRole('treeitem', { name: 'Elsewhere' })).toBeVisible();

	await page.getByRole('tab', { name: 'JSON' }).click();
	await expect(page.getByTestId('json-stale')).toContainText('changed on the server');
	await page.getByRole('button', { name: 'Apply', exact: true }).click();
	await expect(page.getByTestId('json-message')).toHaveText(/changed on the server/);
	expect((await draft(page, id)).survey.version).toBeUndefined();
	await page.getByRole('button', { name: 'Discard my edits and show the latest' }).click();
	await expect(page.getByTestId('json-stale')).toHaveCount(0);
	await expect(editor(page)).toContainText('Elsewhere');
});

test('export target picker shows badges; clicking a diagnostic focuses its field', async ({ page }) => {
	const id = await signInAndCreate(page, `Badges ${Date.now()}`);
	const start = await draft(page, id);
	const survey = structuredClone(start.survey);
	survey.blocks[0].pages[0].items.push(QUESTION);
	survey.version = 2; // unsupported in LimeSurvey
	survey.settings = { ...((survey.settings as object) ?? {}), backNavigation: false }; // unsupported in XLSForm
	const r = await page.request.post(`/api/surveys/${id}/ops`, {
		headers: await writeHeaders(page),
		data: { baseRevision: 0, ops: [{ op: 'replace_survey', params: { survey } }] }
	});
	expect(r.status()).toBe(200);
	await page.reload();
	await expect(tree(page).getByRole('treeitem', { name: 'Favourite colour' })).toBeVisible();

	const strip = page.getByTestId('diagnostics-strip');
	await expect(strip.getByTestId('count-export')).toHaveCount(0);
	await expect(page.locator('[data-export-badge]')).toHaveCount(0);

	// LimeSurvey: shuffled choices are approximated (badge on the card), version unsupported.
	await strip.getByRole('combobox', { name: /Export target/ }).click();
	await page.getByRole('option', { name: 'LimeSurvey' }).click();
	const badges = page.locator('[data-export-badges="fav"]');
	await expect(badges.getByRole('button', { name: 'Approximated in LimeSurvey' })).toBeVisible();
	await expect(strip.getByTestId('count-export')).toHaveText(/[1-9]\d* export issues?/);
	await expect(page.getByTestId('announcer')).toContainText(/Diagnostics: .*export issue.*LimeSurvey/);

	await strip.getByRole('button', { name: /^Diagnostics/ }).click();
	await expect(strip.getByRole('button', { name: /Unsupported Survey · version/ })).toBeVisible();
	expect(await axe(page)).toEqual([]);

	// The badge goes to the property it is about.
	await badges.getByRole('button', { name: 'Approximated in LimeSurvey' }).click();
	await expect(page.locator('#pane-properties :focus')).toHaveAttribute('id', /choiceOrder$/);

	// XLSForm: back navigation off is unsupported; its item focuses the survey's field.
	await strip.getByRole('combobox', { name: /Export target/ }).click();
	await page.getByRole('option', { name: 'XLSForm' }).click();
	const item = strip.getByRole('button', { name: /Unsupported Survey · settings\.backNavigation/ });
	await expect(item).toBeVisible();
	await expect(badges).toHaveCount(0);
	await item.click();
	await expect(page.locator('#pane-properties :focus')).toHaveAttribute('id', /settings-backNavigation$/);

	// None: no badges, no export count.
	await strip.getByRole('combobox', { name: /Export target/ }).click();
	await page.getByRole('option', { name: 'None' }).click();
	await expect(page.locator('[data-export-badge]')).toHaveCount(0);
	await expect(strip.getByTestId('count-export')).toHaveCount(0);
	expect(await axe(page)).toEqual([]);
});
