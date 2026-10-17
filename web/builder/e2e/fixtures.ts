import AxeBuilder from '@axe-core/playwright';
import { test as base, expect, type Page } from '@playwright/test';

/**
 * Every test starts on the mock shell (`/?mock`) with a stubbed health endpoint (no backend
 * needed). Signed out, the API answers 401, which would end the page's session (reload once,
 * then a banner); the mock has no session to end, so those become 404s here.
 */
export const test = base.extend<{ shell: Page }>({
	shell: async ({ page }, use) => {
		await page.route('**/api/**', async (route) => {
			const res = await route.fetch();
			if (res.status() !== 401) return route.fulfill({ response: res });
			return route.fulfill({ status: 404, json: { code: 'not_found', message: 'No backend session in the mock.' } });
		});
		await page.route('**/api/health', (route) => route.fulfill({ json: { status: 'ok' } }));
		await page.goto('/?mock');
		await expect(page.getByRole('tree', { name: 'Survey outline' })).toBeVisible();
		await expect(page.getByText('API connected')).toBeVisible();
		await use(page);
	}
});

export { expect };

// -- sign-in glue ---------------------------------------------------------------------
//
// ALL of the e2e tests' sign-in lives here. The builder pages have no sign-in UI: a host
// owns accounts (planning/pages-split.md). The e2e API server (e2e/api_server.py) uses the
// Dev identity, so every request is the dev researcher (owner of dev-lab): there is
// nothing to sign in to. To test against a real host scheme, change these two functions.

/** Sign in, then open the survey list. With the Dev identity, signing in is a no-op. */
export async function signIn(page: Page): Promise<void> {
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'Your surveys' })).toBeVisible();
}

/**
 * Headers a test's own API writes (`page.request.post`) need, as the page would send: the
 * page's Origin (osp-api checks it on unsafe requests). No CSRF token: there is none.
 */
export async function writeHeaders(page: Page): Promise<Record<string, string>> {
	const url = page.url().startsWith('http') ? page.url() : (base.info().project.use.baseURL ?? 'http://127.0.0.1');
	return { Origin: new URL(url).origin };
}

// -- helpers ----------------------------------------------------------------------------

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
