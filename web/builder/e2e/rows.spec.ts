import { readFileSync } from 'node:fs';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { axe, fillRich, openRich, signIn, writeHeaders } from './fixtures';

// Grid rows editor (task B15), against a real osp-api on SQLite with fixture 38-matrix
// (grid `taste`: rows tea, coffee, cocoa; `cups` shows when taste_tea == 3 and pipes it):
// add, rename, reorder by keyboard and mouse, required, delete, undo, the "still used"
// warning, the canvas card following along; 320 px and axe in light and dark. Labels are
// inline rich-text fields (RT5): a read-only textbox per row until it is focused.

type Survey = { blocks: unknown[]; flow: unknown[]; choiceLists?: unknown[]; [k: string]: unknown };
const FIXTURE = JSON.parse(
	readFileSync(new URL('../../../fixtures/38-matrix/survey.json', import.meta.url), 'utf8')
) as Survey;

async function openGrid(page: Page): Promise<string> {
	await signIn(page);
	await page.getByLabel('New survey title').fill(`Grid rows ${Date.now()}`);
	await page.getByRole('button', { name: 'Create survey' }).click();
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	await page.waitForLoadState('load');
	await expect(page.getByRole('button', { name: /Add question to/ }).first()).toBeVisible();
	const id = page.url().split('/').pop()!;
	const start = (await (await page.request.get(`/api/surveys/${id}`)).json()) as { survey: Survey };
	const survey = { ...structuredClone(start.survey), choiceLists: FIXTURE.choiceLists, blocks: FIXTURE.blocks, flow: FIXTURE.flow };
	const r = await page.request.post(`/api/surveys/${id}/ops`, {
		headers: await writeHeaders(page),
		data: { baseRevision: 0, ops: [{ op: 'replace_survey', params: { survey } }] }
	});
	expect(r.status()).toBe(200);
	await page.reload();
	await page.waitForLoadState('load');
	await expect(card(page)).toBeVisible();
	return id;
}

const card = (page: Page, id = 'taste') => page.locator(`#pane-canvas [data-question-card="${id}"]`);
const saved = (page: Page) => page.getByRole('banner').getByRole('status').first();
const dialogOf = (page: Page) => page.getByRole('dialog', { name: 'Edit rows' });

async function openRows(page: Page) {
	await page.locator('#card-taste').click();
	const props = page.getByRole('complementary', { name: 'Properties' });
	await props.getByRole('button', { name: /Edit rows/ }).click();
	const dialog = dialogOf(page);
	await expect(dialog).toBeVisible();
	await expect(dialog).toContainText('How do you rate these drinks?');
	return dialog;
}

const labels = (page: Page) =>
	dialogOf(page)
		.locator('[data-row] [data-field="label"] [role="textbox"]')
		.evaluateAll((els) => els.map((e) => e.textContent ?? ''));
/** A row's label field: the idle textbox, or the open editor (the same accessible name). */
const labelField = (dialog: Locator, n: number) => dialog.getByRole('textbox', { name: `Label for row ${n}`, exact: true });
const rowIds = (page: Page) =>
	dialogOf(page)
		.locator('[data-row]')
		.evaluateAll((els) => els.map((e) => e.getAttribute('data-row-id')));

async function serverRows(page: Page, id: string) {
	const s = (await (await page.request.get(`/api/surveys/${id}`)).json()) as {
		survey: { blocks: { pages: { items: { id: string; rows?: { id: string; label: unknown; required?: boolean }[] }[] }[] }[] };
	};
	return s.survey.blocks[0].pages[0].items[0].rows!;
}

