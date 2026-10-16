import { axe, expect, focused, test } from './fixtures';

test.describe('layout', () => {
	test('top bar and three panes with mock data', async ({ shell: page }) => {
		const banner = page.getByRole('banner');
		await expect(banner.getByRole('heading', { level: 1 })).toHaveText(/Sleep and study habits/);
		await expect(banner.getByRole('status').first()).toHaveText(/All changes saved/);
		for (const name of ['Undo', 'Redo', 'Command palette', 'Switch to dark theme']) {
			await expect(banner.getByRole('button', { name, exact: true })).toBeVisible();
		}
		await expect(banner.getByRole('button', { name: 'Preview' })).toBeVisible();

		await expect(page.getByRole('complementary', { name: 'Outline' })).toBeVisible();
		await expect(page.getByRole('main', { name: 'Canvas' })).toBeVisible();
		await expect(page.getByRole('complementary', { name: 'Properties' })).toBeVisible();

		await expect(page.getByRole('treeitem')).toHaveCount(15);
		await expect(page.getByRole('main').getByRole('button', { name: /Hours of sleep/ })).toBeVisible();
		await expect(page.getByText('Select an item in the outline')).toBeVisible();
	});

	test('panes resize with the keyboard and the pointer', async ({ shell: page }) => {
		const outline = page.getByRole('complementary', { name: 'Outline' });
		const sep = page.getByRole('separator', { name: 'Resize outline pane' });
		await expect(sep).toHaveAttribute('aria-valuenow', '280');
		await sep.focus();
		await page.keyboard.press('ArrowRight');
		await page.keyboard.press('ArrowRight');
		await expect(sep).toHaveAttribute('aria-valuenow', '312');
		expect((await outline.boundingBox())?.width).toBeCloseTo(312, 0);
		await page.keyboard.press('Home');
		await expect(sep).toHaveAttribute('aria-valuenow', '200');

		const props = page.getByRole('separator', { name: 'Resize properties pane' });
		const box = (await props.boundingBox())!;
		await page.mouse.move(box.x + box.width / 2, box.y + 200);
		await page.mouse.down();
		await page.mouse.move(box.x + box.width / 2 - 60, box.y + 200, { steps: 4 });
		await page.mouse.up();
		await expect(props).toHaveAttribute('aria-valuenow', '380');
	});

	test('panes collapse at narrow widths and open as overlays', async ({ shell: page }) => {
		await page.setViewportSize({ width: 900, height: 700 });
		await expect(page.getByRole('complementary', { name: 'Properties' })).toBeHidden();
		await expect(page.getByRole('complementary', { name: 'Outline' })).toBeVisible();
		const propsToggle = page.getByRole('button', { name: 'Properties pane' });
		await expect(propsToggle).toHaveAttribute('aria-expanded', 'false');
		await propsToggle.click();
		await expect(propsToggle).toHaveAttribute('aria-expanded', 'true');
		await expect(page.getByRole('complementary', { name: 'Properties' })).toBeVisible();

		await page.setViewportSize({ width: 600, height: 700 });
		await expect(page.getByRole('complementary', { name: 'Outline' })).toBeHidden();
		await page.getByRole('button', { name: 'Outline pane' }).click();
		await expect(page.getByRole('complementary', { name: 'Outline' })).toBeVisible();
		// Opening one overlay closes the other.
		await expect(page.getByRole('complementary', { name: 'Properties' })).toBeHidden();
		await page.getByRole('tree').getByRole('treeitem').first().click();
		await page.keyboard.press('Escape');
		await expect(page.getByRole('complementary', { name: 'Outline' })).toBeHidden();
		expect(await axe(page)).toEqual([]);
	});
});

test.describe('command palette and shortcuts', () => {
	test('Ctrl/Cmd+K opens the palette; a chosen command runs through the registry', async ({
		shell: page
	}) => {
		const opener = page.getByRole('button', { name: 'Undo', exact: true });
		await opener.focus();
		await page.keyboard.press('ControlOrMeta+k');
		const dialog = page.getByRole('dialog', { name: 'Command palette' });
		await expect(dialog).toBeVisible();
		await expect(dialog.getByRole('combobox', { name: 'Commands' })).toBeFocused();
		await expect(dialog.getByRole('option', { name: /Focus next pane/ })).toBeVisible();
		expect(await axe(page)).toEqual([]);

		await page.keyboard.type('dark theme');
		await expect(dialog.getByRole('option')).toHaveCount(1);
		await page.keyboard.press('Enter');
		await expect(dialog).toBeHidden();
		await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
		await expect(opener).toBeFocused();

		// Escape closes; Ctrl/Cmd+K toggles.
		await page.keyboard.press('ControlOrMeta+k');
		await expect(dialog).toBeVisible();
		await page.keyboard.press('Escape');
		await expect(dialog).toBeHidden();
		await page.keyboard.press('ControlOrMeta+k');
		await expect(dialog).toBeVisible();
		await page.keyboard.press('ControlOrMeta+k');
		await expect(dialog).toBeHidden();
	});

	test('undo/redo shortcuts and buttons dispatch through the registry', async ({ shell: page }) => {
		const toasts = page.getByRole('region', { name: 'Notifications' });
		await page.getByRole('main').click({ position: { x: 5, y: 5 } });
		await page.keyboard.press('ControlOrMeta+z');
		await expect(toasts).toContainText('Undo: nothing to undo yet');
		await page.keyboard.press('ControlOrMeta+Shift+z');
		await expect(toasts).toContainText('Redo: nothing to redo yet');
		await page.getByRole('button', { name: 'Undo', exact: true }).click();
		await expect(toasts.getByRole('listitem')).toHaveCount(3);
	});

	test('F6 and Shift+F6 cycle focus between panes', async ({ shell: page }) => {
		await page.locator('body').click({ position: { x: 1, y: 799 } });
		const order = [
			['topbar', page.getByRole('banner')],
			['outline', page.getByRole('treeitem').first()],
			['canvas', page.getByRole('main').getByRole('button').first()],
			['properties', page.getByRole('heading', { name: 'Properties' })]
		] as const;
		for (const [, target] of order) {
			await page.keyboard.press('F6');
			if (target === order[0][1]) {
				await expect(focused(page)).toHaveCount(1);
				expect(await focused(page).evaluate((el) => !!el.closest('[data-pane="topbar"]'))).toBe(
					true
				);
			} else {
				await expect(target).toBeFocused();
			}
		}
		await page.keyboard.press('F6');
		expect(await focused(page).evaluate((el) => !!el.closest('[data-pane="topbar"]'))).toBe(true);
		await page.keyboard.press('Shift+F6');
		await expect(page.getByRole('heading', { name: 'Properties' })).toBeFocused();
		await page.keyboard.press('Shift+F6');
		await expect(page.getByRole('main').getByRole('button').first()).toBeFocused();
	});
});

