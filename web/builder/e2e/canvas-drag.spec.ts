import { expect, test, type Page } from '@playwright/test';
import { axe, focused, signIn, writeHeaders } from './fixtures';

// Drag and drop on the canvas (task B19), end to end against a real osp-api on SQLite,
// with real mouse drags (page.mouse down / move with steps / up) and a CDP touch drag:
// a toolbox type between cards 1 and 2 and onto a new page, a card reordered (and
// undone), Escape and drops outside do nothing, auto-scroll at the pane's edge, axe, and
// the 320 px tap-to-place fallback.

// Tall enough that every card of the seeded survey is on screen (drops only land on the
// visible canvas); the scroll, touch and 320 px tests set their own size.
test.use({ viewport: { width: 1280, height: 1400 } });

const banner = (page: Page) => page.getByRole('banner');
const saved = (page: Page) => banner(page).getByRole('status').first();
const toolType = (page: Page, name: string) => page.getByRole('button', { name: `Add ${name} question`, exact: true });
const canvas = (page: Page) => page.getByRole('main', { name: 'Canvas' });
const slot = (page: Page, id: string) => canvas(page).locator(`[data-canvas-question="${id}"]`);
const pageZone = (page: Page, id: string) => canvas(page).locator(`[data-canvas-page="${id}"]`);

/** Each page's questions from the API: `q_*` ids as they are, others by type. */
async function pagesOf(page: Page): Promise<string[][]> {
	const id = page.url().split('/').pop()!;
	const d = await (await page.request.get(`/api/surveys/${id}`)).json();
	return d.survey.blocks.flatMap((b: { pages: { items: { id: string; type: string }[] }[] }) =>
		b.pages.map((p) => p.items.map((q) => (q.id.startsWith('q_') ? q.id : q.type)))
	);
}

/** Page one: the starter question, q_a, q_b (+ extras); p_two: its new question, q_c; p_three: its new question. */
async function seededSurvey(page: Page, title: string, extra = 0) {
	await signIn(page);
	await page.getByLabel('New survey title').fill(title);
	await page.getByRole('button', { name: 'Create survey' }).click();
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	const surveyId = page.url().split('/').pop()!;
	const detail = await (await page.request.get(`/api/surveys/${surveyId}`)).json();
	const block = detail.survey.blocks[0];
	const p1 = block.pages[0].id;
	const more = Array.from({ length: extra }, (_, i) => ({
		op: 'add_question',
		params: { page: p1, id: `q_x${i}`, label: `Extra ${i}` }
	}));
	const r = await page.request.post(`/api/surveys/${surveyId}/ops`, {
		headers: await writeHeaders(page),
		data: {
			baseRevision: detail.revision,
			ops: [
				{ op: 'add_question', params: { page: p1, id: 'q_a', label: 'Alpha' } },
				{ op: 'add_question', params: { page: p1, id: 'q_b', label: 'Bravo' } },
				...more,
				{ op: 'add_page', params: { block: block.id, id: 'p_two' } },
				{ op: 'add_question', params: { page: 'p_two', id: 'q_c', label: 'Charlie' } },
				{ op: 'add_page', params: { block: block.id, id: 'p_three' } }
			]
		}
	});
	expect(r.status()).toBe(200);
	await page.reload();
	await page.waitForLoadState('load');
	await expect(page.getByRole('button', { name: /Add question to/ }).first()).toBeVisible();
	return { p1 };
}

async function centre(page: Page, locator: ReturnType<Page['locator']>) {
	const b = (await locator.boundingBox())!;
	return { x: b.x + b.width / 2, y: b.y + b.height / 2, box: b };
}

/** Pick a toolbox type up with the mouse and carry it to (x, y); the caller drops. */
async function carryType(page: Page, name: string, to: { x: number; y: number }) {
	const from = await centre(page, toolType(page, name));
	await page.mouse.move(from.x, from.y);
	await page.mouse.down();
	await page.mouse.move(from.x + 10, from.y - 10, { steps: 3 });
	await page.mouse.move(to.x, to.y, { steps: 10 });
}

/** Pick a card up by its middle with the mouse and carry it to (x, y). */
async function carryCard(page: Page, id: string, to: { x: number; y: number }) {
	const from = await centre(page, slot(page, id).locator('[data-question-card]'));
	await page.mouse.move(from.x, from.y);
	await page.mouse.down();
	await page.mouse.move(from.x, from.y + 8, { steps: 2 });
	await page.mouse.move(to.x, to.y, { steps: 10 });
}

/** The y in the gap between two cards. */
async function gapBetween(page: Page, upper: ReturnType<Page['locator']>, lower: ReturnType<Page['locator']>) {
	const a = (await upper.boundingBox())!;
	const b = (await lower.boundingBox())!;
	return { x: b.x + b.width / 2, y: (a.y + a.height + b.y) / 2 };
}

