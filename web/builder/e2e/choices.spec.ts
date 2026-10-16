import { expect, test, type Locator, type Page } from '@playwright/test';
import { axe } from './fixtures';

// Choice list editor sandbox (/dev/choices, task B6): reorder by mouse and keyboard, bulk
// paste, validation, shared lists, the published-code warning, axe in both themes.

async function open(page: Page) {
	await page.goto('/dev/choices');
	await expect(page.getByRole('heading', { level: 1, name: 'Choice list editor' })).toBeVisible();
	return page.getByRole('region', { name: 'Editor' });
}

const codes = (editor: Locator) => editor.locator('[data-row]').evaluateAll((rows) => rows.map((r) => r.getAttribute('data-code')));
const labelsOf = (editor: Locator) =>
	editor.locator('[data-row] input[data-field="label"]').evaluateAll((els) => els.map((e) => (e as HTMLInputElement).value));
const lastTxn = (page: Page) => page.getByTestId('op-log').locator('li').last();
const txnCount = (page: Page) => page.getByTestId('op-log').locator('li').count();

for (const scheme of ['light', 'dark'] as const) {
	test(`axe-clean, ${scheme}`, async ({ page }) => {
		await page.emulateMedia({ colorScheme: scheme });
		const editor = await open(page);
		expect(await axe(page)).toEqual([]);
		// With the paste preview, a row error and a shared list showing too.
		await editor.getByRole('button', { name: 'Paste list…' }).click();
		await editor.getByLabel('One choice per line').fill('1 Yes\n1 No');
		await editor.getByLabel('Code for choice 2').fill('1');
		await page.getByRole('radio', { name: 'q_work' }).check();
		await page.getByRole('radio', { name: 'q_mood' }).check();
		await editor.getByLabel('Code for choice 2').fill('a b');
		expect(await axe(page)).toEqual([]);
	});
}

test('drag the handle with the mouse: one move_choice', async ({ page }) => {
	const editor = await open(page);
	expect(await codes(editor)).toEqual(['1', '2', '3']);
	const handle = editor.getByRole('button', { name: 'Move Good' });
	const target = editor.locator('[data-row][data-index="2"]');
	const h = (await handle.boundingBox())!;
	const t = (await target.boundingBox())!;
	await page.mouse.move(h.x + h.width / 2, h.y + h.height / 2);
	await page.mouse.down();
	await page.mouse.move(h.x + h.width / 2, t.y + t.height * 0.75, { steps: 8 });
	await expect(editor.locator('[data-row][data-drop="after"]')).toHaveCount(1);
	await page.mouse.up();
	expect(await codes(editor)).toEqual(['2', '3', '1']);
	expect(await txnCount(page)).toBe(1);
	expect(JSON.parse((await lastTxn(page).textContent())!)).toEqual([
		{ op: 'move_choice', params: { owner: 'q_mood', value: 1, index: 2 } }
	]);
	await expect(page.getByTestId('announcer')).toHaveText('Moved Good to position 3 of 3');
});

test('Escape cancels a drag', async ({ page }) => {
	const editor = await open(page);
	const h = (await editor.getByRole('button', { name: 'Move Bad' }).boundingBox())!;
	await page.mouse.move(h.x + 5, h.y + 5);
	await page.mouse.down();
	await page.mouse.move(h.x + 5, h.y - 80, { steps: 6 });
	await page.keyboard.press('Escape');
	await page.mouse.up();
	expect(await codes(editor)).toEqual(['1', '2', '3']);
	expect(await txnCount(page)).toBe(0);
});

test('Alt+↑/↓ reorders from the keyboard and keeps focus', async ({ page }) => {
	const editor = await open(page);
	const label = editor.getByLabel('Label for choice 1');
	await label.focus();
	await page.keyboard.press('Alt+ArrowDown');
	expect(await labelsOf(editor)).toEqual(['Okay', 'Good', 'Bad']);
	await expect(editor.getByLabel('Label for choice 2')).toBeFocused();
	await page.keyboard.press('Alt+ArrowDown');
	expect(await labelsOf(editor)).toEqual(['Okay', 'Bad', 'Good']);
	await expect(editor.getByLabel('Label for choice 3')).toBeFocused();
	// At the bottom edge: nothing is sent.
	await page.keyboard.press('Alt+ArrowDown');
	expect(await txnCount(page)).toBe(2);
	// From the handle too.
	await editor.getByRole('button', { name: 'Move Good' }).focus();
	await page.keyboard.press('Alt+ArrowUp');
	expect(await labelsOf(editor)).toEqual(['Okay', 'Good', 'Bad']);
	await expect(editor.getByRole('button', { name: 'Move Good' })).toBeFocused();
	expect(JSON.parse((await lastTxn(page).textContent())!)).toEqual([
		{ op: 'move_choice', params: { owner: 'q_mood', value: 1, index: 1 } }
	]);
});

