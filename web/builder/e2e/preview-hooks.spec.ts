import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';
import { withChecksum, type Plan } from '@osp/engine';
import { axe, signIn, writeHeaders } from './fixtures';

// Researcher hooks in the builder Preview (task R10, runtime-design §7a). osp-survey/0.1 has
// no hooks field yet, so (as in web/runtime/e2e/server.py) the manifest is put into the plan
// the real osp-api compiled, with its checksum recomputed, on the way to the builder.

const FIXTURE = '05-showif-null';
const survey = () => JSON.parse(readFileSync(new URL(`../../../fixtures/${FIXTURE}/survey.json`, import.meta.url), 'utf8'));

const HOOKS = {
	format: 'osp-hooks/1',
	source: [
		"osp.on('onStart', function () { throw new Error('boom'); });",
		"osp.on('onPageShown', function (ctx, data, act) { act.addParadata('shownTrial', ctx.trial); });",
		"osp.on('onPageNext', function (ctx, data, act) {",
		'  var a = ctx.results.a;',
		"  if (a && a.value === 99) act.rejectPage({ itemId: 'a', message: 'Hook says: not 99.' });",
		'});'
	].join('\n'),
	handlers: {
		onStart: { reads: [], writes: [] },
		onPageShown: { reads: [], writes: [] },
		onPageNext: { reads: ['a'], writes: [] }
	}
};

async function openPreview(page: Page) {
	await signIn(page);
	const res = await page.request.post('/api/surveys', {
		headers: await writeHeaders(page),
		data: { title: `Preview hooks ${FIXTURE}`, survey: survey() }
	});
	expect(res.status()).toBe(201);
	const { id } = await res.json();
	await page.route('**/api/surveys/*/preview-plan', async (route) => {
		const r = await route.fetch();
		const body = await r.json();
		const { checksum: _old, ...plan } = body.plan as Plan;
		void _old;
		body.plan = withChecksum({ ...plan, hooks: HOOKS } as unknown as Plan);
		await route.fulfill({ response: r, json: body });
	});
	await page.goto(`/surveys/${id}`);
	await page.getByRole('banner').getByRole('button', { name: 'Preview' }).click();
	await expect(page.getByRole('heading', { name: 'Preview', level: 2 })).toBeVisible();
}

const hookRow = (page: Page, event: string) => page.locator(`[data-testid="dbg-hook"][data-event="${event}"]`);

test('preview runs the survey hooks in the participant sandbox; the debugger shows calls and errors', async ({ page }) => {
	// Everything the preview frames ask the network for: never the API (pages-split D10).
	const frameRequests: string[] = [];
	page.on('request', (r) => {
		const f = r.frame();
		if (f !== page.mainFrame() && f.url().includes('preview-frame')) frameRequests.push(r.url());
	});
	const frameResponse = page.waitForResponse((r) => r.url().includes('/preview-frame'));

	await openPreview(page);
	const phone = page.frameLocator('[data-testid="preview-frame-phone"]');
	await expect(phone.getByRole('heading', { level: 1 })).toContainText('showIf with null values');

	// The preview frame is served with the CSP docs/hosting.md asks for.
	const csp = (await frameResponse).headers()['content-security-policy'] ?? '';
	expect(csp).toMatch(/script-src 'self' 'sha256-[A-Za-z0-9+/=]+'/);
	expect(csp).toContain('worker-src blob:');
	expect(csp).toContain("connect-src 'none'");

	// The hooks run in the participant app's own sandbox: an allow-scripts-only iframe.
	await expect(phone.locator('iframe[title="hooks"]')).toHaveAttribute('sandbox', 'allow-scripts');

	// onStart threw: it fails open, and the debugger says so with the error.
	const hooks = page.getByTestId('dbg-hooks');
	await expect(hookRow(page, 'onStart')).toHaveAttribute('data-status', 'failed');
	await expect(hookRow(page, 'onStart').getByTestId('dbg-hook-error')).toContainText('error:');
	await expect(hookRow(page, 'onPageShown')).toHaveAttribute('data-status', 'ok');
	await expect(hookRow(page, 'onPageShown')).toContainText('addParadata shownTrial = 1');

	// onPageNext rejects 99 with the hook's message, in the frame, exactly as for participants.
	await phone.getByLabel('Pick any whole number (optional).').fill('99');
	await phone.getByRole('button', { name: 'Next' }).click();
	await expect(phone.getByTestId('error-summary')).toContainText('Hook says: not 99.');
	await expect(hookRow(page, 'onPageNext')).toContainText('rejectPage a: "Hook says: not 99."');
	await expect(page.getByTestId('dbg-page')).toHaveText('p1');

	// Another answer goes through; the next page's onPageShown runs too.
	await phone.getByLabel('Pick any whole number (optional).').fill('3');
	await phone.getByRole('button', { name: 'Next' }).click();
	await expect(phone.getByText('This question is always shown.')).toBeVisible();
	await expect(page.getByTestId('dbg-page')).toHaveText('p2');
	await expect(hookRow(page, 'onPageShown').last()).toContainText('addParadata shownTrial = 2');
	await expect(hookRow(page, 'onPageNext')).toHaveCount(2);

	await hooks.scrollIntoViewIfNeeded();
	const dir = process.env.OSP_R10_SCREENSHOTS;
	await page.screenshot({ path: dir ? `${dir}/preview-hooks.png` : test.info().outputPath('preview-hooks.png') });
	await axe(page, 'preview with hooks');

	expect(frameRequests.filter((u) => new URL(u).pathname.startsWith('/api'))).toEqual([]);
});

test('a hook manifest the runtime refuses shows in the debugger, not just in the frame', async ({ page }) => {
	await signIn(page);
	const res = await page.request.post('/api/surveys', {
		headers: await writeHeaders(page),
		data: { title: 'Preview bad hooks', survey: survey() }
	});
	const { id } = await res.json();
	await page.route('**/api/surveys/*/preview-plan', async (route) => {
		const r = await route.fetch();
		const body = await r.json();
		const { checksum: _old, ...plan } = body.plan as Plan;
		void _old;
		// A hook may never write a question (§7a): the runner refuses the manifest.
		const bad = { ...HOOKS, handlers: { onStart: { reads: [], writes: ['a'] } } };
		body.plan = withChecksum({ ...plan, hooks: bad } as unknown as Plan);
		await route.fulfill({ response: r, json: body });
	});
	await page.goto(`/surveys/${id}`);
	await page.getByRole('banner').getByRole('button', { name: 'Preview' }).click();
	await expect(page.getByTestId('dbg-hook-log').first()).toContainText('hook manifest refused');
});
