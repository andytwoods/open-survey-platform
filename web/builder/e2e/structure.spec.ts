import { expect, test, type Page } from '@playwright/test';
import { axe, runFromPalette, signIn, writeHeaders } from './fixtures';

// Pages and blocks in the builder (task B20), end to end against a real osp-api: "Add
// page" under each page on the canvas and in the outline, "Add block" in the outline and
// the Flow view, the page/block context menu (rename, duplicate, delete) by mouse and by
// keyboard, the reference warning on delete (Keep / Delete anyway), palette commands,
// undo, axe, 320 px.

const banner = (page: Page) => page.getByRole('banner');
const saved = (page: Page) => banner(page).getByRole('status').first();
const tree = (page: Page) => page.getByRole('tree', { name: 'Survey outline' });
const item = (page: Page, name: string) => tree(page).getByRole('treeitem', { name, exact: true });
const menu = (page: Page) => page.getByRole('menu');
const titleField = (page: Page) => page.getByRole('complementary', { name: 'Properties' }).getByRole('textbox', { name: 'Title', exact: true });
const undoButton = (page: Page) => banner(page).getByRole('button', { name: 'Undo', exact: true });

type Survey = {
	blocks: { id: string; title?: string; pages: { id: string; title?: unknown; items: { id: string }[] }[] }[];
	flow: { type: string; id: string; block?: string }[];
};

async function stored(page: Page): Promise<Survey> {
	const id = page.url().split('/')[4];
	return (await (await page.request.get(`/api/surveys/${id}`)).json()).survey;
}
const pageIds = async (page: Page) => (await stored(page)).blocks.map((b) => b.pages.map((p) => p.id));
const blockIds = async (page: Page) => (await stored(page)).blocks.map((b) => b.id);
const flowBlocks = async (page: Page) => (await stored(page)).flow.filter((n) => n.type === 'block').map((n) => n.block);

/**
 * b1: p1 ("Start": intro, qa "Alpha"), p2 ("Second": qb, which pipes ${qa}).
 * b2 ("Later", in the flow): p3 (qc).
 */
async function seeded(page: Page) {
	await signIn(page);
	await page.getByLabel('New survey title').fill(`Structure ${Date.now()}`);
	await page.getByRole('button', { name: 'Create survey' }).click();
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	const id = page.url().split('/').pop()!;
	const detail = await (await page.request.get(`/api/surveys/${id}`)).json();
	const q = (qid: string, label: string) => ({ id: qid, type: 'text', label: { en: label } });
	const res = await page.request.post(`/api/surveys/${id}/ops`, {
		headers: await writeHeaders(page),
		data: {
			baseRevision: detail.revision,
			ops: [
				{ op: 'set_property', params: { target: 'p1', property: 'title', value: { en: 'Start' } } },
				{ op: 'add_question', params: { page: 'p1', question: q('qa', 'Alpha') } },
				{ op: 'add_page', params: { block: 'b1', page: { id: 'p2', title: { en: 'Second' }, items: [q('qb', 'Hello ${qa}')] } } },
				{ op: 'add_block', params: { block: { id: 'b2', title: 'Later', pages: [{ id: 'p3', items: [q('qc', 'Charlie')] }] } } },
				{ op: 'insert_flow_node', params: { node: { type: 'block', id: 'n2', block: 'b2' } } }
			]
		}
	});
	expect(res.status(), await res.text()).toBe(200);
	await page.reload();
	await expect(page.getByRole('button', { name: /Add question to/ }).first()).toBeVisible();
}

test('Add page under a page on the canvas: after it, selected, title focused; undo removes it', async ({ page }) => {
	await seeded(page);
	await page.getByRole('button', { name: 'Add page after Start' }).click();
	const title = titleField(page);
	await expect(title).toBeFocused();
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect(await pageIds(page)).toEqual([['p1', 'page1', 'p2'], ['p3']]);
	await expect(item(page, 'page1')).toHaveAttribute('aria-selected', 'true');
	// The title is rich text: fill() needs its editor, which may still be loading.
	await expect(title).toHaveAttribute('contenteditable', 'true');
	await title.fill('Middle');
	await expect(item(page, 'Middle')).toBeVisible();
	await expect(saved(page)).toHaveText(/All changes saved/);
	// Undo: the title, then the page.
	await undoButton(page).click();
	await expect(item(page, 'page1')).toBeVisible();
	await undoButton(page).click();
	await expect(item(page, 'page1')).toBeHidden();
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect(await pageIds(page)).toEqual([['p1', 'p2'], ['p3']]);
});

