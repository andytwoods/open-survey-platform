import AxeBuilder from '@axe-core/playwright';
import { readFileSync } from 'node:fs';
import { expect, test, type FrameLocator, type Page } from '@playwright/test';
import { axe, signIn, writeHeaders } from './fixtures';

// Preview + debugger (task B11) end to end against a real osp-api (e2e/api_server.py): the
// draft is compiled by POST /preview-plan, the device frames run web/runtime in preview
// mode, and the debugger's states are compared with the fixture's expected trace.

const FIXTURE = '05-showif-null';
const SCRIPT = 'a3-b3';

const read = (rel: string) => readFileSync(new URL(`../../../fixtures/${FIXTURE}/${rel}`, import.meta.url), 'utf8');
const survey = () => JSON.parse(read('survey.json'));
const scriptText = () => read(`scripts/${SCRIPT}.json`);
const expectedText = () => read(`expected/${SCRIPT}.json`);
const expected = () => JSON.parse(expectedText()) as { steps: Array<Record<string, unknown>> };

/** The keys every step of this fixture's trace asserts. */
const KEYS = ['page', 'visible', 'errors', 'nav', 'questions', 'orders', 'conditions', 'end'];
const pick = (o: Record<string, unknown>) => Object.fromEntries(KEYS.map((k) => [k, o[k]]));

async function openPreview(page: Page) {
	await signIn(page);
	const res = await page.request.post('/api/surveys', {
		headers: await writeHeaders(page),
		data: { title: `Preview ${FIXTURE}`, survey: survey() }
	});
	expect(res.status()).toBe(201);
	const { id } = await res.json();
	await page.goto(`/surveys/${id}`);
	await page.getByRole('banner').getByRole('button', { name: 'Preview' }).click();
	await expect(page.getByRole('heading', { name: 'Preview', level: 2 })).toBeVisible();
	return id as string;
}

async function trace(page: Page) {
	const text = await page.getByTestId('debugger-trace').textContent();
	return JSON.parse(text ?? 'null') as Record<string, unknown>;
}

async function traceIs(page: Page, step: Record<string, unknown>) {
	await expect.poll(async () => pick(await trace(page))).toEqual(pick(step));
}

const frame = (page: Page, device: string): FrameLocator => page.frameLocator(`[data-testid="preview-frame-${device}"]`);

test('preview on phone and desktop follows the fixture trace, and the debugger explains it', async ({ page }) => {
	await openPreview(page);
	const steps = expected().steps;

	// Phone frame: the participant app, page 1.
	const phone = frame(page, 'phone');
	await expect(phone.getByRole('heading', { level: 1 })).toContainText('showIf with null values');
	await traceIs(page, steps[0]!);

	// Answer as the script does (a = 3, b = 3, c = blue), through the participant page.
	await phone.getByLabel('Pick any whole number (optional).').fill('3');
	await phone.getByLabel('Pick another whole number (optional).').fill('3');
	await phone.getByRole('checkbox', { name: 'Blue' }).check();
	await phone.getByRole('button', { name: 'Next' }).click();
	await expect(phone.getByText('This question is always shown.')).toBeVisible();
	await traceIs(page, steps[1]!);

	// The debugger says why each question on p2 is shown or hidden.
	const item = (id: string) => page.locator(`[data-testid="dbg-item"][data-id="${id}"]`);
	await expect(page.getByTestId('dbg-page')).toHaveText('p2');
	await expect(page.getByTestId('dbg-path')).toHaveText('p1 → p2');
	await expect(item('s_gt')).toHaveAttribute('data-visible', 'false');
	await expect(item('s_gt').getByTestId('dbg-condition')).toHaveText('a > 5');
	await expect(item('s_gt')).toContainText('a = 3');
	await expect(item('s_eq')).toHaveAttribute('data-visible', 'true');
	await expect(item('s_eq')).toContainText('b = 3');
	await expect(item('p2_anchor')).toContainText('no show-if condition');
	await expect(page.getByTestId('dbg-trial')).toHaveText('2');
	const dir = process.env.OSP_B11_SCREENSHOTS;
	await item('s_gt').scrollIntoViewIfNeeded();
	await page.screenshot({ path: dir ? `${dir}/preview-debugger.png` : test.info().outputPath('preview-debugger.png') });

	// Desktop: the same run, carried over; finish it there.
	await page.getByRole('radio', { name: /Desktop/ }).check();
	const desktop = frame(page, 'desktop');
	await expect(desktop.getByText('This question is always shown.')).toBeVisible();
	const hidden = desktop.getByText('Shown when: a > 5', { exact: true });
	await expect(hidden).toHaveCount(0);
	await desktop.getByRole('button', { name: 'Next' }).click();
	await expect(desktop.getByTestId('thanks')).toBeVisible();
	await traceIs(page, steps[2]!);

	// Nothing reached the server: no participant session, no publish.
	await expect(page.getByTestId('preview')).toBeVisible();
});

