import AxeBuilder from '@axe-core/playwright';
import { expect, test, type FrameLocator, type Locator, type Page } from '@playwright/test';

// The serverless Pages demo (task DEMO2) against its static build, served by a plain static
// file server (serve.mjs) at the Pages path. Every /api request is aborted and counted: the
// demo must never make one. Everything below runs on the in-memory backend
// (src/lib/demo/): @osp/ops edits, @osp/spec diagnostics, @osp/engine plans.

const DEMO = '/open-survey-platform/demo/';

async function offline(page: Page): Promise<string[]> {
	const blocked: string[] = [];
	await page.route('**/api/**', (route) => {
		blocked.push(route.request().url());
		return route.abort();
	});
	// Anything not served by the static server is a bug too (no CDN, no fonts from afar).
	const origin = new URL(test.info().project.use.baseURL ?? 'http://127.0.0.1').origin;
	page.on('request', (r) => {
		const u = new URL(r.url());
		if ((u.protocol === 'http:' || u.protocol === 'https:') && u.origin !== origin) blocked.push(r.url());
	});
	return blocked;
}

async function axe(page: Page) {
	await page.mouse.move(0, 0);
	await expect(page.locator('.osp-tooltip')).toHaveCount(0);
	const results = await new AxeBuilder({ page })
		.withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'])
		.analyze();
	return results.violations.map((v) => ({ id: v.id, help: v.help, targets: v.nodes.map((n) => n.target.join(' ')) }));
}

const tree = (page: Page) => page.getByRole('tree', { name: 'Survey outline' });
const item = (page: Page, name: string) => tree(page).getByRole('treeitem', { name, exact: true });
const saveState = (page: Page) => page.getByRole('banner').getByRole('status').first();

async function fillRich(page: Page, field: Locator, text: string) {
	await expect(field).toHaveAttribute('role', 'textbox');
	await field.click();
	await expect(field).toHaveAttribute('contenteditable', 'true');
	await expect(field).toBeFocused();
	await page.mouse.move(0, 0);
	await page.keyboard.press('ControlOrMeta+a');
	await page.keyboard.press('Backspace');
	await page.keyboard.type(text);
}

async function openEditor(page: Page) {
	await page.goto(DEMO);
	await expect(page.getByTestId('demo-banner')).toContainText('runs entirely in your browser; changes vanish when you reload');
	await expect(page.getByRole('banner').getByRole('heading', { level: 1 })).toHaveText('Coffee and focus');
	await expect(item(page, 'How old are you?')).toBeVisible();
	await expect(saveState(page)).toHaveText(/All changes saved/);
}

/** Answer the demo study as a coffee drinker, through to its "complete" ending. */
async function runStudy(s: Page | FrameLocator) {
	const next = () => s.getByRole('button', { name: /^(Next|Submit|Finish)/ }).first();
	await s.getByRole('button', { name: 'I agree to take part' }).click();
	await s.getByRole('textbox', { name: /How old are you/ }).fill('34');
	await s.getByRole('radio', { name: 'Yes' }).check();
	await next().click();

	const cups = s.getByRole('slider', { name: /How many cups/ });
	await expect(cups).toBeVisible();
	await s.getByRole('group', { name: /How many cups/ }).getByRole('textbox', { name: 'Or type a number' }).fill('2');
	// Show-if: the follow-ups appear once cups > 0.
	await s.getByRole('checkbox', { name: 'With milk' }).check();
	await next().click();

	// The randomiser shows Focus and Sleep in either order.
	for (let k = 0; k < 2; k++) {
		const grid = s.getByRole('radiogroup', { name: 'Reading' });
		const sleep = s.getByRole('slider', { name: /How many hours did you sleep/ });
		await expect(grid.or(sleep)).toBeVisible();
		if (await grid.isVisible()) {
			for (const row of ['Reading', 'Email and messages', 'Deep work']) {
				await s.getByRole('radiogroup', { name: row }).getByRole('radio', { name: 'Good' }).click();
			}
		} else {
			await s.getByRole('group', { name: /How many hours did you sleep/ }).getByRole('textbox', { name: 'Or type a number' }).fill('7.5');
		}
		await next().click();
	}

	// Piping: the cups answer and the computed caffeine.
	await expect(s.getByText('You had 2 cups yesterday: roughly 190 mg of caffeine.')).toBeVisible();
	await next().click();
	await expect(s.getByRole('heading', { name: 'Thank you!' })).toBeVisible();
}

