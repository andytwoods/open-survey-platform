import { expect, test } from '@playwright/test';
import { axe } from './fixtures';

for (const scheme of ['light', 'dark'] as const) {
	test.describe(`component gallery, ${scheme}`, () => {
		test.use({ colorScheme: scheme });

		test('axe-clean at rest and with overlays open', async ({ page }) => {
			await page.goto('/dev/components');
			await expect(page.getByRole('heading', { name: 'Component gallery' })).toBeVisible();
			expect(await axe(page)).toEqual([]);

			await page.getByRole('combobox', { name: /^Colour/ }).click();
			await expect(page.getByRole('option', { name: 'Green' })).toBeVisible();
			expect(await axe(page)).toEqual([]);
			await page.getByRole('option', { name: 'Green' }).click();
			await expect(page.getByRole('combobox', { name: /^Colour/ })).toHaveText(/Green/);

			await page.getByRole('button', { name: 'Show toast' }).click();
			await expect(page.getByRole('region', { name: 'Notifications' })).toContainText('Saved.');

			await page.getByRole('button', { name: 'Add item' }).hover();
			await expect(page.getByText('Add item', { exact: true }).last()).toBeVisible();

			await page.getByRole('button', { name: 'Open dialog' }).click();
			await expect(page.getByRole('dialog', { name: 'Example dialog' })).toBeVisible();
			expect(await axe(page)).toEqual([]);
			await page.keyboard.press('Escape');
			await expect(page.getByRole('button', { name: 'Open dialog' })).toBeFocused();
		});
	});
}
