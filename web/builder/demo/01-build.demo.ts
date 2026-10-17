import { expect, test, type Page } from '@playwright/test';
import { beat, caption, click, moveTo, press, recordingContext, saveRecording, type } from './overlay';
import { applyOps, DEMO_TITLE } from './seed';

// Video 1: building a survey. Create it, add questions through the type picker and the
// outline toolbox, edit choices and grid rows, add a display condition, undo/redo, the
// command palette, then the flow view with a randomiser.

const banner = (page: Page) => page.getByRole('banner');
const saved = (page: Page) => expect(banner(page).getByRole('status').first()).toHaveText(/All changes saved/);
const props = (page: Page) => page.getByRole('complementary', { name: 'Properties' });
const toolType = (page: Page, name: string) => page.getByRole('button', { name: `Add ${name} question`, exact: true });
const questionText = (page: Page) => props(page).getByRole('textbox', { name: 'Question text' });

test('01 building a survey', async ({ browser }) => {
	const context = await recordingContext(browser, '01-building-a-survey');
	const page = await context.newPage();

	// -- Create ---------------------------------------------------------------------
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'Your surveys' })).toBeVisible();
	await caption(page, 'Building a survey in the Open Survey Platform builder', 1800);
	await caption(page, 'Create a survey', 600);
	await type(page, page.getByLabel('New survey title'), DEMO_TITLE);
	await click(page, page.getByRole('button', { name: 'Create survey' }));
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	const id = page.url().split('/').pop()!;
	await expect(page.getByRole('tree', { name: 'Survey outline' })).toBeVisible();
	await expect(page.getByRole('button', { name: /Add question to/ }).first()).toBeVisible();
	await caption(page, 'Outline on the left, the questions in the middle, properties on the right', 2200);

	// -- The intro note ---------------------------------------------------------------
	await caption(page, 'Write the welcome note', 500);
	await click(page, page.getByRole('tree', { name: 'Survey outline' }).getByRole('treeitem', { name: '(intro)' }));
	await type(page, props(page).getByRole('textbox', { name: 'Text', exact: true }), 'Thanks for helping with this (invented) study.');
	await saved(page);

	// -- Type picker ------------------------------------------------------------------
	await caption(page, 'Add a question with the type picker', 500);
	await click(page, page.getByRole('button', { name: /Add question to/ }).first());
	const picker = page.getByRole('dialog', { name: 'Add a question' });
	await expect(picker.getByRole('combobox', { name: 'Filter question types' })).toBeFocused();
	await beat(page, 900);
	await click(page, picker.getByRole('option', { name: /^Whole number\b/ }));
	await expect(picker).toBeHidden();
	await expect(page.getByTestId('question-type')).toHaveText('Whole number');
	await type(page, questionText(page), 'How many cups of coffee did you drink yesterday?');
	await saved(page);

	// -- Toolbox + choices ------------------------------------------------------------
	await caption(page, '…or click a type in the toolbox under the outline', 500);
	await click(page, toolType(page, 'Single choice'));
	await expect(page.getByTestId('question-type')).toHaveText('Single choice');
	await type(page, questionText(page), 'How do you usually take your coffee?');
	await caption(page, 'Edit the answer choices', 500);
	await click(page, props(page).getByRole('button', { name: /Edit choices/ }));
	const choices = page.getByRole('dialog', { name: 'Edit choices' });
	await expect(choices).toBeVisible();
	await type(page, choices.getByLabel('Label for choice 1'), 'Black');
	for (const [n, label] of [
		[2, 'With milk'],
		[3, 'With oat milk']
	] as const) {
		await click(page, choices.getByRole('button', { name: 'Add choice' }));
		await type(page, choices.getByLabel(`Label for choice ${n}`), label);
	}
	await press(page, 'Tab');
	await saved(page);
	await click(page, choices.getByRole('button', { name: 'Done' }));
	await expect(choices).toBeHidden();
	await expect(page.locator('#pane-canvas')).toContainText('With oat milk');

	// -- Grid + rows ------------------------------------------------------------------
	await caption(page, 'A grid: one row per thing to rate', 500);
	await click(page, toolType(page, 'Grid'));
	await expect(page.getByTestId('question-type')).toHaveText('Grid');
	await type(page, questionText(page), 'How well did you sleep this week?');
	await click(page, props(page).getByRole('button', { name: /Edit rows/ }));
	const rows = page.getByRole('dialog', { name: 'Edit rows' });
	await expect(rows).toBeVisible();
	await type(page, rows.getByLabel('Label for row 1'), 'Weeknights');
	await type(page, rows.getByLabel('Label for row 2'), 'At the weekend');
	await click(page, rows.getByRole('button', { name: 'Add row' }));
	await type(page, rows.getByLabel('Label for row 3'), 'Last night');
	await press(page, 'Enter');
	await saved(page);
	await click(page, rows.getByRole('button', { name: 'Done' }));
	await expect(rows).toBeHidden();
	await expect(page.locator('#pane-canvas')).toContainText('At the weekend');
	await caption(page, 'The grid’s columns: paste a list', 500);
	await click(page, props(page).getByRole('button', { name: /Edit choices/ }));
	const columns = page.getByRole('dialog', { name: 'Edit choices' });
	await click(page, columns.getByRole('button', { name: 'Paste list…' }));
	await type(page, columns.getByLabel('One choice per line'), 'Badly\nOK\nWell');
	await expect(columns.getByRole('table', { name: 'Preview' }).locator('tbody tr')).toHaveCount(3);
	await beat(page, 600);
	await click(page, columns.getByRole('button', { name: 'Replace with 3 choices' }));
	await saved(page);
	await click(page, columns.getByRole('button', { name: 'Done' }));
	await expect(columns).toBeHidden();
	await expect(page.locator('#pane-canvas')).toContainText('Badly');

	// -- Display condition ------------------------------------------------------------
	await caption(page, 'A follow-up question, shown only to heavy coffee drinkers', 500);
	await click(page, toolType(page, 'Text'));
	await expect(page.getByTestId('question-type')).toHaveText('Text');
	await type(page, questionText(page), 'What keeps you awake at night?');
	await saved(page);
	await click(page, props(page).getByRole('button', { name: 'Show if Edit condition…' }));
	const cond = page.getByRole('dialog', { name: 'Edit condition' });
	await expect(cond).toBeVisible();
	await click(page, cond.getByRole('button', { name: 'Add condition to condition' }));
	const row = cond.getByTestId('condition-row').first();
	const q = row.locator('[data-role="question"]');
	const cupsOption = q.locator('option', { hasText: 'cups of coffee' });
	await moveTo(page, q);
	await q.selectOption((await cupsOption.getAttribute('value'))!);
	await beat(page, 500);
	await moveTo(page, row.locator('[data-role="operator"]'));
	await row.locator('[data-role="operator"]').selectOption({ label: 'at least (≥)' });
	await beat(page, 500);
	await type(page, row.locator('[data-role="value"]'), '3');
	await expect(cond.getByTestId('condition-apply')).not.toHaveAttribute('aria-disabled', 'true');
	await beat(page, 900);
	await click(page, cond.getByRole('button', { name: 'Apply' }));
	await expect(cond).toBeHidden();
	await saved(page);
	await beat(page, 900);

	// -- Undo / redo ------------------------------------------------------------------
	await caption(page, 'Every edit can be undone and redone', 500);
	await click(page, banner(page).getByRole('button', { name: 'Undo', exact: true }));
	await saved(page);
	await beat(page, 700);
	await click(page, banner(page).getByRole('button', { name: 'Redo', exact: true }));
	await saved(page);
	await beat(page, 700);

	// A second block for the flow (the builder adds blocks through the API today).
	await applyOps(page, id, [{ op: 'add_block', params: { id: 'evening', title: 'Evening routine' } }]);

	// -- Command palette → Flow -------------------------------------------------------
	await caption(page, 'The command palette (Ctrl/⌘+K) reaches every command', 500);
	await page.getByRole('main', { name: 'Canvas' }).click({ position: { x: 5, y: 5 } });
	await page.keyboard.press('ControlOrMeta+k');
	const palette = page.getByRole('dialog', { name: 'Command palette' });
	await expect(palette.getByRole('combobox', { name: 'Commands' })).toBeFocused();
	await beat(page, 600);
	await page.keyboard.type('flow', { delay: 90 });
	await expect(palette.getByRole('option', { name: /Open survey flow/ })).toHaveAttribute('aria-selected', 'true');
	await beat(page, 800);
	await page.keyboard.press('Enter');
	await expect(page).toHaveURL(/\/flow$/);
	await expect(page.getByRole('heading', { name: 'Survey flow', level: 2 })).toBeVisible();

	// -- Randomiser -------------------------------------------------------------------
	await caption(page, 'Flow: add a randomiser so blocks come in random order', 500);
	await click(page, page.getByRole('button', { name: 'Add node to Survey flow at position 2', exact: true }));
	const add = page.getByRole('dialog', { name: 'Add flow node' });
	await expect(add).toBeVisible();
	await moveTo(page, add.getByLabel('Node type'));
	await add.getByLabel('Node type').selectOption('randomiser');
	await beat(page, 600);
	await moveTo(page, add.getByLabel('First block'));
	await add.getByLabel('First block').selectOption('evening');
	await beat(page, 600);
	await click(page, add.getByRole('button', { name: 'Add', exact: true }));
	await expect(add).toBeHidden();
	await saved(page);
	const randomiser = page.locator('article[data-type="randomiser"]');
	await expect(randomiser).toBeVisible();

	await caption(page, 'Move the first block into it (Alt+↓ on the handle, or drag)', 500);
	const handle = page.getByRole('button', { name: 'Move Block: b1', exact: true });
	await click(page, handle);
	for (let i = 0; i < 4; i++) {
		if (await randomiser.getByRole('heading', { name: 'Block: b1' }).count()) break;
		await press(page, 'Alt+ArrowDown');
	}
	await expect(randomiser.getByRole('heading', { name: 'Block: b1' })).toBeVisible();
	await saved(page);
	await caption(page, 'Everything saves as you go', 2200);
	await caption(page, '', 400);
	await saveRecording(context, page, '01-building-a-survey');
});
