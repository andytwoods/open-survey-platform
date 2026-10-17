/**
 * The participant app against the real backend (e2e/server.py), on every device profile
 * (playwright.config.ts). Every scenario ends by reading what the server stored: exactly
 * one response with exactly the expected answers (zero lost, zero duplicated).
 */
import { expect, test } from '@playwright/test';
import {
	axe,
	back,
	expectFlowPage,
	expectStoredResponse,
	FLOW_EXPECTED,
	flowPages,
	headingFocused,
	localCopy,
	openSurvey,
	slugOf,
	next,
	onPage,
	requestsFor,
	saved,
	sessionId,
	stored,
	thanks
} from './helpers';

test('complete a survey: errors, focus, back, axe on every page', async ({ page, request }) => {
	await openSurvey(page, 'flow');
	await onPage(page, 1);
	const sid = await sessionId(page);
	await axe(page, 'page 1');

	// A failed Next: the error summary gets focus and links to the question.
	await next(page);
	const summary = page.getByTestId('error-summary');
	await expect(summary).toBeFocused();
	await axe(page, 'page 1 with errors');
	await summary.getByRole('link').click();
	await expect(page.getByRole('radio', { name: 'Yes' })).toBeFocused();

	await flowPages[0]!(page);
	await next(page);
	await onPage(page, 2);
	await headingFocused(page);

	// Constraint message from the engine, then fix it.
	await page.getByLabel('How old are you?').fill('12');
	await next(page);
	await expect(summary).toBeFocused();
	await expect(summary).toContainText('Please enter an age between 18 and 120.');
	await flowPages[1]!(page);
	await axe(page, 'page 2');
	await next(page);
	await onPage(page, 3);

	// Piping (escaped text) and a live show-if reveal.
	await expect(page.getByText('Which colours do you like, Sam?')).toBeVisible();
	await expect(page.getByLabel('Which other colour?')).toHaveCount(0);
	await flowPages[2]!(page);
	await axe(page, 'page 3 with a revealed question');

	// Back keeps values; forward again.
	await back(page);
	await onPage(page, 2);
	await headingFocused(page);
	await expectFlowPage(page, 1);
	await next(page);
	await onPage(page, 3);
	await expectFlowPage(page, 2);
	await next(page);
	await onPage(page, 4);
	await flowPages[3]!(page);
	await axe(page, 'page 4');
	await next(page);
	await thanks(page);
	await expect(page.getByTestId('thanks')).toBeFocused();
	await axe(page, 'thank-you page');

	const s = await expectStoredResponse(request, sid, FLOW_EXPECTED);
	expect(s.conflicts).toBe(0);
	expect(await localCopy(page, await slugOf(page, 'flow'))).toBeNull();
});

test('refresh at every step loses nothing', async ({ page, request }) => {
	await openSurvey(page, 'flow');
	const sid = await sessionId(page);
	for (let i = 0; i < flowPages.length; i++) {
		await onPage(page, i + 1);
		await page.reload();
		await onPage(page, i + 1);
		await flowPages[i]!(page);
		// Refresh straight after typing, before any network save could be due.
		await page.reload();
		await onPage(page, i + 1);
		await expectFlowPage(page, i);
		await next(page);
	}
	await thanks(page);
	await page.reload();
	// After submit the local copy is gone; the link starts a fresh session.
	await onPage(page, 1);
	expect(await sessionId(page)).not.toBe(sid);
	const s = await expectStoredResponse(request, sid, FLOW_EXPECTED);
	// A refresh can land a dead page's in-flight save late: the server logs it as a
	// conflict, but it is always an older prefix of what was submitted.
	expect(s.conflictsLosingData).toBe(0);
});

test('kill the tab mid-page and reopen', async ({ context, request }) => {
	let page = await context.newPage();
	await openSurvey(page, 'flow');
	const sid = await sessionId(page);
	await flowPages[0]!(page);
	await next(page);
	await onPage(page, 2);
	await flowPages[1]!(page);
	await page.close(); // no unload handlers run
	page = await context.newPage();
	await openSurvey(page, 'flow');
	await onPage(page, 2);
	expect(await sessionId(page)).toBe(sid);
	await expectFlowPage(page, 1);
	for (let i = 1; i < flowPages.length; i++) {
		if (i > 1) await flowPages[i]!(page);
		await next(page);
	}
	await thanks(page);
	await expectStoredResponse(request, sid, FLOW_EXPECTED);
});

