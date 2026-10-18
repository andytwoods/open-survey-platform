import AxeBuilder from '@axe-core/playwright';
import { test as base, expect, type Locator, type Page } from '@playwright/test';

/**
 * Every test starts on the mock shell (`/?mock`) with a stubbed health endpoint (no backend
 * needed). Signed out, the API answers 401, which would end the page's session (reload once,
 * then a banner); the mock has no session to end, so those become 404s here.
 */
export const test = base.extend<{ shell: Page }>({
	shell: async ({ page }, use) => {
		await page.route('**/api/**', async (route) => {
			// Pages change by full loads, so a request can be cut off mid-flight by the next
			// page; Playwright then disposes it and fetch/fulfill throw. Nothing is waiting.
			try {
				const res = await route.fetch();
				if (res.status() !== 401) return await route.fulfill({ response: res });
				return await route.fulfill({
					status: 404,
					json: { code: 'not_found', message: 'No backend session in the mock.' }
				});
			} catch {
				return;
			}
		});
		await page.route('**/api/health', (route) => route.fulfill({ json: { status: 'ok' } }));
		await page.goto('/?mock');
		await expect(page.getByRole('tree', { name: 'Survey outline' })).toBeVisible();
		await expect(page.getByText('API connected')).toBeVisible();
		await use(page);
		await page.unrouteAll({ behavior: 'ignoreErrors' });
	}
});

export { expect };

/**
 * Run a command from the palette by typing `query` and pressing Enter on `option`. Waits
 * for the input to have focus (keys typed before that are lost) and for `option` to be the
 * highlighted one (Enter runs whichever is highlighted).
 */
export async function runFromPalette(page: Page, query: string, option: RegExp) {
	await page.keyboard.press('ControlOrMeta+k');
	const dialog = page.getByRole('dialog', { name: 'Command palette' });
	await expect(dialog.getByRole('combobox', { name: 'Commands' })).toBeFocused();
	await page.keyboard.type(query);
	const item = dialog.getByRole('option', { name: option });
	await expect(item).toHaveAttribute('aria-selected', 'true');
	await page.keyboard.press('Enter');
	await expect(dialog).toBeHidden();
}

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

// -- rich text fields (planning/rich-text.md §9, RT3) ------------------------------------
//
// A participant-facing text field is a read-only textbox until it is focused; then the
// editor (a contenteditable with the same accessible name) swaps in. A locator by label
// resolves to whichever is present, so these helpers wait for the editor before typing.

/**
 * Focus a rich-text field and wait for its editor to open. Waits for the rich field itself
 * first: until the property schemas load, the properties pane shows a plain fallback input
 * with the same name.
 */
export async function openRich(page: Page, field: Locator): Promise<void> {
	await expect(field).toHaveAttribute('role', 'textbox');
	await field.click();
	await expect(field).toHaveAttribute('contenteditable', 'true');
	await expect(field).toBeFocused();
	// The toolbar appears above the text and may now sit under the pointer: park the mouse
	// so no tooltip opens (a tooltip is portalled outside the landmarks axe checks).
	await page.mouse.move(0, 0);
}

/** Replace a rich-text field's content with `text` (the editor stays open and focused). */
export async function fillRich(page: Page, field: Locator, text: string): Promise<void> {
	await openRich(page, field);
	await page.keyboard.press('ControlOrMeta+a');
	await page.keyboard.press('Backspace');
	if (text) await page.keyboard.type(text);
}

/** Put the caret at the end of an open editor's text (keyboard End differs per platform). */
export async function caretToEnd(field: Locator): Promise<void> {
	await field.evaluate((el) => (el as HTMLElement & { editor: { commands: { focus(where: string): void } } }).editor.commands.focus('end'));
	await expect(field).toBeFocused();
}

/**
 * In the "Add a question" type picker (opened by "Add question" on the canvas or in the
 * palette): wait for its filter box to have focus, click the type named `name` and wait
 * for the picker to close.
 */
export async function pickQuestionType(page: Page, name: string | RegExp = /^Text\b/, dialogName = 'Add a question') {
	const dialog = page.getByRole('dialog', { name: dialogName });
	await expect(dialog.getByRole('combobox', { name: 'Filter question types' })).toBeFocused();
	await dialog.getByRole('option', { name }).click();
	await expect(dialog).toBeHidden();
}
