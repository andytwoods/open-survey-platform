import { expect, test, type Locator, type Page } from '@playwright/test';
import { serveExpressions, startBridge } from './expr-bridge';
import { axe, focused } from './fixtures';

// Condition builder (/dev/conditions, task B7). The parse/print endpoints are answered by
// osp-api's own functions (expr_bridge.py), so text ⇄ AST here is the real osp_expr.
const EXAMPLE = '(age >= 18 and contains(colours, "red")) or not answered(q3)';
const CANONICAL = 'age >= 18 and contains(colours, "red") or not answered(q3)';
const EXAMPLE_AST = {
	kind: 'or',
	args: [
		{
			kind: 'and',
			args: [
				{ kind: 'compare', op: '>=', left: { kind: 'ref', id: 'age' }, right: { kind: 'int', value: 18 } },
				{ kind: 'contains', ref: { kind: 'ref', id: 'colours' }, value: { kind: 'text', value: 'red' } }
			]
		},
		{ kind: 'not', arg: { kind: 'answered', ref: { kind: 'ref', id: 'q3' } } }
	]
};

async function open(page: Page, preset = 'empty') {
	await startBridge();
	const log = await serveExpressions(page);
	await page.goto(`/dev/conditions?preset=${preset}`);
	await expect(page.getByRole('heading', { level: 1, name: 'Condition builder' })).toBeVisible();
	return log;
}

const builder = (page: Page) => page.getByTestId('condition-builder').first();
const root = (page: Page) => builder(page).getByTestId('condition-root');
const textView = (page: Page) => builder(page).locator('.cm-content');

/** The row's controls, by role. */
function row(scope: Locator, n: number) {
	const r = scope.getByTestId('condition-row').nth(n);
	return {
		self: r,
		question: r.locator('[data-role="question"]'),
		operator: r.locator('[data-role="operator"]'),
		value: r.locator('[data-role="value"]')
	};
}

async function expectApplyReady(page: Page) {
	await expect(builder(page).getByTestId('condition-apply')).not.toHaveAttribute('aria-disabled', 'true');
}

async function expectExampleTextAndApply(page: Page) {
	await expectApplyReady(page);
	await builder(page).getByTestId('view-text').click();
	await expect(textView(page)).toHaveText(CANONICAL);
	await builder(page).getByTestId('condition-apply').click();
	const ops = JSON.parse((await page.getByTestId('ops-log').textContent()) ?? '[]');
	expect(ops).toEqual([{ op: 'set_condition', params: { target: 'q_target', condition: EXAMPLE_AST } }]);
}

test('build the example with the mouse; the text view matches', async ({ page }) => {
	await open(page);
	await root(page).locator('[data-role="mode"]').first().selectOption('any');

	await root(page).locator('[data-role="add-group"]').last().click();
	const group = root(page).getByTestId('condition-group');
	const r0 = row(group, 0);
	await r0.question.selectOption('age');
	await r0.operator.selectOption({ label: 'at least (≥)' });
	await r0.value.click();
	await r0.value.fill('18');

	await group.locator('[data-role="add-row"]').click();
	const r1 = row(group, 1);
	await r1.question.selectOption('colours');
	await expect(r1.operator).toHaveValue('contains');
	await r1.value.selectOption({ label: 'Red' });

	await root(page).locator('[data-role="add-row"]').last().click();
	const r2 = row(root(page), 2);
	await r2.question.selectOption('q3');
	await r2.operator.selectOption({ label: 'is empty' });

	await expect(builder(page).getByTestId('condition-preview')).toHaveText(CANONICAL);
	await expectExampleTextAndApply(page);
});

