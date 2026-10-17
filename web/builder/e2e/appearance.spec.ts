import type { Page } from '@playwright/test';
import { axe, expect, test } from './fixtures';

// Appearance view (theme editor, runtime-design §6a): reachable from the top bar and the
// palette, live preview, contrast guard with one-click fixes, undo/redo, JSON import.

async function openAppearance(page: Page) {
	await page.getByRole('banner').getByRole('button', { name: 'Appearance', exact: true }).click();
	await expect(page).toHaveURL(/\/appearance\?mock$/);
	await expect(page.getByRole('heading', { name: 'Appearance', level: 2 })).toBeVisible();
	await expect(page.locator('[data-frame]')).toHaveCount(3);
}

const accent = (page: Page) => page.getByLabel('Accent', { exact: true });
const accentHex = (page: Page) => page.getByRole('textbox', { name: 'Accent, hex value' });
const frameVar = (page: Page, frame: string, name: string) =>
	page
		.locator(`[data-frame="${frame}"]`)
		.evaluate((el, n) => getComputedStyle(el).getPropertyValue(n).trim(), name);
const nextButtonBg = (page: Page, frame: string) =>
	page
		.locator(`[data-frame="${frame}"] .nav-button.primary`)
		.evaluate((el) => getComputedStyle(el).backgroundColor);

test('opens from the top bar and the command palette, and goes back', async ({ shell: page }) => {
	await openAppearance(page);
	await page.getByRole('button', { name: 'Back to editor' }).click();
	await expect(page.getByRole('tree', { name: 'Survey outline' })).toBeVisible();

	await page.keyboard.press('ControlOrMeta+k');
	const dialog = page.getByRole('dialog', { name: 'Command palette' });
	await page.keyboard.type('Open Appearance');
	await expect(dialog.getByRole('option', { name: /Open Appearance/ })).toBeVisible();
	await page.keyboard.press('Enter');
	await expect(page).toHaveURL(/\/appearance\?mock$/);
	await expect(page.getByRole('heading', { name: 'Appearance', level: 2 })).toBeVisible();
});

test('changing the accent updates every preview frame; undo/redo through the shell', async ({
	shell: page
}) => {
	await openAppearance(page);
	expect(await frameVar(page, 'phone', '--color-accent')).toBe('#2456c7');

	await accentHex(page).fill('#1b6b3a');
	for (const f of ['phone', 'tablet', 'desktop']) {
		expect(await frameVar(page, f, '--color-accent')).toBe('#1b6b3a');
	}
	expect(await nextButtonBg(page, 'desktop')).toBe('rgb(27, 107, 58)');
	await expect(accent(page)).toHaveValue('#1b6b3a');

	// The native picker drives the same store.
	await accent(page).fill('#7a2e8c');
	await expect(accentHex(page)).toHaveValue('#7a2e8c');
	expect(await frameVar(page, 'tablet', '--color-accent')).toBe('#7a2e8c');

	// Top-bar Undo / Redo (edit.undo / edit.redo) act on the theme here.
	await page.getByRole('button', { name: 'Undo', exact: true }).click();
	expect(await frameVar(page, 'phone', '--color-accent')).toBe('#2456c7');
	await page.getByRole('button', { name: 'Redo', exact: true }).click();
	expect(await frameVar(page, 'phone', '--color-accent')).toBe('#7a2e8c');

	// Shape controls reach the preview too.
	await page.getByRole('radio', { name: 'Cards' }).check();
	await expect(page.locator('[data-frame="phone"]')).toHaveAttribute('data-osp-choice', 'cards');
	await expect(page.getByTestId('preview-summary')).toContainText('cards choices');
});

test('a failing colour shows the problem and a suggestion that fixes it', async ({ shell: page }) => {
	await openAppearance(page);
	const banner = page.getByTestId('guard-banner');
	await expect(banner).toContainText('Ready to publish');

	await accentHex(page).fill('#66aaff');
	await expect(banner).toContainText("Can't publish: 1 contrast problem");
	const problems = page.getByTestId('contrast-problems');
	await expect(problems).toBeVisible();
	await expect(problems).toContainText('link text / filled button label on the page');
	await expect(problems).toContainText('Nearest passing colour');
	await expect(accent(page)).toHaveAttribute('aria-describedby', /colour-light-accent-problems/);

	// A second failing colour (hidden under "More colours") is listed and reachable.
	await page.getByText('More colours').click();
	await page.getByRole('textbox', { name: 'Hints and borders, hex value' }).fill('#bbbbbb');
	await expect(banner).toContainText("Can't publish: 2 contrast problems");
	await banner.getByRole('button', { name: /Hints and borders/ }).click();
	await expect(page.getByLabel('Hints and borders', { exact: true })).toBeFocused();
	await page.getByRole('textbox', { name: 'Hints and borders, hex value' }).fill('#505a6b');

	await problems.getByRole('button', { name: 'Use suggestion' }).click();
	await expect(problems).toHaveCount(0);
	await expect(banner).toContainText('Ready to publish');
	const fixed = await accentHex(page).inputValue();
	expect(fixed).not.toBe('#66aaff');
	expect(await frameVar(page, 'phone', '--color-accent')).toBe(fixed);
});