test('offline: keep answering, then come back online', async ({ page, context, request }) => {
	await openSurvey(page, 'flow');
	const sid = await sessionId(page);
	await flowPages[0]!(page);
	await next(page);
	await saved(page);
	await context.setOffline(true);
	await flowPages[1]!(page);
	await next(page);
	await onPage(page, 3);
	await expect(page.getByTestId('save-status')).toHaveAttribute('data-status', 'offline');
	await flowPages[2]!(page);
	await next(page);
	await onPage(page, 4);
	await context.setOffline(false);
	await saved(page);
	// Before submit, the server already holds everything answered offline.
	const mid = await stored(request, sid);
	expect(mid.snapshot?.data.values).toMatchObject({ age: 34, nick: 'Sam', other_colour: 'Teal' });
	await flowPages[3]!(page);
	await context.setOffline(true);
	await next(page);
	await expect(page.getByText('Waiting for a connection')).toBeVisible();
	await context.setOffline(false);
	await thanks(page);
	const s = await expectStoredResponse(request, sid, FLOW_EXPECTED);
	expect(s.conflicts).toBe(0);
});

test('resume on a second browser with the resume link', async ({ page, browser, request }) => {
	await openSurvey(page, 'flow');
	const sid = await sessionId(page);
	await flowPages[0]!(page);
	await next(page);
	await flowPages[1]!(page);
	await next(page);
	await onPage(page, 3);
	await saved(page);
	await page.getByText('Continue on another device').click();
	const link = await page.getByTestId('resume-link').inputValue();
	expect(link).toContain('#resume=');

	const other = await browser.newContext();
	const p2 = await other.newPage();
	await p2.goto(link);
	await onPage(p2, 3);
	expect(await sessionId(p2)).toBe(sid);
	expect(p2.url()).not.toContain('resume='); // the secret leaves the address bar
	await back(p2);
	await expectFlowPage(p2, 1);
	await next(p2);
	await flowPages[2]!(p2);
	await next(p2);
	await flowPages[3]!(p2);
	await next(p2);
	await thanks(p2);
	await other.close();
	const s = await expectStoredResponse(request, sid, FLOW_EXPECTED);
	expect(s.conflicts).toBe(0);
});

test('end-only: the server has no answers before submit', async ({ page, request }) => {
	await openSurvey(page, 'endonly');
	const sid = await sessionId(page);
	await expect(page.getByTestId('resume-link')).toHaveCount(0);
	await page.getByRole('radio', { name: 'Yes' }).click();
	await next(page);
	await page.getByLabel('How many hours did you sleep last night?').fill('7');
	await page.reload(); // the browser copy survives a refresh
	await expect(page.getByLabel('How many hours did you sleep last night?')).toHaveValue('7');
	await next(page);
	await page.getByLabel('Any comment? (optional)').fill('private');
	await page.getByLabel('Any comment? (optional)').blur();
	const before = await stored(request, sid);
	expect(before.revision).toBe(0);
	expect(before.snapshot).toBeNull();
	expect(before.saveMode).toBe('end-only');
	await axe(page, 'end-only page');
	await next(page);
	await thanks(page);
	const calls = await requestsFor(request, sid);
	expect(calls.filter((c) => c.method === 'PUT')).toEqual([]);
	await expectStoredResponse(request, sid, {
		consent: { state: 'answered', value: 'yes' },
		q_a: { state: 'answered', value: 7 },
		q_b: { state: 'answered', value: 'private' }
	});
});