test('Add block from the outline: a block with one page, after the selected one, in the flow', async ({ page }) => {
	await seeded(page);
	await item(page, 'Start').click();
	await page.getByRole('group', { name: 'Pages and blocks' }).getByRole('button', { name: 'Add block' }).click();
	await expect(titleField(page)).toBeFocused();
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect(await blockIds(page)).toEqual(['b1', 'block1', 'b2']);
	expect(await flowBlocks(page)).toEqual(['b1', 'block1', 'b2']);
	const s = await stored(page);
	expect(s.blocks[1].pages).toHaveLength(1);
	await titleField(page).fill('Middle block');
	await expect(item(page, 'Middle block')).toBeVisible();
	expect(await axe(page)).toEqual([]);
	// The palette runs its command after it closes (a timer): wait for each undo to show.
	await runFromPalette(page, 'undo', /^Undo/);
	await expect(item(page, 'block1')).toBeVisible();
	await runFromPalette(page, 'undo', /^Undo/);
	await expect(item(page, 'block1')).toBeHidden();
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect(await flowBlocks(page)).toEqual(['b1', 'b2']);
});

test('keyboard only: context menu on an outline row renames and duplicates; palette adds and deletes', async ({ page }) => {
	await seeded(page);
	await item(page, 'Second').click();
	await page.keyboard.press('Shift+F10');
	await expect(menu(page)).toBeVisible();
	await expect(menu(page).getByRole('menuitem', { name: 'Add page after' })).toBeFocused();
	expect(await axe(page)).toEqual([]);
	await page.keyboard.press('ArrowDown');
	await expect(menu(page).getByRole('menuitem', { name: 'Rename…' })).toBeFocused();
	await page.keyboard.press('Enter');
	await expect(menu(page)).toBeHidden();
	const title = titleField(page);
	await expect(title).toBeFocused();
	// The rich-text title (RT3) loads its editor on focus: keys sent before it is editable are lost.
	await expect(title).toHaveAttribute('contenteditable', 'true');
	await page.keyboard.press('ControlOrMeta+a');
	await page.keyboard.type('Two');
	await expect(item(page, 'Two')).toBeVisible();

	// Back to the row; Escape closes the menu and returns focus there.
	await item(page, 'Two').focus();
	await page.keyboard.press('Shift+F10');
	await page.keyboard.press('Escape');
	await expect(menu(page)).toBeHidden();
	await expect(item(page, 'Two')).toBeFocused();

	// Duplicate: the copy follows the original and takes focus.
	await page.keyboard.press('Shift+F10');
	await page.keyboard.press('End');
	await expect(menu(page).getByRole('menuitem', { name: 'Delete…' })).toBeFocused();
	await page.keyboard.press('ArrowUp'); // past "Save to bank…" (QB5)
	await expect(menu(page).getByRole('menuitem', { name: 'Save to bank…' })).toBeFocused();
	await page.keyboard.press('ArrowUp');
	await expect(menu(page).getByRole('menuitem', { name: 'Duplicate' })).toBeFocused();
	await page.keyboard.press('Enter');
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect(await pageIds(page)).toEqual([['p1', 'p2', 'p2_copy'], ['p3']]);
	await expect(tree(page).locator('#outline-p2_copy')).toBeFocused();
	// The copy's question pipes the original's qa (outside the page): unchanged.
	const copy = (await stored(page)).blocks[0].pages[2];
	expect(copy.items.map((q) => q.id)).toEqual(['qb_copy']);

	// Palette: Add page (after the selected copy), then Delete… it.
	await runFromPalette(page, 'add page', /^Add page$/);
	await expect(titleField(page)).toBeFocused();
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect((await pageIds(page))[0]).toEqual(['p1', 'p2', 'p2_copy', 'page1']);
	await runFromPalette(page, 'delete', /^Delete…/);
	// The palette runs its command after it closes (a timer), so "All changes saved" can
	// still be the add's: wait for the row to go first.
	await expect(tree(page).locator('#outline-page1')).toHaveCount(0);
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect((await pageIds(page))[0]).toEqual(['p1', 'p2', 'p2_copy']);
});