test('the builder edits the study with no server', async ({ page }) => {
	const blocked = await offline(page);
	await openEditor(page);
	expect(await axe(page)).toEqual([]);

	// Edit a question's text (set_property through @osp/ops).
	await item(page, 'How old are you?').click();
	const field = page.getByLabel('Question text');
	await fillRich(page, field, 'What is your age?');
	await page.keyboard.press('Tab');
	await expect(item(page, 'What is your age?')).toBeVisible();
	await expect(saveState(page)).toHaveText(/All changes saved/);

	// Add a question by clicking a type in the toolbox: it lands after the selection.
	await page.getByRole('button', { name: 'Add Text question' }).click();
	await expect(item(page, 'New question')).toBeVisible();

	// Undo and redo: inverses kept in the page.
	const undo = page.getByRole('banner').getByRole('button', { name: 'Undo', exact: true });
	const redo = page.getByRole('banner').getByRole('button', { name: 'Redo', exact: true });
	await undo.click();
	await expect(item(page, 'New question')).toHaveCount(0);
	await undo.click();
	await expect(item(page, 'How old are you?')).toBeVisible();
	await redo.click();
	await expect(item(page, 'What is your age?')).toBeVisible();
	await redo.click();
	await expect(item(page, 'New question')).toBeVisible();

	// Change a condition as text: "How do you take it?" shows if cups > 0; make it > 2.
	await item(page, 'How do you take it?').click();
	await page.getByRole('button', { name: 'Show if Edit condition…' }).click();
	const dialog = page.getByRole('dialog').filter({ hasText: 'How do you take it?' });
	await dialog.getByTestId('view-text').click();
	const text = dialog.getByRole('textbox', { name: 'Condition text' });
	await text.click();
	await page.keyboard.press('ControlOrMeta+a');
	await page.keyboard.type('cups > 2');
	await expect(dialog.getByTestId('condition-apply')).not.toHaveAttribute('aria-disabled', 'true');
	await dialog.getByTestId('condition-apply').click();
	await expect(dialog).toBeHidden();
	await expect(saveState(page)).toHaveText(/All changes saved/);
	await expect(page.getByRole('complementary', { name: /Properties/ }).getByText('cups > 2')).toBeVisible();

	// Switch the editing language: the German text is there to edit.
	await item(page, 'Do you drink coffee?').click();
	await page.getByLabel('Editing language').first().selectOption('de');
	await expect(page.getByLabel('Question text')).toHaveText('Trinken Sie Kaffee?');
	await page.getByLabel('Editing language').first().selectOption('en');

	// Publishing needs a server: a friendly message, not an error.
	await page.getByRole('banner').getByRole('button', { name: 'Publish' }).click();
	const publish = page.getByRole('dialog', { name: 'Publish' });
	await expect(publish).toContainText('Not available in the demo');
	await expect(publish).toContainText('Install Open Survey Platform to try this');
	expect(await axe(page)).toEqual([]);
	await publish.getByRole('button', { name: /Close/ }).first().click();

	// A reload starts from the prespecified study again.
	await page.reload();
	await expect(item(page, 'How old are you?')).toBeVisible();
	await expect(item(page, 'New question')).toHaveCount(0);

	expect(blocked).toEqual([]);
});

test('Preview runs the edited study to its ending', async ({ page }) => {
	const blocked = await offline(page);
	await openEditor(page);
	await page.getByRole('banner').getByRole('button', { name: 'Preview' }).click();
	await expect(page.getByRole('heading', { name: 'Preview', level: 2 })).toBeVisible();
	const phone = page.frameLocator('[data-testid="preview-frame-phone"]');
	await expect(phone.getByRole('heading', { name: 'Coffee and focus' })).toBeVisible();
	await runStudy(phone);
	expect(blocked).toEqual([]);
});