test.describe('storage blocked (private mode)', () => {
	test.beforeEach(async ({ context }) => {
		await context.addInitScript(() => {
			Object.defineProperty(window, 'indexedDB', { value: undefined, configurable: true });
		});
	});

	test('end-only falls back to memory with a notice, never to network saves', async ({ page, request }) => {
		await openSurvey(page, 'endonly');
		const sid = await sessionId(page);
		await expect(page.getByTestId('storage-notice')).toContainText('only in this window');
		await page.getByRole('radio', { name: 'No' }).click();
		await next(page);
		await next(page);
		await page.getByLabel('Any comment? (optional)').fill('x');
		await next(page);
		await thanks(page);
		expect((await requestsFor(request, sid)).filter((c) => c.method === 'PUT')).toEqual([]);
		await expectStoredResponse(request, sid, {
			consent: { state: 'answered', value: 'no' },
			q_a: { state: 'unanswered', value: null },
			q_b: { state: 'answered', value: 'x' }
		});
	});

	test('every-page saves every answer to the server', async ({ page, request }) => {
		await openSurvey(page, 'flow');
		const sid = await sessionId(page);
		await expect(page.getByTestId('storage-notice')).toBeVisible();
		await page.getByRole('radio', { name: 'Yes' }).click();
		await expect.poll(async () => (await stored(request, sid)).snapshot?.data.values.consent).toBe('yes');
	});
});

test('quota check: resolved through the server, survives a refresh while pending', async ({ page, context, request }) => {
	await openSurvey(page, 'quota');
	const sid = await sessionId(page);
	await page.getByRole('radio', { name: 'North' }).click();
	await context.setOffline(true);
	await next(page);
	await expect(page.getByRole('button', { name: 'Please wait…' })).toBeDisabled();
	await context.setOffline(false);
	await page.reload();
	await onPage(page, 2);
	await page.getByRole('textbox').first().fill('hello');
	await next(page);
	await thanks(page);
	const s = await stored(request, sid);
	expect(s.responses).toBe(1);
	expect(s.record?.quotas).toEqual({ qc_north: 'open' });
	expect(s.record?.answers.region).toEqual({ state: 'answered', value: 'north' });
	expect(s.record?.answers.p2_q).toEqual({ state: 'answered', value: 'hello' });
});

test('every pilot type renders accessibly (all-types fixture)', async ({ page }) => {
	await openSurvey(page, 'alltypes');
	await onPage(page, 1);
	await axe(page, 'all types');
	// No horizontal scroll (WCAG 1.4.10).
	const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
	expect(overflow).toBeLessThanOrEqual(0);
});

test('researcher hooks run sandboxed: rejectPage blocks Next, onBeforeSubmit paradata is stored', async ({ page, request }) => {
	await openSurvey(page, 'hooks');
	const sid = await sessionId(page);
	// The page CSP allows the frame script by hash and blob: workers only (runtime-design §7a).
	const csp = await page.locator('meta[http-equiv="Content-Security-Policy"]').getAttribute('content');
	expect(csp).toMatch(/script-src 'self' 'sha256-[A-Za-z0-9+/=]+'/);
	expect(csp).toContain('worker-src blob:');
	await flowPages[0]!(page);
	await next(page);
	await onPage(page, 2);
	await page.getByLabel('How old are you?').fill('99');
	await page.getByLabel('What should we call you?').fill('Sam');
	await next(page);
	await expect(page.locator('iframe[title="hooks"]')).toHaveAttribute('sandbox', 'allow-scripts');
	const summary = page.getByTestId('error-summary');
	await expect(summary).toBeFocused();
	await expect(summary).toContainText('Hook says: not 99.');
	await onPage(page, 2);
	await flowPages[1]!(page);
	await next(page);
	await onPage(page, 3);
	await flowPages[2]!(page);
	await next(page);
	await onPage(page, 4);
	await flowPages[3]!(page);
	await next(page);
	await thanks(page);
	const r = await request.get(`/__test/sessions/${sid}`);
	const s = (await r.json()) as { record: { hooks?: { paradata: Array<{ key: string; value: unknown }> } } };
	expect(s.record.hooks?.paradata).toEqual([expect.objectContaining({ key: 'hooked', value: true })]);
});

test.describe('German browser (de-DE), English-only survey', () => {
	test.use({ locale: 'de-DE' });
	test('falls back to the plan default language; app strings follow the session language', async ({ page }) => {
		await openSurvey(page, 'flow');
		await onPage(page, 1);
		await expect(page.getByRole('button', { name: 'Next' })).toBeVisible();
		expect(await page.locator('main').getAttribute('lang')).toBe('en');
	});
});
