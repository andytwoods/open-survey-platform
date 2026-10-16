import { expect, test } from '@playwright/test';
import { axe } from './fixtures';

// Theme gallery (/dev/themes): every preset, in every mode it can show, at phone and
// desktop widths, is axe-clean (incl. colour contrast) in its drawn state and with a
// choice focused. Full-page screenshots go to test-results/ for review by eye.
const PRESETS = ['clean', 'warm', 'high-contrast', 'dark', 'compact'] as const;

for (const preset of PRESETS) {
	test(`theme preset ${preset} is axe-clean`, async ({ page }, info) => {
		await page.setViewportSize({ width: 1400, height: 900 });
		await page.goto(`/dev/themes?preset=${preset}`);
		await expect(page.getByRole('heading', { name: 'Theme gallery' })).toBeVisible();
		const frames = page.locator('[data-frame]');
		await expect(frames.first()).toBeVisible();
		expect(await frames.count()).toBeGreaterThanOrEqual(2);
		expect(await axe(page)).toEqual([]);

		// Hover and focus states are drawn from derived tokens too.
		await page.getByRole('button', { name: 'Next' }).first().hover();
		await frames.first().getByRole('radio', { name: 'A little' }).focus();
		await page.keyboard.press('ArrowDown');
		expect(await axe(page)).toEqual([]);

		// No frame overflows horizontally (WCAG 1.4.10) at phone width.
		const overflow = await page
			.locator('[data-frame$="-phone"]')
			.evaluateAll((els) => els.filter((el) => el.scrollWidth > el.clientWidth + 1).length);
		expect(overflow).toBe(0);

		await page.screenshot({ path: info.outputPath(`themes-${preset}.png`), fullPage: true });
	});
}