test('build the example with the keyboard only', async ({ page }) => {
	await open(page);
	const mode = root(page).locator('[data-role="mode"]').first();
	await mode.focus();
	await chooseByKeyboard(page, mode, 'any');

	// Tab to "Add group" (after "Add condition") and press Enter: focus moves into the new row.
	await page.keyboard.press('Tab');
	await expect(focused(page)).toHaveAttribute('data-role', 'add-row');
	await page.keyboard.press('Tab');
	await expect(focused(page)).toHaveAttribute('data-role', 'add-group');
	await page.keyboard.press('Enter');
	const group = root(page).getByTestId('condition-group');
	const r0 = row(group, 0);
	await expect(r0.question).toBeFocused();
	await chooseByKeyboard(page, r0.question, 'age');
	await page.keyboard.press('Tab');
	await expect(r0.operator).toBeFocused();
	await chooseByKeyboard(page, r0.operator, 'ge');
	await page.keyboard.press('Tab');
	await expect(r0.value).toBeFocused();
	await page.keyboard.type('18');

	// Tab past the remove button to the group's "Add condition".
	await page.keyboard.press('Tab');
	await page.keyboard.press('Tab');
	await expect(focused(page)).toHaveAttribute('data-role', 'add-row');
	await page.keyboard.press('Enter');
	const r1 = row(group, 1);
	await expect(r1.question).toBeFocused();
	await chooseByKeyboard(page, r1.question, 'colours');
	await page.keyboard.press('Tab');
	await expect(r1.operator).toHaveValue('contains');
	await page.keyboard.press('Tab');
	await expect(r1.value).toBeFocused();
	await chooseByKeyboard(page, r1.value, 'red');

	// Out of the nested group to the root's "Add condition".
	await page.keyboard.press('Tab'); // remove row
	await page.keyboard.press('Tab'); // group: add condition
	await page.keyboard.press('Tab'); // group: add group
	await page.keyboard.press('Tab'); // root: add condition
	await expect(focused(page)).toHaveAccessibleName('Add condition to condition');
	await page.keyboard.press('Enter');
	const r2 = row(root(page), 2);
	await expect(r2.question).toBeFocused();
	await chooseByKeyboard(page, r2.question, 'q3');
	await page.keyboard.press('Tab');
	await chooseByKeyboard(page, r2.operator, 'not_answered');

	await expectExampleTextAndApply(page);
});

test('editing the text updates the tree; errors are underlined', async ({ page }) => {
	await open(page);
	await builder(page).getByTestId('view-text').click();
	const editor = textView(page);
	await editor.click();
	await page.keyboard.type(EXAMPLE);
	await expect(builder(page).getByTestId('condition-apply')).not.toHaveAttribute('aria-disabled', 'true');
	await builder(page).getByTestId('view-tree').click();
	await expect(root(page)).toHaveAttribute('data-mode', 'any');
	const group = root(page).getByTestId('condition-group');
	await expect(row(group, 0).question).toHaveValue('age');
	await expect(row(group, 0).operator).toHaveValue('ge');
	await expect(row(group, 0).value).toHaveValue('18');
	await expect(row(group, 1).value).toHaveValue('red');
	await expect(row(root(page), 2).operator).toHaveValue('not_answered');

	// Change the text: the tree follows.
	await builder(page).getByTestId('view-text').click();
	await editor.click();
	await page.keyboard.press('ControlOrMeta+a');
	await page.keyboard.type('pet == 1 and contains(colours, "blue") and age >= 21');
	await expectApplyReady(page);
	await builder(page).getByTestId('view-tree').click();
	await expect(root(page)).toHaveAttribute('data-mode', 'all');
	await expect(root(page).getByTestId('condition-group')).toHaveCount(0);
	await expect(row(root(page), 0).question).toHaveValue('pet');
	await expect(row(root(page), 0).value).toHaveValue('1');
	await expect(row(root(page), 1).value).toHaveValue('blue');
	await expect(row(root(page), 2).value).toHaveValue('21');

	// A syntax error: underlined at its position, explained, Apply blocked, tree kept.
	await builder(page).getByTestId('view-text').click();
	await editor.click();
	await page.keyboard.press('ControlOrMeta+a');
	await page.keyboard.type('age >= 18 andd q3');
	await expect(builder(page).locator('.cm-lintRange-error')).toHaveText('andd');
	await expect(builder(page).getByTestId('condition-diagnostics')).toContainText('unexpected');
	await expect(builder(page).getByTestId('condition-apply')).toHaveAttribute('aria-disabled', 'true');
	await builder(page).getByTestId('view-tree').click();
	await expect(builder(page).getByText('Fix the errors in the text before switching')).toBeVisible();
	await expect(textView(page)).toBeVisible();
});

