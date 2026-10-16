import { expect, test, type Page } from '@playwright/test';
import { axe } from './fixtures';

// Participant widgets gallery (/dev/widgets): runtime-design §6 rules at every width, axe,
// and visual snapshots; plus long-German and Arabic (RTL) variants.
const WIDTHS = [320, 375, 768, 1440] as const;
const VARIANTS = ['en', 'de', 'ar'] as const;

async function open(page: Page, variant: string, width: number) {
	await page.setViewportSize({ width, height: 900 });
	await page.goto(`/dev/widgets?variant=${variant}`);
	await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
	await expect(page.locator('[data-question="matrix-empty"] .matrix')).toHaveAttribute('data-layout', /./);
	await page.evaluate(() => document.fonts.ready);
}

/** Interactive widget controls that are smaller than 44×44 CSS px. */
function undersizedTargets(page: Page) {
	return page.evaluate(() => {
		const sel =
			'.osp-q :is(input:not([type=hidden]), textarea, button, [role=radio], [role=checkbox], [role=slider])';
		return [...document.querySelectorAll<HTMLElement>(sel)]
			.filter((el) => !el.closest('[aria-hidden="true"]') && getComputedStyle(el).visibility !== 'hidden')
			.filter((el) => !el.matches('[aria-hidden="true"], .osp-visually-hidden'))
			.map((el) => ({ el, r: el.getBoundingClientRect() }))
			.filter(({ r }) => r.width > 1 && (r.width < 44 || r.height < 44))
			.map(({ el, r }) => `${el.id || el.tagName} ${Math.round(r.width)}×${Math.round(r.height)}`);
	});
}

/** Text inputs whose font is under 16 px (iOS zooms on focus). */
function smallInputFonts(page: Page) {
	return page.evaluate(() =>
		[...document.querySelectorAll<HTMLElement>('.osp-q :is(input:not([type=hidden]), textarea)')]
			.filter((el) => parseFloat(getComputedStyle(el).fontSize) < 16)
			.map((el) => `${el.id} ${getComputedStyle(el).fontSize}`)
	);
}

for (const variant of VARIANTS) {
	for (const width of WIDTHS) {
		test(`widgets ${variant} @ ${width}px: no h-scroll, 44px targets, 16px inputs, axe, snapshot`, async ({
			page
		}) => {
			await open(page, variant, width);

			const scroll = await page.evaluate(() => document.documentElement.scrollWidth);
			expect(scroll, 'no horizontal scroll').toBeLessThanOrEqual(width);
			expect(await undersizedTargets(page)).toEqual([]);
			expect(await smallInputFonts(page)).toEqual([]);
			expect(await axe(page)).toEqual([]);

			await expect(page).toHaveScreenshot(`widgets-${variant}-${width}.png`, { fullPage: true });
		});
	}
}

test.describe('dark theme', () => {
	test.use({ colorScheme: 'dark' });
	for (const width of [320, 1440]) {
		test(`widgets axe-clean in dark @ ${width}px`, async ({ page }) => {
			await open(page, 'en', width);
			expect(await axe(page)).toEqual([]);
		});
	}
});

