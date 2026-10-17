import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { applyOps, createSurvey, DEMO_TITLE } from '../demo/seed';

/**
 * Screenshots for the docs site (`make docs-screenshots`; mkdocs.yml at the repo root).
 * Every image is drawn from the real builder and participant app on a throwaway stack
 * (playwright.config.ts), with the invented "Coffee and sleep study" from ../demo/seed.ts:
 * no real personal data (AGENTS.md rule 7). The PNGs land in docs/assets/screenshots/ and
 * are committed, so the site builds without a browser.
 */

const OUT = process.env.OSP_DOCS_SCREENSHOTS ?? join(process.cwd(), '..', '..', 'docs', 'assets', 'screenshots');

const banner = (page: Page) => page.getByRole('banner');
const saved = (page: Page) => expect(banner(page).getByRole('status').first()).toHaveText(/All changes saved/);
const props = (page: Page) => page.getByRole('complementary', { name: 'Properties' });
const tree = (page: Page) => page.getByRole('tree', { name: 'Survey outline' });
const select = async (page: Page, id: string) => {
	await tree(page).locator(`[role="treeitem"][data-id="${id}"]`).click();
	await expect(props(page).getByRole('textbox', { name: 'Question text' })).toBeVisible();
};

/** Write `name`.png: the viewport, or the whole page. */
async function shot(page: Page, name: string, opts: { fullPage?: boolean } = {}) {
	mkdirSync(OUT, { recursive: true });
	// Let fonts, icons and transitions settle (the only fixed wait).
	await page.waitForTimeout(400);
	await page.screenshot({ path: join(OUT, `${name}.png`), fullPage: opts.fullPage ?? false, animations: 'disabled' });
}

function headers(page: Page) {
	return { Origin: new URL(page.url()).origin };
}

