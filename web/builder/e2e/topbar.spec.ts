import { expect, test, type Page } from '@playwright/test';
import { axe, signIn, test as mockTest } from './fixtures';

// The top bar at phone, tablet and desktop widths (task B17), against a real osp-api: every
// target is at least 44 x 44 px below 1024 px, nothing scrolls sideways, the less-used
// actions sit in an accessible "More actions" menu, Preview and Publish stay in the bar,
// shortcuts still work, and axe is clean in light and dark with and without a dialog open.

const banner = (page: Page) => page.getByRole('banner');
const more = (page: Page) => banner(page).getByRole('button', { name: 'More actions' });
const menu = (page: Page) => page.getByRole('menu');

async function openSurvey(page: Page, width: number) {
	await page.setViewportSize({ width, height: 800 });
	await signIn(page);
	await page.getByLabel('New survey title').fill(`Top bar ${width} ${Date.now()}`);
	await page.getByRole('button', { name: 'Create survey' }).click();
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	await page.waitForLoadState('load');
	await expect(page.getByRole('button', { name: /Add question to/ }).first()).toBeVisible();
	await expect(banner(page).getByRole('status').first()).toHaveText(/All changes saved/);
}

/** Every visible button in the top bar: name and box. */
async function targets(page: Page) {
	const out: { name: string; box: { x: number; y: number; width: number; height: number } }[] = [];
	for (const b of await banner(page).getByRole('button').all()) {
		if (!(await b.isVisible())) continue;
		const name = (await b.getAttribute('aria-label')) ?? (await b.innerText()).trim();
		out.push({ name, box: (await b.boundingBox())! });
	}
	return out;
}

async function noSideScroll(page: Page, width: number) {
	const sizes = await page.evaluate(() => {
		const bar = document.querySelector('[data-pane="topbar"]')!;
		return {
			doc: document.documentElement.scrollWidth,
			bar: bar.scrollWidth - bar.clientWidth
		};
	});
	expect(sizes.doc, 'no horizontal page scroll').toBeLessThanOrEqual(width);
	expect(sizes.bar, 'the top bar does not overflow').toBeLessThanOrEqual(0);
}

for (const width of [320, 375, 768, 1440]) {
	test(`${width} px: target sizes, no horizontal scroll, Preview and Publish in the bar`, async ({
		page
	}) => {
		await openSurvey(page, width);
		await noSideScroll(page, width);
		const min = width < 1024 ? 44 : 24;
		const all = await targets(page);
		for (const { name, box } of all) {
			expect(box.width, `${name} width`).toBeGreaterThanOrEqual(min);
			expect(box.height, `${name} height`).toBeGreaterThanOrEqual(min);
			expect(box.x, `${name} left edge`).toBeGreaterThanOrEqual(0);
			expect(box.x + box.width, `${name} right edge`).toBeLessThanOrEqual(width);
		}
		const names = all.map((t) => t.name);
		expect(names).toEqual(expect.arrayContaining(['Preview', 'Publish', 'Questions', 'Flow', 'Settings']));
		if (width < 1024) {
			expect(names).toContain('More actions');
			for (const moved of ['Undo', 'Redo', 'Command palette', 'Appearance']) expect(names).not.toContain(moved);
		} else {
			expect(names).not.toContain('More actions');
			expect(names).toEqual(expect.arrayContaining(['Undo', 'Redo', 'Command palette', 'Appearance']));
		}
	});

	for (const scheme of ['light', 'dark'] as const) {
		test(`${width} px, ${scheme}: axe-clean, alone and with a dialog open`, async ({ page }) => {
			await page.emulateMedia({ colorScheme: scheme });
			await openSurvey(page, width);
			expect(await axe(page)).toEqual([]);
			if (width < 1024) {
				await more(page).click();
				await expect(menu(page)).toBeVisible();
				expect(await axe(page)).toEqual([]);
				await page.keyboard.press('Escape');
				await expect(menu(page)).toBeHidden();
			}
			// The whole page, the top bar behind the overlay included.
			await page.getByRole('button', { name: /Add question to/ }).first().click();
			const dialog = page.getByRole('dialog', { name: 'Add a question' });
			await expect(dialog.getByRole('combobox', { name: 'Filter question types' })).toBeFocused();
			expect(await axe(page)).toEqual([]);
			await page.keyboard.press('Escape');
			await expect(dialog).toBeHidden();
		});
	}
}

