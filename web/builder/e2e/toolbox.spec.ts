import { expect, test, type Page } from '@playwright/test';
import { axe, focused, signIn, writeHeaders } from './fixtures';

// The question-type toolbox under the outline (task B16), end to end against a real
// osp-api on SQLite: a click adds to the selected (or last) page; a drag onto the outline
// inserts between questions or at a page's end (add_question with an index); Escape
// cancels a drag; Shift+Enter is the keyboard way to choose where; axe; 320 px.

const banner = (page: Page) => page.getByRole('banner');
const saved = (page: Page) => banner(page).getByRole('status').first();
const tree = (page: Page) => page.getByRole('tree', { name: 'Survey outline' });
const item = (page: Page, name: string) => tree(page).getByRole('treeitem', { name, exact: true });
const toolType = (page: Page, name: string) => page.getByRole('button', { name: `Add ${name} question`, exact: true });

/** Each page's questions (label/type) from the API: what the server stored. */
async function pagesOf(page: Page): Promise<string[][]> {
	const id = page.url().split('/').pop()!;
	const d = await (await page.request.get(`/api/surveys/${id}`)).json();
	return d.survey.blocks.flatMap((b: { pages: { items: { id: string; type: string }[] }[] }) =>
		b.pages.map((p) => p.items.map((q) => (q.id.startsWith('q_') ? q.id : q.type)))
	);
}

/** A survey with two pages: page one holds q_a, q_b (after the starter question), p_two q_c. */
async function seededSurvey(page: Page, title: string) {
	await signIn(page);
	await page.getByLabel('New survey title').fill(title);
	await page.getByRole('button', { name: 'Create survey' }).click();
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	const surveyId = page.url().split('/').pop()!;
	const detail = await (await page.request.get(`/api/surveys/${surveyId}`)).json();
	const block = detail.survey.blocks[0];
	const p1 = block.pages[0].id;
	const r = await page.request.post(`/api/surveys/${surveyId}/ops`, {
		headers: await writeHeaders(page),
		data: {
			baseRevision: detail.revision,
			ops: [
				{ op: 'add_question', params: { page: p1, id: 'q_a', label: 'Alpha' } },
				{ op: 'add_question', params: { page: p1, id: 'q_b', label: 'Bravo' } },
				{ op: 'add_page', params: { block: block.id, id: 'p_two' } },
				{ op: 'add_question', params: { page: 'p_two', id: 'q_c', label: 'Charlie' } }
			]
		}
	});
	expect(r.status()).toBe(200);
	await page.reload();
	await page.waitForLoadState('load');
	// The canvas shows at every width (the outline may be an overlay).
	await expect(page.getByRole('button', { name: /Add question to/ }).first()).toBeVisible();
}

/** Drag a toolbox type to (x, y) with a real mouse, checking the indicator, then drop. */
async function dragType(page: Page, name: string, to: { x: number; y: number }, indicator?: { row: string; edge: string }) {
	const from = (await toolType(page, name).boundingBox())!;
	await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
	await page.mouse.down();
	await page.mouse.move(from.x + from.width / 2 + 10, from.y + from.height / 2 - 10, { steps: 3 });
	await page.mouse.move(to.x, to.y, { steps: 8 });
	if (indicator) await expect(item(page, indicator.row)).toHaveAttribute('data-drop', indicator.edge);
}

test('a click adds the type to the selected page, else the last page', async ({ page }) => {
	await seededSurvey(page, `Toolbox click ${Date.now()}`);
	await expect(page.getByRole('toolbar', { name: 'Add a question of type' })).toBeVisible();
	expect(await axe(page)).toEqual([]);

	// Alpha selected (page one): the slider goes at page one's end.
	await item(page, 'Alpha').click();
	await toolType(page, 'Slider').click();
	await expect(page.getByTestId('question-type')).toHaveText('Slider');
	await expect(focused(page)).toHaveAccessibleName('Question text');
	await expect(saved(page)).toHaveText(/All changes saved/);
	let pages = await pagesOf(page);
	expect(pages[0].slice(-3)).toEqual(['q_a', 'q_b', 'slider']);

	// The second page selected: there.
	await item(page, 'p_two').click();
	await toolType(page, 'Note').click();
	await expect(saved(page)).toHaveText(/All changes saved/);
	pages = await pagesOf(page);
	expect(pages[1].at(-1)).toBe('note');

	// Nothing selected: the last page.
	await page.getByRole('main', { name: 'Canvas' }).click({ position: { x: 5, y: 5 } });
	await page.keyboard.press('Escape');
	await toolType(page, 'Date').click();
	await expect(saved(page)).toHaveText(/All changes saved/);
	pages = await pagesOf(page);
	expect(pages[1].slice(-2)).toEqual(['note', 'date']);
});

