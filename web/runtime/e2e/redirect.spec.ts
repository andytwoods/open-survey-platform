/**
 * End redirects in the participant app (end-of-survey plan §4.2, task EN2), against the
 * real backend: the countdown is read once and can be cancelled, the link goes to the
 * declared template filled with the piped answer, `link` mode never navigates by itself,
 * the automatic navigation happens with no referrer, and a reload after the submit starts
 * afresh (no replayed redirect).
 */
import { expect, test, type Page } from '@playwright/test';
import { axe, next, onPage, openSurvey, sessionId, thanks } from './helpers';

const PROLIFIC = 'https://app.prolific.com/submissions/complete';

/** Catch the navigation to Prolific in the browser; nothing leaves the machine. */
async function catchProlific(page: Page) {
	const seen: Array<{ url: string; referer: string | undefined }> = [];
	await page.route(`${PROLIFIC}**`, async (route) => {
		seen.push({ url: route.request().url(), referer: route.request().headers()['referer'] });
		await route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>Prolific</title><h1>Landed</h1>' });
	});
	return seen;
}

async function complete(page: Page, rating = '7') {
	await openSurvey(page, 'redirect');
	await onPage(page, 1);
	await page.getByRole('radio', { name: 'Yes' }).click();
	await next(page);
	await onPage(page, 2);
	await page.getByLabel('Rate your breakfast today from 1 to 10.').fill(rating);
	await next(page);
	await onPage(page, 3);
	await next(page);
	await thanks(page);
}

test('auto mode: countdown is aria-hidden, announced once, and "Stay on this page" cancels it', async ({ page }) => {
	const seen = await catchProlific(page);
	await complete(page);
	const redirect = page.getByTestId('redirect');
	await expect(redirect).toHaveAttribute('data-state', 'counting');
	// The ending's own text and status are on screen before the countdown, heading focused.
	await expect(page.getByTestId('thanks')).toHaveText('Thank you for your time');
	await expect(page.getByTestId('thanks')).toBeFocused();
	await expect(page.locator('[data-ending-status="recorded"]')).toBeVisible();
	const countdown = page.getByTestId('redirect-countdown');
	await expect(countdown).toHaveAttribute('aria-hidden', 'true');
	await expect(countdown).toContainText('app.prolific.com');
	await expect(page.locator('[aria-live="polite"]')).toContainText('You will be taken to app.prolific.com in 3 seconds');
	const go = page.getByRole('link', { name: 'Back to Prolific' });
	await expect(go).toHaveAttribute('href', `${PROLIFIC}?cc=C1AB2&r=7`);
	await axe(page, 'thank-you page with a redirect');
	await page.getByRole('button', { name: 'Stay on this page' }).click();
	await expect(redirect).toHaveAttribute('data-state', 'cancelled');
	await expect(countdown).toHaveCount(0);
	await page.waitForTimeout(4000);
	expect(page.url()).toContain('/s/');
	expect(seen).toEqual([]);
	await expect(go).toBeVisible(); // the link stays for later
});

test('auto mode: navigates to the filled URL when the countdown ends, without a referrer', async ({ page }) => {
	const seen = await catchProlific(page);
	await complete(page, '9');
	await page.waitForURL(`${PROLIFIC}?cc=C1AB2&r=9`, { timeout: 15_000 });
	expect(seen.map((s) => s.url)).toEqual([`${PROLIFIC}?cc=C1AB2&r=9`]);
	expect(seen[0]!.referer).toBeUndefined();
});

test('link mode: the button is shown and nothing navigates by itself', async ({ page }) => {
	const seen = await catchProlific(page);
	await openSurvey(page, 'redirect');
	await page.getByRole('radio', { name: 'No' }).click();
	await next(page);
	await expect(page.getByTestId('thanks')).toHaveText('Thank you for your interest');
	const redirect = page.getByTestId('redirect');
	await expect(redirect).toHaveAttribute('data-state', 'link');
	await expect(page.getByTestId('redirect-countdown')).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Stay on this page' })).toHaveCount(0);
	const go = page.getByRole('link', { name: 'Continue to app.prolific.com' });
	await expect(go).toHaveAttribute('href', `${PROLIFIC}?cc=SCREEN1&r=ineligible`);
	await axe(page, 'screened-out page with a link');
	await page.waitForTimeout(2500);
	expect(seen).toEqual([]);
	await go.click();
	await page.waitForURL(`${PROLIFIC}?cc=SCREEN1&r=ineligible`);
});

test('a reload after the submit starts a new session: the redirect is not replayed', async ({ page }) => {
	const seen = await catchProlific(page);
	await complete(page);
	const sid = await sessionId(page);
	await page.getByRole('button', { name: 'Stay on this page' }).click();
	await page.reload();
	await onPage(page, 1);
	expect(await sessionId(page)).not.toBe(sid);
	await page.waitForTimeout(1500);
	expect(seen).toEqual([]);
	expect(page.url()).toContain('/s/');
});