test('too complex for the visual editor falls back to text', async ({ page }) => {
	await open(page, 'complex');
	await expect(builder(page).getByTestId('too-complex')).toHaveText(
		'This condition is too complex for the visual editor; edit as text.'
	);
	await expect(textView(page)).toHaveText('age + 1 > 30');
	// "Visual" is aria-disabled (still focusable, explains itself): force past Playwright's check.
	await builder(page).getByTestId('view-tree').click({ force: true });
	await expect(textView(page)).toBeVisible();
	// Simplify it: the visual editor becomes available again.
	await textView(page).click();
	await page.keyboard.press('ControlOrMeta+a');
	await page.keyboard.type('age > 29');
	await expectApplyReady(page);
	await expect(builder(page).getByTestId('too-complex')).toHaveCount(0);
	await builder(page).getByTestId('view-tree').click();
	await expect(row(root(page), 0).operator).toHaveValue('gt');
});

test('warns about deleted and later questions', async ({ page }) => {
	await open(page, 'deleted');
	const gone = row(root(page), 1);
	await expect(gone.question).toHaveValue('q_gone');
	await expect(gone.self.locator('[data-kind="unknown-question"]')).toContainText('no longer exists');

	await page.getByTestId('preset').selectOption('forward');
	await expect(row(root(page), 0).self.locator('[data-code="ref.forward"]')).toContainText(
		"'later' comes later in the flow"
	);
});

test('"excludes" on an optional question offers "also require answered"', async ({ page }) => {
	await open(page, 'excludes');
	const warning = root(page).locator('[data-kind="may-be-unanswered"]');
	await expect(warning).toContainText('did not answer “colours”');
	await warning.getByRole('button', { name: 'Also require answered' }).click();
	await expect(warning).toHaveCount(0);
	await expectApplyReady(page);
	await expect(builder(page).getByTestId('condition-preview')).toHaveText(
		'answered(colours) and not contains(colours, "red")'
	);
});

test('the dialog applies one op and closes', async ({ page }) => {
	await open(page, 'forward');
	await page.getByRole('button', { name: 'Edit condition…' }).click();
	const dialog = page.getByRole('dialog', { name: 'Edit condition for “Tell us more”' });
	await expect(dialog).toBeVisible();
	const r0 = row(dialog, 0);
	await r0.question.selectOption('age');
	await r0.value.fill('40');
	await expect(dialog.getByTestId('condition-apply')).not.toHaveAttribute('aria-disabled', 'true');
	await dialog.getByTestId('condition-apply').click();
	await expect(dialog).toBeHidden();
	const ops = JSON.parse((await page.getByTestId('ops-log').textContent()) ?? '[]');
	expect(ops[0].params.condition).toEqual({
		kind: 'compare',
		op: '>',
		left: { kind: 'ref', id: 'age' },
		right: { kind: 'int', value: 40 }
	});
});

for (const scheme of ['light', 'dark'] as const) {
	test.describe(`axe, ${scheme}`, () => {
		test.use({ colorScheme: scheme });
		test('tree view with warnings is axe-clean', async ({ page }) => {
			await open(page, 'deleted');
			await expect(root(page).locator('[data-kind="unknown-question"]')).toBeVisible();
			await page.getByTestId('preset').selectOption('excludes');
			await expect(root(page).locator('[data-kind="may-be-unanswered"]')).toBeVisible();
			expect(await axe(page)).toEqual([]);
		});
		test('text view with an error is axe-clean', async ({ page }) => {
			await open(page);
			await builder(page).getByTestId('view-text').click();
			await textView(page).click();
			await page.keyboard.type('age >=');
			await expect(builder(page).locator('.cm-lintRange-error')).toHaveCount(1);
			expect(await axe(page)).toEqual([]);
		});
	});
}

/** Pick an option of a focused native select with the keyboard (type-ahead on its label). */
async function chooseByKeyboard(page: Page, select: Locator, value: string) {
	await expect(select).toBeFocused();
	const label = await select.locator(`option[value="${value}"]`).textContent();
	await page.keyboard.type(label ?? '');
	await expect(select).toHaveValue(value);
}