test('dark colours are checked when the survey follows the device', async ({ shell: page }) => {
	await openAppearance(page);
	await page.getByRole('group', { name: 'Colours for' }).getByRole('radio', { name: 'Dark' }).check();
	await expect(page.locator('[data-frame="phone"]')).toHaveAttribute('data-mode', 'dark');
	await accentHex(page).fill('#203060');
	await expect(page.getByTestId('guard-banner')).toContainText('Dark colours · Accent');
	// Showing light only means the dark palette is no longer used, so nothing blocks.
	await page.getByRole('group', { name: 'Light or dark' }).getByRole('radio', { name: 'Light' }).check();
	await expect(page.getByTestId('guard-banner')).toContainText('Ready to publish');
});

test('imports a theme JSON, rejects an invalid one, and keeps a draft', async ({ shell: page }) => {
	await openAppearance(page);
	const input = page.getByTestId('theme-import');
	await input.setInputFiles({
		name: 'bad.json',
		mimeType: 'application/json',
		buffer: Buffer.from(JSON.stringify({ font: 'Comic Sans', css: 'body{}' }))
	});
	const alert = page.getByRole('alert').filter({ hasText: "isn't a valid theme" });
	await expect(alert).toContainText('/colours: Required.');
	await expect(alert).toContainText('/font');
	await expect(alert).toContainText('/css: Unknown field "css".');

	await page.getByRole('radio', { name: 'Warm' }).check();
	const download = page.waitForEvent('download');
	await page.getByRole('button', { name: 'Export JSON' }).click();
	const file = await (await download).path();
	await page.getByRole('radio', { name: 'Clean' }).check();
	await input.setInputFiles(file);
	await expect(page.getByRole('radio', { name: 'Warm' })).toBeChecked();
	await expect(alert).toHaveCount(0);

	await page.reload();
	await expect(page.getByRole('radio', { name: 'Warm' })).toBeChecked();
});

test('controls are labelled and keyboard-operable', async ({ shell: page }) => {
	await openAppearance(page);
	const size = page.getByRole('slider', { name: 'Base size' });
	await expect(size).toHaveAttribute('min', '16');
	await size.focus();
	await page.keyboard.press('ArrowRight');
	await expect(size).toHaveValue('17');
	await page.keyboard.press('Home');
	await expect(size).toHaveValue('16');
	await page.keyboard.press('ArrowLeft');
	await expect(size).toHaveValue('16');
	// Inputs in the preview never go below 16 px.
	const inputPx = await page
		.locator('[data-frame="phone"] .text-input')
		.first()
		.evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
	expect(inputPx).toBeGreaterThanOrEqual(16);

	const compact = page.getByRole('radio', { name: 'Compact' }).last();
	await page.getByRole('radio', { name: 'Comfortable' }).focus();
	await page.keyboard.press('ArrowRight');
	await expect(compact).toBeChecked();

	// The preview is a picture: hidden from assistive tech, nothing focusable inside.
	for (const frame of await page.locator('[data-frame]').all()) {
		await expect(frame).toHaveAttribute('aria-hidden', 'true');
		await expect(frame).toHaveAttribute('inert', '');
	}
	await expect(page.getByTestId('preview-summary')).toContainText('compact spacing');
});

for (const scheme of ['light', 'dark'] as const) {
	test.describe(`${scheme} builder theme`, () => {
		test.use({ colorScheme: scheme });

		test('axe-core reports no violations', async ({ shell: page }) => {
			await openAppearance(page);
			expect(await axe(page)).toEqual([]);
			await accentHex(page).fill('#66aaff');
			await expect(page.getByTestId('contrast-problems')).toBeVisible();
			await page.getByText('More colours').click();
			expect(await axe(page)).toEqual([]);
		});
	});
}

test('visual snapshot at 1440 px', async ({ shell: page }, info) => {
	await page.setViewportSize({ width: 1440, height: 900 });
	await openAppearance(page);
	await page.mouse.move(0, 0);
	await page.screenshot({ path: info.outputPath('appearance-1440.png') });
	await expect(page).toHaveScreenshot('appearance-1440.png');
});