test('builder and participant screenshots', async ({ page, browser }) => {
	// -- Surveys list --------------------------------------------------------------------
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'Your surveys' })).toBeVisible();
	const id = await createSurvey(page, DEMO_TITLE);
	await page.reload();
	await expect(page.getByRole('link', { name: DEMO_TITLE })).toBeVisible();
	await shot(page, 'surveys');

	// -- Editor ----------------------------------------------------------------------------
	await page.goto(`/surveys/${id}`);
	await expect(tree(page)).toBeVisible();
	await expect(page.locator('#pane-canvas')).toContainText('How many cups of coffee');
	await select(page, 'cups');
	await shot(page, 'editor');

	// -- Type picker -----------------------------------------------------------------------
	await page.getByRole('button', { name: /Add question to/ }).first().click();
	const picker = page.getByRole('dialog', { name: 'Add a question' });
	await expect(picker.getByRole('combobox', { name: 'Filter question types' })).toBeFocused();
	await shot(page, 'type-picker');
	await page.keyboard.press('Escape');
	await expect(picker).toBeHidden();

	// -- Choices editor --------------------------------------------------------------------
	await select(page, 'taken');
	await props(page).getByRole('button', { name: /Edit choices/ }).click();
	const choices = page.getByRole('dialog', { name: 'Edit choices' });
	await expect(choices.getByLabel('Label for choice 4')).toBeVisible();
	await shot(page, 'choices');
	await choices.getByRole('button', { name: 'Done' }).click();
	await expect(choices).toBeHidden();

	// -- Condition editor ------------------------------------------------------------------
	await select(page, 'awake');
	await props(page).getByRole('button', { name: 'Show if Edit condition…' }).click();
	const cond = page.getByRole('dialog', { name: 'Edit condition' });
	await expect(cond.getByTestId('condition-row').first()).toBeVisible();
	await shot(page, 'condition');
	await cond.getByRole('button', { name: 'Cancel' }).click();
	await expect(cond).toBeHidden();

	// -- Preview + debugger ------------------------------------------------------------------
	await banner(page).getByRole('button', { name: 'Preview' }).click();
	await expect(page.getByRole('heading', { name: 'Preview', level: 2 })).toBeVisible();
	await expect(page.getByTestId('debugger')).toBeVisible();
	await expect(page.frameLocator('[data-testid^="preview-frame-"]').first().getByText('How many cups of coffee')).toBeVisible();
	await shot(page, 'preview');

	// -- Settings: retention, consent ------------------------------------------------------
	await page.goto(`/surveys/${id}/settings`);
	await expect(page.getByRole('heading', { name: 'Survey settings', level: 2 })).toBeVisible();
	await page.getByRole('radio', { name: /Keep until I delete it/ }).click();
	await expect(page.getByTestId('retention-status')).toHaveText(/Retention is set/);
	await page.getByRole('checkbox', { name: 'Show a consent page before the first question' }).click();
	await page.getByLabel('Consent text').fill('This invented study asks about coffee and sleep. Taking part is voluntary.');
	await page.getByLabel('Agree button').fill('Yes, I take part');
	await page.keyboard.press('Tab');
	await expect(page.getByTestId('consent-preview')).toContainText('Yes, I take part');
	await saved(page);
	await page.evaluate(() => window.scrollTo(0, 0));
	await shot(page, 'settings', { fullPage: true });

	// -- Appearance ------------------------------------------------------------------------
	await page.goto(`/surveys/${id}/appearance`);
	await expect(page.getByRole('heading', { name: 'Appearance', level: 2 })).toBeVisible();
	await page.getByRole('radio', { name: 'Warm' }).click();
	await page.getByRole('button', { name: 'Use for this survey' }).click();
	await expect(page.getByTestId('survey-theme-status')).toHaveText(/This survey uses this theme/);
	await saved(page);
	await shot(page, 'appearance');

	// -- Publish ---------------------------------------------------------------------------
	await page.goto(`/surveys/${id}`);
	await expect(tree(page)).toBeVisible();
	await banner(page).getByRole('button', { name: 'Publish', exact: true }).click();
	const result = page.getByRole('dialog', { name: 'Publish' }).getByTestId('publish-result');
	await expect(result).toContainText('Published version 1');
	await shot(page, 'publish');
	const link = await result.getByLabel('Participant link').inputValue();

	// -- Participant app, desktop and phone --------------------------------------------------
	await page.goto(link);
	await expect(page.getByRole('button', { name: 'Yes, I take part' })).toBeVisible();
	await shot(page, 'participant-consent');
	await page.getByRole('button', { name: 'Yes, I take part' }).click();
	await expect(page.getByText('How many cups of coffee did you drink yesterday?')).toBeVisible();
	await shot(page, 'participant');

	const phone = await browser.newContext({
		colorScheme: 'light',
		viewport: { width: 390, height: 844 },
		deviceScaleFactor: 2,
		isMobile: true,
		hasTouch: true,
		baseURL: test.info().project.use.baseURL
	});
	const mobile = await phone.newPage();
	await mobile.goto(link);
	await expect(mobile.getByRole('button', { name: 'Yes, I take part' })).toBeVisible();
	await mobile.getByRole('button', { name: 'Yes, I take part' }).click();
	await expect(mobile.getByText('How many cups of coffee did you drink yesterday?')).toBeVisible();
	await mobile.getByLabel('How many cups of coffee did you drink yesterday?').fill('4');
	await mobile.waitForTimeout(400);
	await mobile.screenshot({ path: join(OUT, 'participant-phone.png'), animations: 'disabled' });
	await phone.close();

	// -- Flow: a randomiser over two blocks ------------------------------------------------
	// A third block through the API (the builder has no "add block" control yet), then a
	// randomiser holding it, and the Coffee block moved in with the keyboard.
	await applyOps(page, id, [{ op: 'add_block', params: { id: 'evening', title: 'Evening routine' } }]);
	await page.goto(`/surveys/${id}/flow`);
	await expect(page.getByRole('heading', { name: 'Survey flow', level: 2 })).toBeVisible();
	await page.getByRole('button', { name: 'Add node to Survey flow at position 2', exact: true }).click();
	const add = page.getByRole('dialog', { name: 'Add flow node' });
	await add.getByLabel('Node type').selectOption('randomiser');
	await add.getByLabel('First block').selectOption('evening');
	await add.getByRole('button', { name: 'Add', exact: true }).click();
	await expect(add).toBeHidden();
	await saved(page);
	const randomiser = page.locator('article[data-type="randomiser"]');
	await expect(randomiser).toBeVisible();
	await page.getByRole('button', { name: 'Move Block: Coffee', exact: true }).click();
	for (let i = 0; i < 4; i++) {
		if (await randomiser.getByRole('heading', { name: 'Block: Coffee' }).count()) break;
		await page.keyboard.press('Alt+ArrowDown');
	}
	await expect(randomiser.getByRole('heading', { name: 'Block: Coffee' })).toBeVisible();
	await saved(page);
	await page.getByRole('main').click({ position: { x: 5, y: 5 } });
	await shot(page, 'flow');

	// -- Results: the results fixture survey with its five fake responses --------------------
	await page.goto('/');
	const fixture = await (await page.request.get('/api/e2e/results-fixture')).json();
	const rid = await createSurvey(page, 'Results (invented data)', fixture);
	const seeded = await page.request.post(`/api/e2e/results-seed/${rid}`, { headers: headers(page) });
	expect(await seeded.json()).toEqual({ version: 1, responses: 5 });
	await page.goto(`/surveys/${rid}/results`);
	await expect(page.getByRole('heading', { name: 'Results', level: 2 })).toBeVisible();
	await expect(page.getByRole('list', { name: 'Questions' })).toBeVisible();
	await expect(page.getByTestId('results-count')).toHaveText('5 responses');
	await expect(page.getByRole('article', { name: 'Fruit?' }).locator('svg.marks')).toBeVisible();
	// The filter bar fills the viewport at this width: fold it so the cards show.
	const hideFilters = page.getByRole('button', { name: 'Hide filters' });
	if (await hideFilters.count()) await hideFilters.click();
	await page.getByRole('article', { name: 'Fruit?' }).scrollIntoViewIfNeeded();
	await shot(page, 'results');
});