test('bulk paste: preview, then one bulk_paste_choices', async ({ page }) => {
	const editor = await open(page);
	await editor.getByRole('button', { name: 'Paste list…' }).click();
	const box = editor.getByLabel('One choice per line');
	await expect(box).toBeFocused();
	await box.fill('1 Strongly disagree\n2 Disagree\n3 Neither\n4 Agree\n5 Strongly agree');
	const preview = editor.getByRole('table', { name: 'Preview' });
	await expect(preview.locator('tbody tr')).toHaveCount(5);
	await expect(preview.locator('tbody tr').first()).toContainText('Strongly disagree');
	await editor.getByRole('button', { name: 'Replace with 5 choices' }).click();
	expect(await labelsOf(editor)).toEqual(['Strongly disagree', 'Disagree', 'Neither', 'Agree', 'Strongly agree']);
	expect(await txnCount(page)).toBe(1);
	const [op] = JSON.parse((await lastTxn(page).textContent())!);
	expect(op).toEqual({
		op: 'bulk_paste_choices',
		params: { owner: 'q_mood', mode: 'replace', text: '1\tStrongly disagree\n2\tDisagree\n3\tNeither\n4\tAgree\n5\tStrongly agree' }
	});
	await expect(editor.getByRole('button', { name: 'Paste list…' })).toBeFocused();
});

test('bulk paste: bare labels are auto-coded on append; duplicates block apply', async ({ page }) => {
	const editor = await open(page);
	await editor.getByRole('button', { name: 'Paste list…' }).click();
	await editor.getByRole('radio', { name: 'Add to the end' }).check();
	const box = editor.getByLabel('One choice per line');
	await box.fill('Terrible\n2\tOkay again');
	await expect(editor.getByText('Code 2 is already in the list.')).toBeVisible();
	await expect(editor.getByRole('button', { name: 'Add 2 choices' })).toBeDisabled();
	await box.fill('Terrible\nAwful');
	await editor.getByRole('button', { name: 'Add 2 choices' }).click();
	expect(await codes(editor)).toEqual(['1', '2', '3', '4', '5']);
	expect(await labelsOf(editor)).toEqual(['Good', 'Okay', 'Bad', 'Terrible', 'Awful']);
});

test('codes are validated as you type and never sent while invalid', async ({ page }) => {
	const editor = await open(page);
	const code = editor.getByLabel('Code for choice 3');
	await code.fill('1');
	await expect(code).toHaveAttribute('aria-invalid', 'true');
	await expect(code).toHaveAccessibleDescription('Code 1 is used more than once.');
	await expect(editor.getByLabel('Code for choice 1')).toHaveAttribute('aria-invalid', 'true');
	await code.fill('b a');
	await expect(code).toHaveAccessibleDescription('Codes cannot contain spaces.');
	await code.press('Enter');
	await code.blur();
	expect(await txnCount(page)).toBe(0);
	await code.fill('bad');
	await code.press('Enter');
	expect(JSON.parse((await lastTxn(page).textContent())!)).toEqual([
		{ op: 'set_choice', params: { owner: 'q_mood', value: 3, new_value: 'bad' } }
	]);
	expect(await codes(editor)).toEqual(['1', '2', 'bad']);
	await expect(editor.getByLabel('Code for choice 3')).toBeFocused();
	await expect(editor.getByText('This list mixes number and text codes.')).toBeVisible();
});

test('server diagnostics are shown on the row', async ({ page }) => {
	const editor = await open(page);
	await editor.getByRole('button', { name: 'Delete Okay' }).click();
	await expect(editor.locator('[data-row][data-index="1"]')).toContainText('A condition compares q_mood with code 2');
	expect(await codes(editor)).toEqual(['1', '2', '3']);
	await editor.getByRole('button', { name: 'Delete Bad' }).click();
	expect(await codes(editor)).toEqual(['1', '2']);
	await expect(editor.getByText('A condition compares')).toHaveCount(0);
});

