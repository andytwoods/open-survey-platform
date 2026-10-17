import { expect, test, type Page } from '@playwright/test';
import { axe, runFromPalette, signIn, writeHeaders } from './fixtures';

// Outline reorder (task B3) and the property panel's specialised editors, end to end
// against a real osp-api (e2e/api_server.py): drag, keyboard, cross-page, multi-select,
// undo, reload, a rejected move rolled back; choices and show-if dialogs persist.

const tree = (page: Page) => page.getByRole('tree', { name: 'Survey outline' });
const item = (page: Page, name: string) => tree(page).getByRole('treeitem', { name, exact: true });
const saveState = (page: Page) => page.getByRole('banner').getByRole('status').first();
const announcer = (page: Page) => page.getByTestId('announcer');

/** Ids of the rows in display order. */
const order = (page: Page) =>
	tree(page)
		.locator('[role="treeitem"]')
		.evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.id));

const text = (en: string) => ({ en });
const question = (id: string, label: string, extra: Record<string, unknown> = {}) => ({
	id,
	type: 'text',
	label: text(label),
	...extra
});

/** Sign in, create a survey, seed it through the ops API, and open it. */
async function seeded(page: Page, ops: { op: string; params: Record<string, unknown> }[]) {
	await signIn(page);
	await page.getByLabel('New survey title').fill(`Outline ${Date.now()}`);
	await page.getByRole('button', { name: 'Create survey' }).click();
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	const id = page.url().split('/').pop()!;
	const detail = await (await page.request.get(`/api/surveys/${id}`)).json();
	const res = await page.request.post(`/api/surveys/${id}/ops`, {
		headers: await writeHeaders(page),
		data: { baseRevision: detail.revision, ops }
	});
	expect(res.status(), await res.text()).toBe(200);
	await page.reload();
	await expect(tree(page)).toBeVisible();
	return id;
}

// p1: intro, Alpha, Beta, Gamma; p2 ("Second"): Delta.
const SEED = [
	{ op: 'add_question', params: { page: 'p1', question: question('qa', 'Alpha') } },
	{ op: 'add_question', params: { page: 'p1', question: question('qb', 'Beta') } },
	{ op: 'add_question', params: { page: 'p1', question: question('qc', 'Gamma') } },
	{
		op: 'add_page',
		params: { block: 'b1', page: { id: 'p2', title: text('Second'), items: [question('qd', 'Delta')] } }
	}
];

async function drag(page: Page, from: string, to: string, where: 'before' | 'after' | 'into') {
	const a = (await item(page, from).boundingBox())!;
	const b = (await item(page, to).boundingBox())!;
	const y = where === 'before' ? b.y + 3 : where === 'after' ? b.y + b.height - 3 : b.y + b.height / 2;
	await page.mouse.move(a.x + 40, a.y + a.height / 2);
	await page.mouse.down();
	await page.mouse.move(a.x + 40, y, { steps: 10 });
	await expect(tree(page).locator(`[data-drop="${where}"]`)).toHaveCount(1);
	await page.mouse.up();
}

test('drag, keyboard, cross-page and multi-select moves; undo; reload', async ({ page }) => {
	await seeded(page, SEED);
	expect(await order(page)).toEqual(['b1', 'p1', 'intro', 'qa', 'qb', 'qc', 'p2', 'qd']);
	expect(await axe(page)).toEqual([]);

	// Mouse: Gamma before Alpha. One move_question; announced.
	await drag(page, 'Gamma', 'Alpha', 'before');
	await expect.poll(() => order(page)).toEqual(['b1', 'p1', 'intro', 'qc', 'qa', 'qb', 'p2', 'qd']);
	await expect(announcer(page)).toHaveText('Moved Gamma to position 2 of 4 in p1');
	await expect(saveState(page)).toHaveText(/All changes saved/);

	// Keyboard: Alt+↓ moves Alpha past Beta; focus stays on it.
	await item(page, 'Alpha').click();
	await page.keyboard.press('Alt+ArrowDown');
	await expect.poll(() => order(page)).toEqual(['b1', 'p1', 'intro', 'qc', 'qb', 'qa', 'p2', 'qd']);
	await expect(item(page, 'Alpha')).toBeFocused();
	await expect(saveState(page)).toHaveText(/All changes saved/);

	// Alt+Shift+↓ crosses into the next page (at its start).
	await page.keyboard.press('Alt+Shift+ArrowDown');
	await expect.poll(() => order(page)).toEqual(['b1', 'p1', 'intro', 'qc', 'qb', 'p2', 'qa', 'qd']);
	await expect(announcer(page)).toHaveText('Moved Alpha to position 1 of 2 in Second');
	await expect(saveState(page)).toHaveText(/All changes saved/);

	// Multi-select (Ctrl/Cmd+click) and drag both into Second: one transaction.
	await item(page, 'Gamma').click();
	await item(page, 'Beta').click({ modifiers: ['ControlOrMeta'] });
	await expect(tree(page).locator('[aria-selected="true"]')).toHaveCount(2);
	await drag(page, 'Beta', 'Delta', 'after');
	await expect.poll(() => order(page)).toEqual(['b1', 'p1', 'intro', 'p2', 'qa', 'qd', 'qc', 'qb']);
	await expect(announcer(page)).toHaveText('Moved 2 questions to position 3 of 4 in Second');
	await expect(saveState(page)).toHaveText(/All changes saved/);
	expect(await axe(page)).toEqual([]);

	// Undo reverses the multi-move in one step, then the cross-page move.
	const undo = page.getByRole('banner').getByRole('button', { name: 'Undo', exact: true });
	await undo.click();
	await expect.poll(() => order(page)).toEqual(['b1', 'p1', 'intro', 'qc', 'qb', 'p2', 'qa', 'qd']);
	await undo.click();
	await expect.poll(() => order(page)).toEqual(['b1', 'p1', 'intro', 'qc', 'qb', 'qa', 'p2', 'qd']);
	await expect(saveState(page)).toHaveText(/All changes saved/);

	// Reload: the server has it.
	await page.reload();
	await expect.poll(() => order(page)).toEqual(['b1', 'p1', 'intro', 'qc', 'qb', 'qa', 'p2', 'qd']);
});

