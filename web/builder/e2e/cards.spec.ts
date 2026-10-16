import { expect, test, type Page } from '@playwright/test';
import { axe } from './fixtures';

// Question cards gallery (/dev/cards, task B5): one snapshot per family in light and dark,
// cropped to that family's cards, at 1440 px; axe; click / Enter selection.
const FAMILIES = ['choice', 'text', 'number', 'matrix', 'scale', 'note'] as const;

async function open(page: Page) {
	await page.setViewportSize({ width: 1440, height: 900 });
	await page.goto('/dev/cards');
	await expect(page.getByRole('heading', { level: 1, name: 'Question cards' })).toBeVisible();
	await expect(page.locator('[data-question-card="q_study_grid"] .matrix')).toHaveAttribute('data-layout', /./);
	await page.evaluate(() => document.fonts.ready);
}

for (const scheme of ['light', 'dark'] as const) {
	test.describe(`question cards, ${scheme}`, () => {
		test.use({ colorScheme: scheme });

		test('axe-clean', async ({ page }) => {
			await open(page);
			expect(await axe(page)).toEqual([]);
		});

		for (const family of FAMILIES) {
			test(`${family} card snapshot`, async ({ page }) => {
				await open(page);
				await expect(page.getByTestId(`family-${family}`).locator('.cards')).toHaveScreenshot(
					`card-${family}-${scheme}.png`
				);
			});
		}
	});
}

test.describe('question card behaviour', () => {
	test('every family renders its own card with a read-only preview', async ({ page }) => {
		await open(page);
		for (const family of FAMILIES) {
			const card = page.getByTestId(`family-${family}`).locator('[data-question-card]').first();
			await expect(card).toHaveAttribute('data-family', family);
		}
		await expect(page.locator('[data-question-card="q_rank"]')).toHaveAttribute('data-family', 'unknown');
		await expect(page.locator('[data-question-card="q_rank"]')).toContainText('No preview');
		// The preview can't be focused or typed into.
		const preview = page.locator('[data-question-card="q_study_place"] .preview');
		await expect(preview).toHaveAttribute('inert', '');
		await preview.locator('input').focus();
		await expect(preview.locator('input')).not.toBeFocused();
	});

	test('label shows pipes as tokens, required marker and badges', async ({ page }) => {
		await open(page);
		const card = page.locator('[data-question-card="q_devices"]');
		await expect(card.locator('.pipe')).toHaveText(/\$\{q_name\}/);
		await expect(card.locator('.req')).toBeVisible();
		await expect(card.locator('[data-badge="showIf"]')).toContainText('q_age >= 18');
		await expect(card.locator('[data-badge="shuffle"]')).toBeVisible();
		await expect(card.locator('[data-badge="export"]')).toContainText('XLSForm');
		await expect(page.locator('[data-question-card="q_hours"] [data-badge="validation"]')).toContainText(
			'q_hours >= 0 and q_hours <= 24'
		);
		await expect(page.locator('[data-question-card="q_quality"] [data-badge="errors"]')).toHaveText('1 error');
	});

	test('click and Enter select; the selected card is marked and announced', async ({ page }) => {
		await open(page);
		const devices = page.getByRole('button', { name: /^Which devices/ });
		await expect(devices).toHaveAttribute('aria-current', 'true');
		await expect(devices).toHaveAccessibleName(/selected$/);

		const hours = page.getByRole('button', { name: /^Hours of sleep/ });
		// A click on the preview (not the label) still selects the card.
		const preview = page.locator('[data-question-card="q_hours"] .preview');
		await preview.scrollIntoViewIfNeeded();
		const box = (await preview.boundingBox())!;
		await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
		await expect(page.getByTestId('selected')).toHaveText('Selected: q_hours');
		await expect(hours).toHaveAttribute('aria-current', 'true');
		await expect(devices).not.toHaveAttribute('aria-current');

		const note = page.getByRole('button', { name: /^Thanks/ });
		await note.focus();
		await page.keyboard.press('Enter');
		await expect(page.getByTestId('selected')).toHaveText('Selected: q_info');
		await expect(note).toHaveAccessibleName(/selected$/);
		await expect(note).toHaveAccessibleDescription(/^$/);

		// Tab moves card to card: nothing inside a preview takes focus.
		await page.keyboard.press('Shift+Tab');
		await expect(page.getByRole('button', { name: /^How would you rate/ })).toBeFocused();
	});
});