test('add, rename, reorder (keyboard and mouse), required: the card follows', async ({ page }) => {
	const id = await openGrid(page);
	const dialog = await openRows(page);
	expect(await labels(page)).toEqual(['Tea', 'Coffee', 'Cocoa (optional)']);
	await expect(dialog).toContainText('taste_coffee');

	// Add: focus lands on the new row's label (which opens its editor); type and Enter renames it.
	await dialog.getByRole('button', { name: 'Add row' }).click();
	const added = labelField(dialog, 4);
	await expect(added).toBeFocused();
	await expect(added).toHaveAttribute('contenteditable', 'true');
	await page.keyboard.type('Juice');
	await page.keyboard.press('Enter');
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect(card(page)).toContainText('Juice');
	expect(await rowIds(page)).toEqual(['tea', 'coffee', 'cocoa', 'r4']);

	// Rename keeps the id (and so the variable).
	await fillRich(page, labelField(dialog, 2), 'Filter coffee');
	await page.keyboard.press('Tab');
	await expect(card(page)).toContainText('Filter coffee');
	expect(await rowIds(page)).toEqual(['tea', 'coffee', 'cocoa', 'r4']);

	// Keyboard reorder keeps focus on the moved row.
	await openRich(page, labelField(dialog, 1));
	await page.keyboard.press('Alt+ArrowDown');
	await expect.poll(() => rowIds(page)).toEqual(['coffee', 'tea', 'cocoa', 'r4']);
	await expect(labelField(dialog, 2)).toBeFocused();
	await expect(labelField(dialog, 2)).toHaveText('Tea');

	// Mouse drag: Juice (last) to the top.
	const handle = dialog.getByRole('button', { name: 'Move Juice' });
	const target = dialog.locator('[data-row][data-index="0"]');
	const h = (await handle.boundingBox())!;
	const t = (await target.boundingBox())!;
	await page.mouse.move(h.x + h.width / 2, h.y + h.height / 2);
	await page.mouse.down();
	await page.mouse.move(h.x + h.width / 2, t.y + t.height * 0.25, { steps: 10 });
	await expect(dialog.locator('[data-row][data-drop="before"]')).toHaveCount(1);
	await page.mouse.up();
	await expect.poll(() => rowIds(page)).toEqual(['r4', 'coffee', 'tea', 'cocoa']);

	// Required: tea follows the grid (required); switching it off stores false; cocoa back on
	// follows the grid again.
	const teaReq = dialog.getByRole('switch', { name: 'Required: Tea' });
	await expect(teaReq).toHaveAttribute('aria-checked', 'true');
	await teaReq.click();
	await expect(teaReq).toHaveAttribute('aria-checked', 'false');
	await dialog.getByRole('switch', { name: 'Required: Cocoa (optional)' }).click();
	await expect(dialog.getByRole('switch', { name: 'Required: Cocoa (optional)' })).toHaveAttribute('aria-checked', 'true');
	await expect(saved(page)).toHaveText(/All changes saved/);

	const rows = await serverRows(page, id);
	expect(rows.map((r) => [r.id, r.label, r.required])).toEqual([
		['r4', 'Juice', undefined],
		['coffee', 'Filter coffee', undefined],
		['tea', 'Tea', false],
		['cocoa', 'Cocoa (optional)', undefined]
	]);

	// The card shows the rows in the new order.
	await dialog.getByRole('button', { name: 'Done' }).click();
	await expect(dialog).toBeHidden();
	await expect(page.getByRole('complementary', { name: 'Properties' }).getByRole('button', { name: /Edit rows/ })).toBeFocused();
	const text = (await card(page).textContent()) ?? '';
	const order = ['Juice', 'Filter coffee', 'Tea', 'Cocoa'].map((s) => text.indexOf(s));
	expect(order.every((n, i) => n >= 0 && (i === 0 || n > order[i - 1]))).toBe(true);
});

test('a formatted row label is stored as a tree, shown on the card and in the dialog (RT5)', async ({ page }) => {
	const id = await openGrid(page);
	const dialog = await openRows(page);
	const tea = labelField(dialog, 1);
	await expect(tea).toHaveAttribute('aria-multiline', 'false');
	await expect(dialog.locator('.osp-rt-count')).toHaveCount(0);
	await fillRich(page, tea, 'Green ');
	await expect(dialog.locator('.osp-rt-count')).toHaveText(/6 \/ 500/);
	const tb = page.getByRole('toolbar', { name: 'Text formatting' });
	await expect(tb.getByRole('button', { name: 'Bulleted list' })).toHaveCount(0);
	await tb.getByRole('button', { name: 'Italic' }).click();
	await page.keyboard.type('tea');
	await page.keyboard.press('Enter');
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect(await axe(page)).toEqual([]);
	await page.keyboard.press('Tab');
	await expect(tea).not.toHaveAttribute('contenteditable', 'true');
	await expect(tea.locator('em')).toHaveText('tea');
	await expect(dialog.getByRole('button', { name: 'Move Green tea' })).toBeVisible();
	await expect(card(page).locator('em')).toHaveText('tea');
	const rows = await serverRows(page, id);
	expect(rows[0]).toEqual({
		id: 'tea',
		label: { type: 'rich', blocks: [{ type: 'p', content: [{ text: 'Green ' }, { text: 'tea', marks: ['i'] }] }] }
	});
	// Escape with a draft reverts it and keeps the dialog open.
	await openRich(page, tea);
	await page.keyboard.press('End');
	await page.keyboard.type(' oops');
	await page.keyboard.press('Escape');
	await expect(dialog).toBeVisible();
	await expect(tea).toHaveText('Green tea');
	await expect(tea).toBeFocused();
});