test('deleting a page that piping refers to warns: Keep keeps it, Delete anyway deletes, undo restores', async ({ page }) => {
	await seeded(page);
	await item(page, 'Start').click({ button: 'right' });
	await menu(page).getByRole('menuitem', { name: 'Delete…' }).click();
	const dialog = page.getByRole('dialog', { name: 'Delete a page that is still used?' });
	await expect(dialog).toBeVisible();
	await expect(dialog.getByTestId('structure-delete-warning')).toContainText('Hello ${qa} (text)');
	expect(await axe(page)).toEqual([]);
	await dialog.getByRole('button', { name: 'Keep page' }).click();
	await expect(dialog).toBeHidden();
	expect((await pageIds(page))[0]).toEqual(['p1', 'p2']);

	await item(page, 'Start').click({ button: 'right' });
	await menu(page).getByRole('menuitem', { name: 'Delete…' }).click();
	await dialog.getByRole('button', { name: 'Delete anyway' }).click();
	await expect(item(page, 'Start')).toBeHidden();
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect((await pageIds(page))[0]).toEqual(['p2']);
	await undoButton(page).click();
	await expect(item(page, 'Start')).toBeVisible();
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect((await pageIds(page))[0]).toEqual(['p1', 'p2']);
});

test('a block: duplicate from the canvas heading menu (placed in the flow), delete with its flow node', async ({ page }) => {
	await seeded(page);
	await page.locator('#card-b2').click({ button: 'right' });
	await menu(page).getByRole('menuitem', { name: 'Duplicate' }).click();
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect(await blockIds(page)).toEqual(['b1', 'b2', 'b2_copy']);
	expect(await flowBlocks(page)).toEqual(['b1', 'b2', 'b2_copy']);
	await expect(item(page, 'Later (copy)')).toBeVisible();

	await item(page, 'Later (copy)').click({ button: 'right' });
	await menu(page).getByRole('menuitem', { name: 'Delete…' }).click();
	await expect(item(page, 'Later (copy)')).toBeHidden();
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect(await flowBlocks(page)).toEqual(['b1', 'b2']);
	await undoButton(page).click();
	await expect(item(page, 'Later (copy)')).toBeVisible();
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect(await flowBlocks(page)).toEqual(['b1', 'b2', 'b2_copy']);
});

test('Add block in the Flow view: a new block node at the end of the flow, focused', async ({ page }) => {
	await seeded(page);
	await page.getByRole('navigation', { name: 'Builder views' }).getByRole('button', { name: 'Flow' }).click();
	await expect(page.getByRole('heading', { name: 'Survey flow' })).toBeVisible();
	await page.getByRole('button', { name: 'Add block' }).click();
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect(await flowBlocks(page)).toEqual(['b1', 'b2', 'block1']);
	await expect(page.locator('[data-flow-handle="n_block1"]')).toBeFocused();
	expect(await axe(page)).toEqual([]);
	await runFromPalette(page, 'add block', /^Add block$/);
	// Run after the palette closes (a timer): wait for the new node before "saved".
	await expect(page.locator('[data-flow-handle="n_block2"]')).toHaveCount(1);
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect(await flowBlocks(page)).toEqual(['b1', 'b2', 'block1', 'block2']);
});

test('320 px: outline actions fit; the menu and the warning fit and are axe-clean', async ({ page }) => {
	await page.setViewportSize({ width: 320, height: 640 });
	await seeded(page);
	await banner(page).getByRole('button', { name: 'Outline pane' }).click();
	const actions = page.getByRole('group', { name: 'Pages and blocks' });
	await expect(actions).toBeVisible();
	for (const b of await actions.getByRole('button').all()) {
		const box = (await b.boundingBox())!;
		expect(box.height).toBeGreaterThanOrEqual(44);
		expect(box.x + box.width).toBeLessThanOrEqual(320);
	}
	await item(page, 'Start').click();
	await actions.getByRole('button', { name: 'Actions for Start' }).click();
	await expect(menu(page)).toBeVisible();
	const box = (await menu(page).boundingBox())!;
	expect(box.x).toBeGreaterThanOrEqual(0);
	expect(box.x + box.width).toBeLessThanOrEqual(320);
	expect(await axe(page)).toEqual([]);
	await menu(page).getByRole('menuitem', { name: 'Delete…' }).click();
	const dialog = page.getByRole('dialog', { name: 'Delete a page that is still used?' });
	await expect(dialog).toBeVisible();
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
	expect(await axe(page)).toEqual([]);
	await page.keyboard.press('Escape');
	await expect(dialog).toBeHidden();
	expect((await pageIds(page))[0]).toEqual(['p1', 'p2']);
	// "Add page" on the canvas works here too and opens the title field.
	await banner(page).getByRole('button', { name: 'Outline pane' }).click();
	await page.getByRole('button', { name: 'Add page after Second' }).click();
	await expect(titleField(page)).toBeFocused();
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect((await pageIds(page))[0]).toEqual(['p1', 'p2', 'page1']);
});