test('a type dragged between cards 1 and 2, then onto a new page', async ({ page }) => {
	await seededSurvey(page, `Canvas drag ${Date.now()}`);
	const cards = canvas(page).locator('[data-canvas-question]');
	await expect(cards).toHaveCount(6);

	// Between the first two cards: the line shows on card 2 (and in the outline too).
	const to = await gapBetween(page, cards.nth(0), cards.nth(1));
	await carryType(page, 'Slider', to);
	await expect(cards.nth(1)).toHaveAttribute('data-drop', 'before');
	await expect(canvas(page).locator('[data-drop]')).toHaveCount(1);
	await expect(page.getByRole('treeitem', { name: 'Alpha', exact: true })).toHaveAttribute('data-drop', 'before');
	await page.mouse.up();
	await expect(page.getByTestId('question-type')).toHaveText('Slider');
	await expect(focused(page)).toHaveAccessibleName('Question text');
	await expect(saved(page)).toHaveText(/All changes saved/);
	// At rest (mid-drag the picked-up toolbox type is faded on purpose).
	expect(await axe(page)).toEqual([]);
	let pages = await pagesOf(page);
	expect(pages[0].slice(1)).toEqual(['slider', 'q_a', 'q_b']);

	// A page just added (the schema never lets a page be empty: it starts with one new
	// question): over its heading, the type goes at its start.
	const fresh = pageZone(page, 'p_three');
	await fresh.getByRole('button', { name: 'Page: p_three' }).scrollIntoViewIfNeeded();
	const head = await centre(page, fresh.getByRole('button', { name: 'Page: p_three' }));
	await carryType(page, 'Note', head);
	await expect(fresh.locator('[data-canvas-question]').first()).toHaveAttribute('data-drop', 'before');
	await page.mouse.up();
	await expect(page.getByTestId('question-type')).toHaveText('Note');
	await expect(saved(page)).toHaveText(/All changes saved/);
	pages = await pagesOf(page);
	expect(pages[2]).toHaveLength(2);
	expect(pages[2][0]).toBe('note');
	await expect(canvas(page).locator('[data-drop]')).toHaveCount(0);
});

test('Escape cancels a type drag; letting go outside the canvas adds nothing', async ({ page }) => {
	await seededSurvey(page, `Canvas cancel ${Date.now()}`);
	const before = await pagesOf(page);
	const to = await gapBetween(page, slot(page, 'q_a'), slot(page, 'q_b'));
	await carryType(page, 'Text', to);
	await expect(slot(page, 'q_b')).toHaveAttribute('data-drop', 'before');
	await page.keyboard.press('Escape');
	await expect(page.locator('[data-drop]')).toHaveCount(0);
	await page.mouse.up();

	// Over the properties pane: no gap, nothing added.
	const props = await centre(page, page.locator('#pane-properties'));
	await carryType(page, 'Text', props);
	await expect(page.locator('[data-drop]')).toHaveCount(0);
	await page.mouse.up();
	await page.waitForTimeout(300);
	expect(await pagesOf(page)).toEqual(before);
});

test('a card dragged to a new place reorders (one move); undo puts it back', async ({ page }) => {
	await seededSurvey(page, `Canvas reorder ${Date.now()}`);
	// Bravo above Alpha.
	const to = await gapBetween(page, canvas(page).locator('[data-canvas-question]').first(), slot(page, 'q_a'));
	await carryCard(page, 'q_b', to);
	await expect(slot(page, 'q_b')).toHaveClass(/moving/);
	await expect(slot(page, 'q_a')).toHaveAttribute('data-drop', 'before');
	await page.mouse.up();
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect((await pagesOf(page))[0].slice(1)).toEqual(['q_b', 'q_a']);
	await expect(page.locator('#card-q_b')).toBeFocused();
	await expect(page.locator('#card-q_b')).toHaveAttribute('aria-current', 'true');

	// Across pages: Alpha to the end of p_two.
	const charlie = (await slot(page, 'q_c').boundingBox())!;
	await carryCard(page, 'q_a', { x: charlie.x + charlie.width / 2, y: charlie.y + charlie.height - 4 });
	await expect(slot(page, 'q_c')).toHaveAttribute('data-drop', 'after');
	await page.mouse.up();
	await expect(saved(page)).toHaveText(/All changes saved/);
	let pages = await pagesOf(page);
	expect(pages[0].slice(1)).toEqual(['q_b']);
	expect(pages[1].slice(-2)).toEqual(['q_c', 'q_a']);

	const undo = banner(page).getByRole('button', { name: 'Undo', exact: true });
	await undo.click();
	await expect(saved(page)).toHaveText(/All changes saved/);
	await undo.click();
	await expect(saved(page)).toHaveText(/All changes saved/);
	pages = await pagesOf(page);
	expect(pages[0].slice(1)).toEqual(['q_a', 'q_b']);
	await expect(slot(page, 'q_a')).toBeVisible();
});