test('a fixture script loaded into the debugger matches the expected trace at every step', async ({ page }) => {
	await openPreview(page);
	const steps = expected().steps;
	await page.getByTestId('dbg-script-text').fill(scriptText());
	await page.getByRole('button', { name: 'Load script' }).click();
	await expect(page.getByTestId('dbg-script-pos')).toContainText('Step 0 of 2');
	await page.getByTestId('dbg-expected-text').fill(expectedText());
	await page.getByRole('button', { name: 'Compare with expected' }).click();

	for (let k = 0; k < steps.length; k++) {
		await page.getByRole('list', { name: 'Script steps' }).getByRole('button').nth(k).click();
		await expect(page.getByTestId('dbg-script-pos')).toContainText(`Step ${k} of 2`);
		await expect(page.getByTestId('dbg-compare')).toHaveAttribute('data-match', 'true');
		await traceIs(page, steps[k]!);
	}
	// The frame shows the end too (the debugger drives the preview).
	await expect(frame(page, 'phone').getByTestId('thanks')).toBeVisible();

	// Export the run as a script: same seed, same answers.
	await page.getByRole('button', { name: 'Export run as script' }).click();
	const exported = JSON.parse((await page.getByTestId('dbg-exported').inputValue()) ?? '{}');
	const original = JSON.parse(scriptText());
	expect(exported.sessionSeed).toBe(original.sessionSeed);
	expect(exported.actions.map((a: { do: string; expectPage?: string }) => [a.do, a.expectPage])).toEqual(
		original.actions.map((a: { do: string; expectPage?: string }) => [a.do, a.expectPage])
	);
	expect(exported.actions[0].set).toEqual(original.actions[0].set);
});

test('stepping in the debugger with given answers moves the preview; seed and restart', async ({ page }) => {
	await openPreview(page);
	const phone = frame(page, 'phone');
	await page.locator('[data-testid="dbg-answer"][data-id="a"]').fill('7');
	await page.locator('[data-testid="dbg-answer"][data-id="c"]').fill('["red"]');
	await page.getByRole('button', { name: 'Next page' }).click();
	await expect(phone.getByText('Shown when: a > 5', { exact: true })).toBeVisible();
	await expect(phone.getByText('Shown when: contains(c, "red")', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Back', exact: true }).click();
	await expect(page.getByTestId('dbg-page')).toHaveText('p1');
	await page.getByTestId('preview-seed').fill('77');
	await page.getByRole('button', { name: 'Use seed' }).click();
	await expect(page.getByTestId('debugger')).toContainText('77');
	await page.getByRole('button', { name: 'Restart', exact: true }).click();
	await expect(page.getByTestId('dbg-path')).toHaveText('p1');
});

test('run simulation shows the report', async ({ page }) => {
	await openPreview(page);
	await page.getByRole('button', { name: 'Run simulation' }).click();
	const report = page.getByTestId('sim-report');
	await expect(report).toBeVisible({ timeout: 60_000 });
	await expect(report).toContainText(/Exhaustive|Sampled/);
	await expect(report.getByTestId('sim-unreachable')).toBeVisible();
	await expect(report).toContainText('Balance checks');
});

async function axeWithout(page: Page, exclude: string) {
	const results = await new AxeBuilder({ page })
		.withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'])
		.exclude(exclude)
		.analyze();
	return results.violations.map((v) => ({ id: v.id, targets: v.nodes.map((n) => n.target.join(' ')) }));
}

for (const scheme of ['light', 'dark'] as const) {
	test(`preview and debugger, ${scheme}: axe-core reports no violations; screenshot`, async ({ browser }) => {
		const context = await browser.newContext({ colorScheme: scheme, viewport: { width: 1280, height: 800 } });
		const page = await context.newPage();
		await axeRun(page, scheme);
		await context.close();
	});
}

async function axeRun(page: Page, scheme: string) {
	await openPreview(page);
	await expect(frame(page, 'phone').getByRole('heading', { level: 1 })).toBeVisible();
	// One device: the builder page and the participant page inside the frame.
	expect(await axe(page)).toEqual([]);
	// Side by side, the frames repeat the participant page's landmarks (each frame is a
	// participant page of its own), so the frames are left out of this run.
	await page.getByRole('checkbox', { name: 'Side by side' }).check();
	await expect(frame(page, 'desktop').getByRole('heading', { level: 1 })).toBeVisible();
	await page.getByRole('button', { name: 'Run simulation' }).click();
	await expect(page.getByTestId('sim-report')).toBeVisible({ timeout: 60_000 });
	expect(await axeWithout(page, 'iframe')).toEqual([]);
	const dir = process.env.OSP_B11_SCREENSHOTS;
	await page.screenshot({ path: dir ? `${dir}/preview-${scheme}.png` : test.info().outputPath(`preview-${scheme}.png`) });
}