test('dragging a type onto the outline inserts it there; Escape cancels', async ({ page }) => {
	await seededSurvey(page, `Toolbox drag ${Date.now()}`);

	// Into the gap between Alpha and Bravo (the top half of Bravo).
	const bravo = (await item(page, 'Bravo').boundingBox())!;
	await dragType(page, 'Grid', { x: bravo.x + 40, y: bravo.y + 3 }, { row: 'Bravo', edge: 'before' });
	await page.mouse.up();
	await expect(page.getByTestId('question-type')).toHaveText('Grid');
	await expect(saved(page)).toHaveText(/All changes saved/);
	let pages = await pagesOf(page);
	expect(pages[0].slice(-3)).toEqual(['q_a', 'matrix', 'q_b']);

	// Onto the second page's row: at its end.
	const second = (await item(page, 'p_two').boundingBox())!;
	await dragType(page, 'Whole number', { x: second.x + 40, y: second.y + second.height / 2 }, { row: 'p_two', edge: 'into' });
	await page.mouse.up();
	await expect(saved(page)).toHaveText(/All changes saved/);
	pages = await pagesOf(page);
	expect(pages[1].slice(-2)).toEqual(['q_c', 'integer']);

	// Escape mid-drag: nothing added, no indicator left behind.
	const alpha = (await item(page, 'Alpha').boundingBox())!;
	await dragType(page, 'Text', { x: alpha.x + 40, y: alpha.y + alpha.height - 3 }, { row: 'Alpha', edge: 'after' });
	await page.keyboard.press('Escape');
	await expect(tree(page).locator('[data-drop]')).toHaveCount(0);
	await page.mouse.up();
	// Let go away from the outline and the canvas (over the properties pane): nothing either.
	const props = (await page.locator('#pane-properties').boundingBox())!;
	await dragType(page, 'Text', { x: props.x + props.width / 2, y: props.y + props.height / 2 });
	await page.mouse.up();
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect(await pagesOf(page)).toEqual(pages);
});

test('keyboard: arrows through the types, Shift+Enter chooses the page and position', async ({ page }) => {
	await seededSurvey(page, `Toolbox keys ${Date.now()}`);
	await item(page, 'Alpha').click();

	// One Tab stop; arrows move along it.
	const first = toolType(page, 'Text');
	await first.focus();
	await page.keyboard.press('ArrowDown');
	await expect(toolType(page, 'Whole number')).toBeFocused();
	await page.keyboard.press('Shift+Enter');
	const dialog = page.getByRole('dialog', { name: 'Add Whole number question at…' });
	await expect(dialog).toBeVisible();
	// Starts on the selected question's page, just after it.
	await expect(dialog.getByLabel('Position')).toHaveValue(/\d+/);
	expect(await axe(page)).toEqual([]);
	await page.keyboard.press('Escape');
	await expect(dialog).toBeHidden();
	await expect(toolType(page, 'Whole number')).toBeFocused();

	await page.keyboard.press('Shift+Enter');
	await expect(dialog).toBeVisible();
	await dialog.getByLabel('Position').selectOption({ label: 'After Alpha' });
	await dialog.getByRole('button', { name: 'Add', exact: true }).click();
	await expect(dialog).toBeHidden();
	await expect(page.getByTestId('question-type')).toHaveText('Whole number');
	await expect(saved(page)).toHaveText(/All changes saved/);
	let pages = await pagesOf(page);
	expect(pages[0].slice(-3)).toEqual(['q_a', 'integer', 'q_b']);

	// Another page, at the start.
	await toolType(page, 'Whole number').focus();
	await page.keyboard.press('ArrowDown');
	await page.keyboard.press('Shift+Enter');
	const dec = page.getByRole('dialog', { name: 'Add Decimal number question at…' });
	await dec.getByLabel('Page').selectOption({ index: 1 });
	await dec.getByLabel('Position').selectOption({ label: 'At the start' });
	await dec.getByRole('button', { name: 'Add', exact: true }).press('Enter');
	await expect(dec).toBeHidden();
	await expect(saved(page)).toHaveText(/All changes saved/);
	pages = await pagesOf(page);
	expect(pages[1][0]).toBe('decimal');
});

test('320 px: the toolbox starts folded in the outline overlay, unfolds, fits', async ({ page }) => {
	await page.setViewportSize({ width: 320, height: 640 });
	await seededSurvey(page, `Toolbox narrow ${Date.now()}`);
	// The outline is an overlay here, opened from the top bar.
	await banner(page).getByRole('button', { name: 'Outline pane' }).click();
	await expect(item(page, 'Bravo')).toBeVisible();
	const toggle = page.getByRole('button', { name: 'Question types' });
	await expect(toggle).toHaveAttribute('aria-expanded', 'false');
	await expect(toolType(page, 'Text')).toBeHidden();
	await toggle.click();
	await expect(toolType(page, 'Text')).toBeVisible();
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
	for (const b of await page.getByRole('toolbar', { name: 'Add a question of type' }).getByRole('button').all()) {
		const box = (await b.boundingBox())!;
		expect(box.height, await b.getAttribute('aria-label') ?? '').toBeGreaterThanOrEqual(44);
		expect(box.x + box.width).toBeLessThanOrEqual(320);
	}
	// Here a tap picks the type up and the canvas asks where (B19's tap-to-place).
	await toolType(page, 'Single choice').click();
	await page.getByRole('button', { name: 'Place here at the end of p_two, after Charlie', exact: true }).click();
	await expect(page.getByTestId('question-type')).toHaveText('Single choice');
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect((await pagesOf(page))[1].at(-1)).toBe('single');
});
