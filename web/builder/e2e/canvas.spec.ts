import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';
import { axe, fillRich, signIn, writeHeaders } from './fixtures';

// The editor canvas shows each question as its rich per-family card (task B14 wiring B5's
// lib/cards), against a real osp-api on SQLite: a survey with all nine types (fixtures
// 01-all-types plus 38-matrix's grid and 39-slider's slider); edits in the properties
// panel show on the card at once; 320 px has no page scroll; axe in light and dark.

type Survey = { blocks: { id: string; pages: { id: string; items: unknown[] }[] }[]; [k: string]: unknown };
const fixture = (name: string) =>
	JSON.parse(readFileSync(new URL(`../../../fixtures/${name}/survey.json`, import.meta.url), 'utf8')) as Survey & {
		choiceLists?: unknown[];
	};

async function openAllTypes(page: Page): Promise<string> {
	await signIn(page);
	await page.getByLabel('New survey title').fill(`Canvas cards ${Date.now()}`);
	await page.getByRole('button', { name: 'Create survey' }).click();
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	await page.waitForLoadState('load');
	await expect(page.getByRole('button', { name: /Add question to/ }).first()).toBeVisible();
	const id = page.url().split('/').pop()!;

	const all = fixture('01-all-types');
	const grid = fixture('38-matrix').blocks[0].pages[0].items[0];
	const slider = fixture('39-slider').blocks[0].pages[0].items[0];
	const start = (await (await page.request.get(`/api/surveys/${id}`)).json()) as { survey: Survey };
	const survey = structuredClone(start.survey);
	survey.choiceLists = all.choiceLists;
	survey.blocks[0].pages[0].items = [...all.blocks[0].pages[0].items, grid, slider];
	const r = await page.request.post(`/api/surveys/${id}/ops`, {
		headers: await writeHeaders(page),
		data: { baseRevision: 0, ops: [{ op: 'replace_survey', params: { survey } }] }
	});
	expect(r.status()).toBe(200);
	await page.reload();
	await page.waitForLoadState('load');
	await expect(card(page, 'taste')).toBeVisible();
	return id;
}

const card = (page: Page, id: string) => page.locator(`#pane-canvas [data-question-card="${id}"]`);
const saved = (page: Page) => page.getByRole('banner').getByRole('status').first();

test('every type shows its card: grid rows × columns, slider ends, choices', async ({ page }) => {
	await openAllTypes(page);
	const families: [string, string][] = [
		['note_intro', 'note'],
		['n_int', 'number'],
		['n_dec', 'number'],
		['t_text', 'text'],
		['s_single', 'choice'],
		['m_multi', 'choice'],
		['d_date', 'text'],
		['taste', 'matrix'],
		['pain', 'scale']
	];
	for (const [id, family] of families) await expect(card(page, id)).toHaveAttribute('data-family', family);

	const grid = card(page, 'taste');
	for (const s of ['Tea', 'Coffee', 'Cocoa (optional)', 'Poor', 'Fine', 'Good']) await expect(grid).toContainText(s);
	const slider = card(page, 'pain');
	await expect(slider).toContainText('None');
	await expect(slider).toContainText('Worst imaginable');
	for (const s of ['Apple', 'Banana', 'Cherry']) await expect(card(page, 's_single')).toContainText(s);
	for (const s of ['Red', 'Green', 'Blue']) await expect(card(page, 'm_multi')).toContainText(s);

	// Click selects: outline and aria-current follow.
	await page.locator('#card-taste').click();
	await expect(page.locator('#card-taste')).toHaveAttribute('aria-current', 'true');
	await expect(page.getByRole('treeitem', { name: /How do you rate these drinks/ })).toHaveAttribute(
		'aria-selected',
		'true'
	);
	// Enter on a focused card selects it too.
	await page.locator('#card-pain').focus();
	await page.keyboard.press('Enter');
	await expect(page.locator('#card-pain')).toHaveAttribute('aria-current', 'true');
});

test('edits in the properties panel update the card at once', async ({ page }) => {
	await openAllTypes(page);
	await page.locator('#card-taste').click();
	const props = page.getByRole('complementary', { name: 'Properties' });

	// The grid's question text.
	const text = props.getByRole('textbox', { name: 'Question text' });
	await fillRich(page, text, 'Rate these hot drinks');
	await page.keyboard.press('Tab');
	await expect(card(page, 'taste')).toContainText('Rate these hot drinks');
	await expect(saved(page)).toHaveText(/All changes saved/);

	// A column label, in the choices editor (rows have their own, e2e/rows.spec.ts).
	await props.getByRole('button', { name: /Edit choices/ }).click();
	const dialog = page.getByRole('dialog', { name: 'Edit choices' });
	await expect(dialog).toBeVisible();
	await dialog.getByLabel('Label for choice 1').fill('Awful');
	await dialog.getByLabel('Label for choice 1').press('Tab');
	await expect(saved(page)).toHaveText(/All changes saved/);
	await dialog.getByRole('button', { name: 'Done' }).click();
	await expect(card(page, 'taste')).toContainText('Awful');
	await expect(card(page, 'taste')).not.toContainText('Poor');
});

test('320 px: no horizontal page scroll, 44 px targets', async ({ page }) => {
	await page.setViewportSize({ width: 320, height: 700 });
	await openAllTypes(page);
	await expect(card(page, 'taste')).toContainText('Coffee');
	const overflow = await page.evaluate(() => {
		const els = [document.documentElement, document.getElementById('pane-canvas')!];
		return els.map((e) => e.scrollWidth - e.clientWidth);
	});
	expect(overflow.every((d) => d <= 0)).toBe(true);
	// Every card fits inside the canvas.
	const canvas = (await page.locator('#pane-canvas').boundingBox())!;
	for (const id of ['taste', 'pain', 's_single']) {
		const b = (await card(page, id).boundingBox())!;
		expect(b.x + b.width).toBeLessThanOrEqual(canvas.x + canvas.width + 1);
	}
	// The card's select target covers the whole card, well over 44 px.
	const hit = (await card(page, 'n_int').boundingBox())!;
	expect(hit.height).toBeGreaterThanOrEqual(44);
});

for (const scheme of ['light', 'dark'] as const) {
	test(`axe-clean with every card, ${scheme}`, async ({ page }) => {
		await page.emulateMedia({ colorScheme: scheme });
		await openAllTypes(page);
		await page.locator('#card-taste').click();
		await expect(saved(page)).toHaveText(/All changes saved/);
		expect(await axe(page)).toEqual([]);
	});
}
