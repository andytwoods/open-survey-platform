/**
 * The ending's list of answers (end-of-survey plan §4.4, task EN5), against the real backend:
 * every answered question in path order with its display label once the submit is stored,
 * answers as text (never HTML), a Print button and a print stylesheet that keeps only the
 * ending and the list; nothing for an ending that does not ask for it, never after a consent
 * decline, nothing after a reload (a new session); fits 320 px; axe clean throughout.
 */
import { expect, test, type Page } from '@playwright/test';
import { axe, fillDate, next, onPage, openSurvey, sessionId, stored, thanks } from './helpers';

const agree = (page: Page) => page.getByRole('button', { name: 'I agree to take part' }).click();
const summary = (page: Page) => page.getByTestId('answer-summary');
const entries = (page: Page) => summary(page).locator(':scope > dl > div[data-item]');

/** Agree, answer every type (the matrix's coffee row and the date's neighbours left out), submit. */
async function complete(page: Page) {
	await openSurvey(page, 'summary');
	await agree(page);
	await onPage(page, 1);
	await page.getByRole('radio', { name: 'Yes' }).click();
	await next(page);
	await onPage(page, 2);
	await page.getByLabel('Rate your breakfast today from 1 to 10.').fill('8');
	await page.getByRole('checkbox', { name: 'Fruit' }).click();
	await page.getByRole('checkbox', { name: 'Toast' }).click();
	await fillDate(page, 'when', '2026-10-01');
	await page.getByLabel('Anything else?').fill('Line one\n<b>two</b>');
	await next(page);
	await onPage(page, 3);
	await page.getByRole('radiogroup', { name: 'Tea' }).getByRole('radio', { name: 'Good' }).click();
	await page.locator('[data-question="q-hunger"]').getByLabel('Or type a number').fill('4');
	await next(page);
	await thanks(page);
}

test('lists the answers in path order with display labels, as text; Print works; print media hides the controls', async ({ page, request }) => {
	await complete(page);
	const sid = await sessionId(page);
	await expect(page.getByTestId('thanks')).toHaveText('Thank you for your time');
	await expect(page.getByTestId('thanks')).toBeFocused();
	await expect(page.locator('[data-ending-status="recorded"]')).toBeVisible();
	await expect(summary(page).getByRole('heading', { name: 'Your answers', level: 2 })).toBeVisible();

	// Path order, the note left out, the matrix as one entry with its answered row only.
	await expect(entries(page)).toHaveCount(7);
	expect(await entries(page).evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.item))).toEqual([
		'eligible',
		'rating',
		'foods',
		'when',
		'comment',
		'drinks',
		'hunger'
	]);
	const dd = (item: string) => summary(page).locator(`[data-item="${item}"] > dd`);
	await expect(summary(page).locator('[data-item="eligible"] > dt')).toHaveText('Are you willing to answer a few more questions?');
	await expect(dd('eligible')).toHaveText('Yes');
	await expect(dd('rating')).toHaveText('8');
	await expect(dd('foods')).toHaveText('Toast, Fruit'); // labels, in the displayed order
	await expect(dd('when')).toHaveText('2026-10-01');
	// A multi-line answer keeps its line break and is text, never markup.
	await expect(dd('comment')).toContainText('<b>two</b>');
	await expect(dd('comment').locator('b')).toHaveCount(0);
	expect(await dd('comment').evaluate((el) => (el as HTMLElement).innerText)).toBe('Line one\n<b>two</b>');
	// A matrix row is the question `<matrix>_<row>` (C2c-1); only the answered row is listed.
	await expect(summary(page).locator('[data-item="drinks"] [data-item="drinks_tea"] dd')).toHaveText('Good');
	await expect(summary(page).locator('[data-item="drinks"] [data-item="drinks_coffee"]')).toHaveCount(0);
	await expect(dd('hunger')).toHaveText('4');
	await axe(page, 'thank-you page with the answers');

	// The same values the record holds.
	const s = await stored(request, sid);
	expect(s.record?.answers.rating).toEqual({ state: 'answered', value: 8 });
	expect(s.record?.answers.drinks_tea).toEqual({ state: 'answered', value: 3 });
	expect(s.record?.answers.drinks_coffee).toEqual({ state: 'unanswered', value: null });

	// Print: the button prints; on paper only the ending and the list remain.
	await page.evaluate(() => {
		(window as unknown as { __printed: number }).__printed = 0;
		window.print = () => void (window as unknown as { __printed: number }).__printed++;
	});
	await page.getByRole('button', { name: 'Print' }).click();
	expect(await page.evaluate(() => (window as unknown as { __printed: number }).__printed)).toBe(1);
	await page.emulateMedia({ media: 'print' });
	await expect(page.getByTestId('thanks')).toBeVisible();
	await expect(summary(page)).toBeVisible();
	await expect(entries(page).first()).toBeVisible();
	await expect(page.getByRole('button', { name: 'Print' })).toBeHidden();
	await expect(page.getByRole('button', { name: 'Withdraw my answers' })).toBeHidden();
	await page.emulateMedia({ media: 'screen' });
	await expect(page.getByRole('button', { name: 'Print' })).toBeVisible();

	// A reload after the submit starts a new session: nothing of the old answers is shown.
	await page.reload();
	await expect(page.getByTestId('consent')).toBeVisible();
	await expect(summary(page)).toHaveCount(0);
});

test('nothing is listed for an ending that does not ask for it, nor after a consent decline', async ({ page }) => {
	await openSurvey(page, 'summary');
	await agree(page);
	await onPage(page, 1);
	await page.getByRole('radio', { name: 'No' }).click();
	await next(page);
	await expect(page.getByTestId('thanks')).toHaveText('Thank you for your interest');
	await expect(summary(page)).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Print' })).toHaveCount(0);

	await openSurvey(page, 'summary');
	await page.getByRole('button', { name: 'I do not want to take part' }).click();
	await expect(page.getByTestId('declined')).toBeVisible();
	await expect(page.locator('[data-ending-status="not-recorded"]')).toBeVisible();
	await expect(summary(page)).toHaveCount(0);
});

test('the list goes once the answers are withdrawn', async ({ page }) => {
	await complete(page);
	await expect(entries(page)).toHaveCount(7);
	await page.getByRole('button', { name: 'Withdraw my answers' }).click();
	await page.getByRole('button', { name: 'Yes, delete my answers' }).click();
	await expect(page.getByTestId('withdrawn')).toBeVisible();
	await expect(summary(page)).toHaveCount(0);
});

test.describe('320 px', () => {
	test.use({ viewport: { width: 320, height: 640 } });

	test('the list fits a 320 px viewport without horizontal scrolling', async ({ page }) => {
		await complete(page);
		await expect(entries(page)).toHaveCount(7);
		expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
		expect(await summary(page).evaluate((el) => el.getBoundingClientRect().right)).toBeLessThanOrEqual(320);
		await axe(page, 'thank-you page with the answers at 320 px');
	});
});