test('a card drag: Escape cancels, outside does nothing, next to itself does nothing', async ({ page }) => {
	await seededSurvey(page, `Canvas card cancel ${Date.now()}`);
	const before = await pagesOf(page);
	const charlie = await centre(page, slot(page, 'q_c'));
	await carryCard(page, 'q_a', { x: charlie.x, y: charlie.y + 30 });
	await expect(canvas(page).locator('[data-drop]')).toHaveCount(1);
	await page.keyboard.press('Escape');
	await expect(page.locator('[data-drop]')).toHaveCount(0);
	await expect(slot(page, 'q_a')).not.toHaveClass(/moving/);
	await page.mouse.up();

	const props = await centre(page, page.locator('#pane-properties'));
	await carryCard(page, 'q_a', props);
	await expect(page.locator('[data-drop]')).toHaveCount(0);
	await page.mouse.up();

	const own = await centre(page, slot(page, 'q_a'));
	await carryCard(page, 'q_a', { x: own.x, y: own.y + 20 });
	await expect(page.locator('[data-drop]')).toHaveCount(0);
	await page.mouse.up();
	await page.waitForTimeout(300);
	expect(await pagesOf(page)).toEqual(before);
});

test('near the bottom edge the canvas scrolls while dragging', async ({ page }) => {
	await page.setViewportSize({ width: 1280, height: 560 });
	await seededSurvey(page, `Canvas scroll ${Date.now()}`, 6);
	const pane = page.locator('#pane-canvas');
	expect(await pane.evaluate((el) => el.scrollTop)).toBe(0);
	const box = (await pane.boundingBox())!;
	await carryCard(page, 'q_a', { x: box.x + box.width / 2, y: box.y + box.height - 8 });
	await expect.poll(() => pane.evaluate((el) => el.scrollTop), { timeout: 5000 }).toBeGreaterThan(100);
	// The gap follows the scroll: it is now further down the survey.
	await expect(canvas(page).locator('[data-drop]')).toHaveCount(1);
	await page.keyboard.press('Escape');
	await page.mouse.up();
});

test.describe('touch', () => {
	test.use({ hasTouch: true, viewport: { width: 820, height: 900 } });

	test('a touch drag by the grip reorders a card', async ({ page }) => {
		await seededSurvey(page, `Canvas touch ${Date.now()}`);
		const grip = await centre(page, slot(page, 'q_b').locator('[data-drag-handle]'));
		const to = await gapBetween(page, canvas(page).locator('[data-canvas-question]').first(), slot(page, 'q_a'));
		const cdp = await page.context().newCDPSession(page);
		const touch = (type: string, x: number, y: number) =>
			cdp.send('Input.dispatchTouchEvent', {
				type,
				touchPoints: type === 'touchEnd' ? [] : [{ x: Math.round(x), y: Math.round(y) }]
			});
		await touch('touchStart', grip.x, grip.y);
		const steps = 12;
		for (let i = 1; i <= steps; i++) {
			await touch('touchMove', grip.x + ((to.x - grip.x) * i) / steps, grip.y + ((to.y - grip.y) * i) / steps);
		}
		await expect(slot(page, 'q_a')).toHaveAttribute('data-drop', 'before');
		await touch('touchEnd', to.x, to.y);
		await expect(saved(page)).toHaveText(/All changes saved/);
		expect((await pagesOf(page))[0].slice(1)).toEqual(['q_b', 'q_a']);
	});
});

test('320 px: tap a type, then tap "Place here"; Cancel and axe', async ({ page }) => {
	await page.setViewportSize({ width: 320, height: 640 });
	await seededSurvey(page, `Canvas place ${Date.now()}`);
	const openTypes = async () => {
		await banner(page).getByRole('button', { name: 'Outline pane' }).click();
		const toggle = page.getByRole('button', { name: 'Question types' });
		if ((await toggle.getAttribute('aria-expanded')) === 'false') await toggle.click();
	};
	await openTypes();
	await expect(page.getByText('Tap a type, then tap where it goes on the canvas.')).toBeVisible();
	await toolType(page, 'Date').click();
	// The overlay closes; every gap gets a button; Cancel leaves without adding.
	await expect(page.getByText('Choose where the Date question goes.')).toBeVisible();
	await expect(canvas(page).locator('[data-place-page]')).toHaveCount(4 + 3 + 2);
	expect(await axe(page)).toEqual([]);
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
	await canvas(page).getByRole('button', { name: 'Cancel', exact: true }).click();
	await expect(canvas(page).locator('[data-place-page]')).toHaveCount(0);

	await openTypes();
	await toolType(page, 'Date').click();
	await canvas(page).getByRole('button', { name: 'Place here between Alpha and Bravo', exact: false }).click();
	await expect(page.getByTestId('question-type')).toHaveText('Date');
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect((await pagesOf(page))[0].slice(1)).toEqual(['q_a', 'date', 'q_b']);
	await expect(canvas(page).locator('[data-place-page]')).toHaveCount(0);
});