test('add, duplicate and label edits', async ({ page }) => {
	const editor = await open(page);
	await editor.getByRole('button', { name: 'Duplicate Good' }).click();
	expect(await codes(editor)).toEqual(['1', '4', '2', '3']);
	await expect(editor.getByLabel('Label for choice 2')).toBeFocused();
	await editor.getByRole('button', { name: 'Add choice' }).click();
	await expect(editor.getByLabel('Label for choice 5')).toBeFocused();
	await page.keyboard.type('Unsure');
	await page.keyboard.press('Enter');
	expect(JSON.parse((await lastTxn(page).textContent())!)).toEqual([
		{ op: 'set_choice', params: { owner: 'q_mood', value: 5, label: 'Unsure' } }
	]);
	expect(await labelsOf(editor)).toEqual(['Good', 'Good', 'Okay', 'Bad', 'Unsure']);
});

test('shared lists: usage, switch, make shared, separate copy', async ({ page }) => {
	const editor = await open(page);
	await page.getByRole('radio', { name: 'q_work' }).check();
	await expect(editor.getByTestId('shared-status')).toContainText('Shared list agree5, used by 2 questions');
	// An edit to a shared list targets the list.
	await editor.getByLabel('Label for choice 3').fill('Neutral');
	await editor.getByLabel('Label for choice 3').press('Enter');
	expect(JSON.parse((await lastTxn(page).textContent())!)[0].params.owner).toBe('agree5');

	await editor.getByRole('button', { name: 'Use a separate copy' }).click();
	await expect(editor.getByTestId('shared-status')).toContainText('belong to this question only');
	expect(await labelsOf(editor)).toContain('Neutral');

	await editor.getByRole('button', { name: 'Make shared…' }).click();
	await expect(editor.getByLabel('New list id')).toHaveValue('q_work_choices');
	await editor.getByLabel('New list id').fill('agree5');
	await expect(editor.getByText('A list called agree5 already exists.')).toBeVisible();
	await editor.getByLabel('New list id').fill('work_agree');
	await editor.getByRole('button', { name: 'Share', exact: true }).click();
	await expect(editor.getByTestId('shared-status')).toContainText('Shared list work_agree, used by 1 question.');
	expect(JSON.parse((await lastTxn(page).textContent())!).map((o: { op: string }) => o.op)).toEqual([
		'create_choice_list',
		'set_property',
		'set_property'
	]);

	await editor.getByRole('combobox', { name: /Switch to another list/ }).click();
	await page.getByRole('option', { name: /^yesno/ }).click();
	await editor.getByRole('button', { name: 'Use list' }).click();
	await expect(editor.getByTestId('shared-status')).toContainText('Shared list yesno, used by 2 questions');
	expect(await labelsOf(editor)).toEqual(['Yes', 'No']);
});

test('changing a code on a published survey asks first', async ({ page }) => {
	const editor = await open(page);
	await page.getByRole('checkbox', { name: 'Survey has published versions' }).check();
	const code = editor.getByLabel('Code for choice 1');
	await code.fill('10');
	await code.press('Enter');
	const dialog = page.getByRole('dialog', { name: 'Change a code with data behind it?' });
	await expect(dialog).toBeVisible();
	await expect(dialog).toContainText('2 published versions');
	await dialog.getByRole('button', { name: 'Keep code 1' }).click();
	await expect(dialog).toBeHidden();
	await expect(code).toHaveValue('1');
	expect(await txnCount(page)).toBe(0);

	await code.fill('10');
	await code.press('Enter');
	await dialog.getByRole('button', { name: 'Change to 10' }).click();
	expect(await codes(editor)).toEqual(['10', '2', '3']);
	expect(await txnCount(page)).toBe(1);
	// Labels never ask.
	await editor.getByLabel('Label for choice 2').fill('Fine');
	await editor.getByLabel('Label for choice 2').press('Enter');
	await expect(dialog).toBeHidden();
	expect(await txnCount(page)).toBe(2);
});

test('dialog wrapper opens from "Edit choices…" and is axe-clean', async ({ page }) => {
	await open(page);
	await page.getByRole('button', { name: 'Edit choices…' }).click();
	const dialog = page.getByRole('dialog', { name: 'Edit choices' });
	await expect(dialog).toBeVisible();
	await expect(dialog).toContainText('How do you feel today?');
	await dialog.getByLabel('Label for choice 1').focus();
	await page.keyboard.press('Alt+ArrowDown');
	await expect(dialog.getByLabel('Label for choice 1')).toHaveValue('Okay');
	expect(await axe(page)).toEqual([]);
	await dialog.getByRole('button', { name: 'Done' }).click();
	await expect(dialog).toBeHidden();
	await expect(page.getByRole('button', { name: 'Edit choices…' })).toBeFocused();
});