test('"Move to…" from the palette moves the selection', async ({ page }) => {
	await seeded(page, SEED);
	await item(page, 'Alpha').click();
	await item(page, 'Gamma').click({ modifiers: ['Shift'] });
	await expect(tree(page).locator('[aria-selected="true"]')).toHaveCount(3);
	await runFromPalette(page, 'move to', /Move to/);
	const dialog = page.getByRole('dialog', { name: 'Move to…' });
	await expect(dialog).toBeVisible();
	expect(await axe(page)).toEqual([]);
	await dialog.getByLabel('Destination page').selectOption({ label: 'Second (b1)' });
	await dialog.getByLabel('Position').selectOption({ label: 'At the start' });
	await dialog.getByRole('button', { name: 'Move' }).click();
	await expect.poll(() => order(page)).toEqual(['b1', 'p1', 'intro', 'p2', 'qa', 'qb', 'qc', 'qd']);
	await expect(saveState(page)).toHaveText(/All changes saved/);
	await page.reload();
	await expect.poll(() => order(page)).toEqual(['b1', 'p1', 'intro', 'p2', 'qa', 'qb', 'qc', 'qd']);
});

test('a rejected move is rolled back and the reason shown', async ({ page }) => {
	await seeded(page, SEED);
	// Delta is the only question on Second: moving it out would leave the page empty.
	await item(page, 'Delta').click();
	await page.keyboard.press('Alt+Shift+ArrowUp');
	await expect(page.getByRole('region', { name: 'Notifications' })).toContainText(/empty/);
	await expect(announcer(page)).toContainText(/Move not applied/);
	await expect.poll(() => order(page)).toEqual(['b1', 'p1', 'intro', 'qa', 'qb', 'qc', 'p2', 'qd']);
	await expect(item(page, 'Delta')).toBeFocused();
});

test('pages and blocks reorder too', async ({ page }) => {
	await seeded(page, SEED);
	await item(page, 'Second').click();
	await page.keyboard.press('Alt+ArrowUp');
	await expect.poll(() => order(page)).toEqual(['b1', 'p2', 'qd', 'p1', 'intro', 'qa', 'qb', 'qc']);
	await expect(saveState(page)).toHaveText(/All changes saved/);
	await drag(page, 'p1', 'Second', 'before');
	await expect.poll(() => order(page)).toEqual(['b1', 'p1', 'intro', 'qa', 'qb', 'qc', 'p2', 'qd']);
	await expect(saveState(page)).toHaveText(/All changes saved/);
});

test('choices and show-if dialogs from the property panel persist', async ({ page }) => {
	await seeded(page, [
		{ op: 'add_question', params: { page: 'p1', question: question('qa', 'Alpha') } },
		{
			op: 'add_question',
			params: {
				page: 'p1',
				question: {
					id: 'colour',
					type: 'single',
					label: text('Favourite colour'),
					choices: [
						{ value: 1, label: text('Red') },
						{ value: 2, label: text('Blue') }
					]
				}
			}
		}
	]);
	const props = page.getByRole('complementary', { name: 'Properties' });

	// Choices: add one in the dialog, then reload.
	await item(page, 'Favourite colour').click();
	await props.getByRole('button', { name: /Edit choices/ }).click();
	const choices = page.getByRole('dialog', { name: 'Edit choices' });
	await expect(choices).toBeVisible();
	await expect(choices.locator('[data-row]')).toHaveCount(2);
	await choices.getByRole('button', { name: 'Add choice' }).click();
	await expect(choices.locator('[data-row]')).toHaveCount(3);
	await expect(saveState(page)).toHaveText(/All changes saved/);
	expect(await axe(page)).toEqual([]);
	await choices.getByRole('button', { name: 'Done' }).click();
	await expect(props.getByText('3 choices')).toBeVisible();

	// Show if: set through the condition dialog (text view), then reload.
	const showIf = props.locator('[data-kind="condition"]').first();
	await expect(showIf.getByTestId('summary')).toHaveText('No condition');
	await showIf.getByRole('button', { name: /Edit condition/ }).click();
	const cond = page.getByRole('dialog', { name: 'Edit condition' });
	await expect(cond).toBeVisible();
	await cond.getByTestId('view-text').click();
	await cond.locator('.cm-content').click();
	await page.keyboard.type('answered(qa)');
	await expect(cond.getByTestId('condition-apply')).not.toHaveAttribute('aria-disabled', 'true');
	await cond.getByTestId('condition-apply').click();
	await expect(cond).toBeHidden();
	await expect(showIf.getByTestId('summary')).not.toHaveText('No condition');
	await expect(saveState(page)).toHaveText(/All changes saved/);

	await page.reload();
	await item(page, 'Favourite colour').click();
	await expect(props.getByText('3 choices')).toBeVisible();
	await expect(props.locator('[data-kind="condition"]').first().getByTestId('summary')).toHaveText(/qa/);
});