test('delete an unused row, then undo it', async ({ page }) => {
	const id = await openGrid(page);
	const dialog = await openRows(page);
	await dialog.getByRole('button', { name: 'Delete Coffee' }).click();
	await expect.poll(() => rowIds(page)).toEqual(['tea', 'cocoa']);
	await expect(page.getByTestId('row-delete-warning')).toHaveCount(0);
	await expect(card(page)).not.toContainText('Coffee');
	await expect(saved(page)).toHaveText(/All changes saved/);

	await dialog.getByRole('button', { name: 'Done' }).click();
	await page.getByRole('banner').getByRole('button', { name: 'Undo', exact: true }).click();
	await expect(card(page)).toContainText('Coffee');
	await expect.poll(async () => (await serverRows(page, id)).map((r) => r.id)).toEqual(['tea', 'coffee', 'cocoa']);
});

test('deleting a row that conditions and piping use asks first', async ({ page }) => {
	const id = await openGrid(page);
	const dialog = await openRows(page);
	await dialog.getByRole('button', { name: 'Delete Tea' }).click();
	const warn = page.getByRole('dialog', { name: 'Delete a row that is still used?' });
	await expect(warn).toBeVisible();
	await expect(warn).toContainText('taste_tea');
	await expect(warn).toContainText('How many cups a day? (condition)');
	await expect(warn).toContainText('How many cups a day? (text)');
	expect(await axe(page)).toEqual([]);
	// The plain refusal is not shown as an error: the dialog handles it.
	await expect(page.getByText('is still referenced')).toHaveCount(0);

	await warn.getByRole('button', { name: 'Keep row' }).click();
	await expect(warn).toBeHidden();
	expect(await rowIds(page)).toEqual(['tea', 'coffee', 'cocoa']);

	await dialog.getByRole('button', { name: 'Delete Tea' }).click();
	await warn.getByRole('button', { name: 'Delete anyway' }).click();
	await expect(warn).toBeHidden();
	await expect.poll(() => rowIds(page)).toEqual(['coffee', 'cocoa']);
	await expect(card(page)).not.toContainText('Tea');
	await expect(saved(page)).toHaveText(/All changes saved/);

	// Undo brings it back with its id, label and place.
	await dialog.getByRole('button', { name: 'Done' }).click();
	await page.getByRole('banner').getByRole('button', { name: 'Undo', exact: true }).click();
	await expect(card(page)).toContainText('Tea');
	await expect
		.poll(async () => (await serverRows(page, id)).map((r) => [r.id, r.label]))
		.toEqual([
			['tea', 'Tea'],
			['coffee', 'Coffee'],
			['cocoa', 'Cocoa (optional)']
		]);
});

test('320 px: no horizontal scroll, 44 px targets', async ({ page }) => {
	await page.setViewportSize({ width: 320, height: 700 });
	await openGrid(page);
	// At 320 px the properties pane is a drawer: open it from the top bar.
	await page.locator('#card-taste').click();
	const props = page.getByRole('complementary', { name: 'Properties' });
	if (!(await props.getByRole('button', { name: /Edit rows/ }).isVisible())) {
		await page.getByRole('banner').getByRole('button', { name: 'Properties pane' }).click();
	}
	await props.getByRole('button', { name: /Edit rows/ }).click();
	const dialog = dialogOf(page);
	await expect(dialog).toBeVisible();
	const overflow = await page.evaluate(() => {
		const d = document.querySelector('[data-testid="rows-editor"]')!;
		return [document.documentElement.scrollWidth - document.documentElement.clientWidth, d.scrollWidth - d.clientWidth];
	});
	expect(overflow.every((n) => n <= 0)).toBe(true);
	const box = (await dialog.boundingBox())!;
	expect(box.x).toBeGreaterThanOrEqual(0);
	expect(box.x + box.width).toBeLessThanOrEqual(320);
	const sizes = await dialog
		.locator('[data-testid="rows-editor"] :is(button, input, [role="textbox"])')
		.evaluateAll((els) => els.map((e) => {
			const r = e.getBoundingClientRect();
			return { name: e.getAttribute('aria-label') ?? e.textContent?.trim(), w: r.width, h: r.height };
		}));
	expect(sizes.length).toBeGreaterThan(10);
	for (const s of sizes) expect(Math.min(s.w, s.h), s.name ?? '').toBeGreaterThanOrEqual(44);
});

for (const scheme of ['light', 'dark'] as const) {
	test(`axe-clean with the rows editor open, ${scheme}`, async ({ page }) => {
		await page.emulateMedia({ colorScheme: scheme });
		await openGrid(page);
		await openRows(page);
		await expect(saved(page)).toHaveText(/All changes saved/);
		expect(await axe(page)).toEqual([]);
	});
}