test('More actions menu: keyboard, Escape and focus return; items run their commands', async ({
	page
}) => {
	await openSurvey(page, 375);
	const trigger = more(page);
	await trigger.focus();
	await page.keyboard.press('Enter');
	await expect(menu(page)).toBeVisible();
	const items = menu(page).getByRole('menuitem');
	await expect(items).toHaveText([
		/Command palette/,
		/Undo/,
		/Redo/,
		/Appearance/,
		/Panel profile/,
		/Results/,
		/Switch to (dark|light) theme/
	]);
	for (const item of await items.all()) {
		expect((await item.boundingBox())!.height).toBeGreaterThanOrEqual(44);
	}
	await expect(items.first()).toBeFocused();
	await page.keyboard.press('ArrowDown');
	await expect(items.nth(1)).toBeFocused();
	await page.keyboard.press('End');
	await expect(items.last()).toBeFocused();
	await page.keyboard.press('Escape');
	await expect(menu(page)).toBeHidden();
	await expect(trigger).toBeFocused();

	// The theme toggle from the menu, by keyboard; focus comes back to the trigger.
	const before = await page.evaluate(() => document.documentElement.dataset.theme ?? 'system');
	await page.keyboard.press('Enter');
	await expect(items.first()).toBeFocused(); // keys sent before the menu takes focus are lost
	const label = await items.last().innerText();
	await page.keyboard.press('End');
	await page.keyboard.press('Enter');
	await expect(menu(page)).toBeHidden();
	await expect(trigger).toBeFocused();
	const want = /dark/.test(label) ? 'dark' : 'light';
	await expect
		.poll(() => page.evaluate(() => document.documentElement.dataset.theme))
		.toBe(want);
	expect(want).not.toBe(before);

	// The palette from the menu opens with focus in its input and hands it back on close.
	await page.keyboard.press('Enter');
	await expect(items.first()).toBeFocused();
	await page.keyboard.press('Enter');
	const palette = page.getByRole('dialog', { name: 'Command palette' });
	await expect(palette.getByRole('combobox', { name: 'Commands' })).toBeFocused();
	await page.keyboard.press('Escape');
	await expect(palette).toBeHidden();
	await expect(trigger).toBeFocused();
});

mockTest('320 px: shortcuts still work with the actions in the menu', async ({ shell: page }) => {
	await page.setViewportSize({ width: 320, height: 700 });
	const toasts = page.getByRole('region', { name: 'Notifications' });
	await page.getByRole('main').click({ position: { x: 5, y: 5 } });
	await page.keyboard.press('ControlOrMeta+z');
	await expect(toasts).toContainText('Undo: nothing to undo yet');
	await page.keyboard.press('ControlOrMeta+Shift+z');
	await expect(toasts).toContainText('Redo: nothing to redo yet');
	// The menu's Undo runs the same command.
	await more(page).click();
	await menu(page).getByRole('menuitem', { name: /^Undo/ }).click();
	await expect(toasts.getByRole('listitem')).toHaveCount(3);

	await page.getByRole('main').click({ position: { x: 5, y: 5 } });
	await page.keyboard.press('ControlOrMeta+k');
	const palette = page.getByRole('dialog', { name: 'Command palette' });
	await expect(palette.getByRole('combobox', { name: 'Commands' })).toBeFocused();
	expect(await axe(page)).toEqual([]);
	await page.keyboard.press('Escape');
	await expect(palette).toBeHidden();
});