test.describe('outline', () => {
	test('arrow keys move a roving tabindex and selection follows', async ({ shell: page }) => {
		const tree = page.getByRole('tree', { name: 'Survey outline' });
		const item = (name: string) => tree.getByRole('treeitem', { name, exact: false }).first();
		const details = page.getByTestId('selected-details');

		await page.keyboard.press('F6');
		await page.keyboard.press('F6');
		await expect(item('Welcome')).toBeFocused();
		await expect(tree.locator('[tabindex="0"]')).toHaveCount(1);

		await page.keyboard.press('ArrowDown');
		await expect(item('Introduction')).toBeFocused();
		await expect(item('Introduction')).toHaveAttribute('aria-selected', 'true');
		await expect(details).toContainText('b_intro');
		await expect(details).toContainText('block');

		await page.keyboard.press('ArrowDown');
		await expect(item('About this study')).toBeFocused();
		await expect(details).toContainText('q_info');
		await expect(details).toContainText('question');

		await page.keyboard.press('ArrowLeft'); // to parent block
		await expect(item('Introduction')).toBeFocused();
		await page.keyboard.press('ArrowLeft'); // collapse block
		await expect(item('Introduction')).toHaveAttribute('aria-expanded', 'false');
		await expect(tree.getByRole('treeitem', { name: 'About this study' })).toHaveCount(0);
		await page.keyboard.press('ArrowRight'); // expand
		await expect(item('Introduction')).toHaveAttribute('aria-expanded', 'true');
		await page.keyboard.press('ArrowRight'); // first child
		await expect(item('About this study')).toBeFocused();

		await page.keyboard.press('End');
		await expect(item('Anything else')).toBeFocused();
		await page.keyboard.press('Home');
		await expect(item('Welcome')).toBeFocused();
		await expect(tree.locator('[tabindex="0"]')).toHaveCount(1);

		// Tab leaves the tree in one step (roving tabindex).
		await page.keyboard.press('Tab');
		expect(await focused(page).evaluate((el) => !!el.closest('[role="tree"]'))).toBe(false);
	});

	test('selecting on the canvas updates outline and properties', async ({ shell: page }) => {
		await page.getByRole('main').getByRole('button', { name: /Where do you usually study/ }).click();
		await expect(
			page.getByRole('treeitem', { name: /Where do you usually study/ })
		).toHaveAttribute('aria-selected', 'true');
		await expect(page.getByTestId('selected-details')).toContainText('q_study_place');
		await page.getByRole('tab', { name: 'Diagnostics' }).click();
		await expect(page.getByText('No diagnostics')).toBeVisible();
	});
});

test.describe('theme', () => {
	test('follows the OS, and the toggle overrides it', async ({ shell: page }) => {
		await page.emulateMedia({ colorScheme: 'dark' });
		await expect(page.getByRole('button', { name: 'Switch to light theme' })).toBeVisible();
		await page.getByRole('button', { name: 'Switch to light theme' }).click();
		await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
		await page.reload();
		await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
	});
});

for (const scheme of ['light', 'dark'] as const) {
	test.describe(`${scheme} theme`, () => {
		test.use({ colorScheme: scheme });

		test('axe-core reports no violations', async ({ shell: page }) => {
			expect(await axe(page)).toEqual([]);
			await page.getByRole('main').getByRole('button', { name: /Hours of sleep/ }).click();
			expect(await axe(page)).toEqual([]);
			await page.getByRole('button', { name: 'Preview' }).click();
			await expect(page.getByRole('dialog', { name: 'Preview' })).toBeVisible();
			expect(await axe(page)).toEqual([]);
		});

		test('visual snapshot', async ({ shell: page }) => {
			await page.getByRole('main').getByRole('button', { name: /Hours of sleep/ }).click();
			await page.mouse.move(0, 0);
			await expect(page).toHaveScreenshot(`shell-${scheme}.png`);
		});
	});
}
