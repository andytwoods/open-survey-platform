import AxeBuilder from '@axe-core/playwright';
import { test as base, expect, type Page } from '@playwright/test';

/** Every test starts on the mock shell (`/?mock`) with a stubbed health endpoint (no backend needed). */
export const test = base.extend<{ shell: Page }>({
	shell: async ({ page }, use) => {
		await page.route('**/api/health', (route) => route.fulfill({ json: { status: 'ok' } }));
		await page.goto('/?mock');
		await expect(page.getByRole('tree', { name: 'Survey outline' })).toBeVisible();
		await expect(page.getByText('API connected')).toBeVisible();
		await use(page);
	}
});

export { expect };

export async function axe(page: Page) {
	const results = await new AxeBuilder({ page })
		.withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'])
		.analyze();
	return results.violations.map((v) => ({
		id: v.id,
		impact: v.impact,
		help: v.help,
		targets: v.nodes.map((n) => n.target.join(' '))
	}));
}

/** The element that has focus, described for assertions. */
export function focused(page: Page) {
	return page.locator('*:focus');
}