test.describe('widgets behaviour in a real browser', () => {
	test('matrix is a table when it fits and cards when it does not, in one DOM', async ({ page }) => {
		await open(page, 'en', 1440);
		const matrix = page.locator('[data-question="matrix-answered"]');
		await expect(matrix.locator('.matrix')).toHaveAttribute('data-layout', 'table');
		const radios = await matrix.getByRole('radio').count();
		await page.setViewportSize({ width: 320, height: 900 });
		await expect(matrix.locator('.matrix')).toHaveAttribute('data-layout', 'cards');
		expect(await matrix.getByRole('radio').count()).toBe(radios);
		await expect(
			matrix.getByRole('radiogroup', { name: 'I would recommend it to a friend' }).getByRole('radio', {
				name: 'Strongly agree'
			})
		).toBeChecked();
	});

	test('radio arrows select, Space toggles checkboxes', async ({ page }) => {
		await open(page, 'en', 375);
		const single = page.locator('[data-question="single-empty"]');
		await single.getByRole('radio', { name: 'Apple' }).focus();
		await page.keyboard.press('ArrowDown');
		await expect(single.getByRole('radio', { name: 'Pear' })).toBeFocused();
		await expect(single.getByRole('radio', { name: 'Pear' })).toBeChecked();

		const multi = page.locator('[data-question="multi-empty"]');
		await multi.getByRole('checkbox', { name: 'Car' }).focus();
		await page.keyboard.press('Space');
		await expect(multi.getByRole('checkbox', { name: 'Car' })).toBeChecked();
	});

	test('slider has no thumb until touched; keys and the track answer it', async ({ page }) => {
		await open(page, 'en', 375);
		const q = page.locator('[data-question="slider-empty"]');
		const thumb = q.getByRole('slider');
		const knobVisibility = () =>
			thumb.evaluate((el) => getComputedStyle(el, '::after').visibility);
		await expect(thumb).toHaveAttribute('aria-valuetext', 'Not answered');
		expect(await knobVisibility()).toBe('hidden');

		await thumb.focus();
		await page.keyboard.press('ArrowRight');
		await expect(thumb).toHaveAttribute('aria-valuetext', '6');
		expect(await knobVisibility()).toBe('visible');

		const other = page.locator('[data-question="slider-error"]');
		const track = other.locator('.osp-slider-root');
		await track.scrollIntoViewIfNeeded();
		const box = (await track.boundingBox())!;
		await page.mouse.click(box.x + box.width * 0.9, box.y + box.height / 2);
		await expect(other.getByRole('slider')).toHaveAttribute('aria-valuetext', '9');
	});

	test('RTL: Arabic flows right to left, and arrows follow the reading direction', async ({ page }) => {
		await open(page, 'ar', 375);
		const q = page.locator('[data-question="single-empty"]');
		const row = q.getByRole('radio').first();
		const ind = (await row.locator('.osp-choice-ind').boundingBox())!;
		const text = (await row.locator('.osp-choice-text').boundingBox())!;
		expect(ind.x).toBeGreaterThan(text.x);

		const slider = page.locator('[data-question="slider-empty"]').getByRole('slider');
		await slider.focus();
		await page.keyboard.press('ArrowLeft');
		await expect(slider).toHaveAttribute('aria-valuenow', '6');
	});

	test('conditional reveal is announced once; reduced motion skips the animation', async ({ page }) => {
		await page.emulateMedia({ reducedMotion: 'reduce' });
		await open(page, 'en', 375);
		await page.getByRole('button', { name: 'Show the follow-up question' }).click();
		const q = page.locator('[data-question="follow-up"]');
		await expect(q).toBeVisible();
		await expect(page.getByTestId('announcer')).toHaveText('New question: Which other fruit do you eat?');
		expect(await q.evaluate((el) => getComputedStyle(el).animationName)).toBe('none');
	});

	test('number and date format messages appear after leaving the field', async ({ page }) => {
		await open(page, 'de', 375);
		const dec = page.locator('[data-question="decimal-empty"]').getByRole('textbox');
		await dec.fill('72.5.1');
		await dec.blur();
		await expect(page.locator('[data-question="decimal-empty"]')).toContainText('z. B. 12,5');
		await expect(dec).toHaveAttribute('aria-invalid', 'true');

		const date = page.locator('[data-question="date-empty"]');
		await date.getByRole('textbox', { name: 'Tag' }).fill('31');
		await date.getByRole('textbox', { name: 'Monat' }).fill('2');
		await date.getByRole('textbox', { name: 'Jahr' }).fill('2024');
		await date.getByRole('textbox', { name: 'Jahr' }).blur();
		await expect(date).toContainText('Geben Sie ein gültiges Datum ein.');
	});
});