test('the Bank inserts a bundled instrument (generated from the Python packages)', async ({ page }) => {
	const blocked = await offline(page);
	await openEditor(page);
	await page.getByRole('button', { name: 'Bank', exact: true }).click();
	const pane = page.getByTestId('bank-pane');
	await pane.getByRole('searchbox', { name: 'Search the bank' }).fill('anxiety');
	const gad2 = pane.locator('[data-bank-result="gad2"]');
	await expect(gad2).toBeVisible();
	await item(page, 'How old are you?').click();
	await gad2.getByRole('button', { name: /^Insert / }).click();
	await expect(item(page, 'GAD-2')).toBeVisible();
	await expect(saveState(page)).toHaveText(/All changes saved/);
	expect(blocked).toEqual([]);
});

test('edits carry over between the demo pages and to Take the study', async ({ page }) => {
	const blocked = await offline(page);
	await openEditor(page);
	await item(page, 'How old are you?').click();
	await fillRich(page, page.getByLabel('Question text'), 'Your age, please');
	await page.keyboard.press('Tab');
	await expect(item(page, 'Your age, please')).toBeVisible();
	await expect(saveState(page)).toHaveText(/All changes saved/);
	await page.getByRole('navigation', { name: 'Builder views' }).getByRole('button', { name: 'Flow' }).click();
	await expect(page).toHaveURL(/\/demo\/flow\/\?survey=coffee-focus$/);
	await expect(page.getByRole('heading', { name: 'Branch: if age < 18' })).toBeVisible();
	expect(await axe(page)).toEqual([]);
	await page.getByRole('navigation', { name: 'Builder views' }).getByRole('button', { name: 'Questions' }).click();
	await expect(item(page, 'Your age, please')).toBeVisible();
	// "Take the study" runs the draft as edited here.
	await page.getByTestId('demo-banner').getByRole('link', { name: 'Take the study' }).click();
	await page.getByRole('button', { name: 'I agree to take part' }).click();
	await expect(page.getByRole('textbox', { name: /Your age, please/ })).toBeVisible();
	expect(blocked).toEqual([]);
});

test('Take the study: the participant app runs to the real ending', async ({ page }) => {
	const blocked = await offline(page);
	await page.goto(`${DEMO}take/`);
	await expect(page.getByRole('heading', { name: 'Coffee and focus' })).toBeVisible();
	expect(await axe(page)).toEqual([]);
	await runStudy(page);
	expect(await axe(page)).toEqual([]);
	expect(blocked).toEqual([]);
});

test('Take the study: a branch ends early, in German', async ({ page }) => {
	const blocked = await offline(page);
	await page.goto(`${DEMO}take/?lang=de`);
	await page.getByRole('button', { name: 'Ich bin einverstanden' }).click();
	await page.getByRole('textbox', { name: /Wie alt sind Sie/ }).fill('16');
	await page.getByRole('radio', { name: 'Nein' }).check();
	await page.getByRole('button', { name: 'Weiter' }).click();
	await expect(page.getByRole('heading', { name: 'Danke für Ihr Interesse' })).toBeVisible();
	expect(blocked).toEqual([]);
});

test.describe('at 320 px', () => {
	test.use({ viewport: { width: 320, height: 640 } });

	test('the builder and the study are usable', async ({ page }) => {
		const blocked = await offline(page);
		await page.goto(DEMO);
		await expect(page.getByTestId('demo-banner')).toBeVisible();
		await expect(page.getByRole('banner').getByRole('heading', { level: 1 })).toHaveText('Coffee and focus');
		const scroll = await page.evaluate(() => document.documentElement.scrollWidth);
		expect(scroll).toBeLessThanOrEqual(320);
		expect(await axe(page)).toEqual([]);

		await page.goto(`${DEMO}take/`);
		await runStudy(page);
		expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
		expect(blocked).toEqual([]);
	});
});
