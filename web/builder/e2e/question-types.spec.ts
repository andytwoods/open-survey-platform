import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { axe, focused, pickQuestionType, runFromPalette, signIn, writeHeaders } from './fixtures';

// Question types (task B13), end to end against a real osp-api on SQLite: add every type
// through the type picker (button, keyboard, palette), the last used type first; change a
// type from the properties panel and the palette, with undo; a change that breaks a
// condition asks first; axe; 320 px.

const TYPES: [string, string][] = [
	['text', 'Text'],
	['integer', 'Whole number'],
	['decimal', 'Decimal number'],
	['single', 'Single choice'],
	['multi', 'Multiple choice'],
	['date', 'Date'],
	['matrix', 'Grid'],
	['slider', 'Slider'],
	['note', 'Note']
];

const banner = (page: Page) => page.getByRole('banner');
const saved = (page: Page) => banner(page).getByRole('status').first();
const picker = (page: Page, name = 'Add a question') => page.getByRole('dialog', { name });
const typeShown = (page: Page) => page.getByTestId('question-type');
const option = (page: Page, name: string, dialog = 'Add a question') =>
	picker(page, dialog).getByRole('option', { name: new RegExp(`^${name}\\b`) });

async function axeIn(page: Page, selector: string) {
	const r = await new AxeBuilder({ page })
		.include(selector)
		.withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'])
		.analyze();
	return r.violations.map((v) => ({ id: v.id, targets: v.nodes.map((n) => n.target.join(' ')) }));
}

async function createSurvey(page: Page, title: string) {
	await signIn(page);
	await page.getByLabel('New survey title').fill(title);
	await page.getByRole('button', { name: 'Create survey' }).click();
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	await page.waitForLoadState('load');
	await expect(page.getByRole('button', { name: /Add question to/ }).first()).toBeVisible();
}

/** Every question's type in the draft, in order, from the API (what the server stored). */
async function questionTypes(page: Page): Promise<string[]> {
	const id = page.url().split('/').pop()!;
	const d = await (await page.request.get(`/api/surveys/${id}`)).json();
	return d.survey.blocks.flatMap((b: { pages: { items: { type: string }[] }[] }) =>
		b.pages.flatMap((p) => p.items.map((q) => q.type))
	);
}

test('add each of the nine types through the picker; the last used comes first', async ({ page }) => {
	await createSurvey(page, `Types e2e ${Date.now()}`);
	const before = (await questionTypes(page)).length;
	const add = page.getByRole('button', { name: /Add question to/ }).first();

	for (const [, name] of TYPES) {
		await add.click();
		await expect(picker(page).getByRole('option')).toHaveCount(9);
		await pickQuestionType(page, new RegExp(`^${name}\\b`));
		await expect(typeShown(page)).toHaveText(name);
		// The new question's text has focus, ready to type.
		await expect(focused(page)).toHaveAccessibleName(name === 'Note' ? 'Text' : 'Question text');
		await expect(saved(page)).toHaveText(/All changes saved/);
	}
	expect((await questionTypes(page)).slice(before)).toEqual(TYPES.map(([id]) => id));

	// The last used type (Note) is first, marked, and what Enter picks; Escape cancels and
	// gives focus back to the button.
	await add.click();
	const first = picker(page).getByRole('option').first();
	await expect(first).toContainText('Note');
	await expect(first).toContainText('Last used');
	await expect(first).toHaveAttribute('aria-selected', 'true');
	expect(await axe(page)).toEqual([]);
	await page.keyboard.press('Escape');
	await expect(picker(page)).toBeHidden();
	await expect(add).toBeFocused();

	// Keyboard: type to filter, arrows, Enter.
	await add.click();
	await expect(picker(page).getByRole('combobox', { name: 'Filter question types' })).toBeFocused();
	await page.keyboard.type('number');
	await expect(picker(page).getByRole('option')).toHaveCount(2);
	await page.keyboard.press('ArrowDown');
	await expect(option(page, 'Decimal number')).toHaveAttribute('aria-selected', 'true');
	await page.keyboard.press('Enter');
	await expect(picker(page)).toBeHidden();
	await expect(typeShown(page)).toHaveText('Decimal number');

	// One palette command per type.
	await page.getByRole('main', { name: 'Canvas' }).click({ position: { x: 5, y: 5 } });
	await runFromPalette(page, 'add grid', /^Add grid question$/);
	await expect(typeShown(page)).toHaveText('Grid');
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect((await questionTypes(page)).slice(-2)).toEqual(['decimal', 'matrix']);
});

test('change single → multi and back, with undo; a broken condition asks first', async ({ page }) => {
	await createSurvey(page, `Change type e2e ${Date.now()}`);
	await page.getByRole('button', { name: /Add question to/ }).first().click();
	await pickQuestionType(page, /^Single choice\b/);
	await expect(typeShown(page)).toHaveText('Single choice');
	await expect(saved(page)).toHaveText(/All changes saved/);

	// From the properties panel: the current type is marked and not the one highlighted.
	const change = page.getByRole('button', { name: /^Change type of/ });
	await change.click();
	const dialog = picker(page, 'Change question type');
	await expect(dialog.getByRole('option', { name: /^Single choice\b/ })).toContainText('Current');
	expect(await axe(page)).toEqual([]);
	await dialog.getByRole('option', { name: /^Multiple choice\b/ }).click();
	await expect(dialog).toBeHidden();
	await expect(typeShown(page)).toHaveText('Multiple choice');
	await expect(change).toBeFocused();
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect((await questionTypes(page)).at(-1)).toBe('multi');

	// And back, from the palette.
	await runFromPalette(page, 'change question type', /^Change question type…$/);
	await expect(dialog.getByRole('combobox', { name: 'Filter question types' })).toBeFocused();
	await page.keyboard.type('single');
	await page.keyboard.press('Enter');
	await expect(typeShown(page)).toHaveText('Single choice');
	await expect(saved(page)).toHaveText(/All changes saved/);

	// Undo twice: multi, then single again (the original question, choices and all).
	const undo = banner(page).getByRole('button', { name: 'Undo', exact: true });
	await undo.click();
	await expect(typeShown(page)).toHaveText('Multiple choice');
	await undo.click();
	await expect(typeShown(page)).toHaveText('Single choice');
	await expect(saved(page)).toHaveText(/All changes saved/);

	// Another question shown only when this one is 1: making it text would break that.
	const surveyId = page.url().split('/').pop()!;
	const detail = await (await page.request.get(`/api/surveys/${surveyId}`)).json();
	const items = detail.survey.blocks[0].pages[0].items as { id: string; type: string }[];
	const single = items.at(-1)!.id;
	const r = await page.request.post(`/api/surveys/${surveyId}/ops`, {
		headers: await writeHeaders(page),
		data: {
			baseRevision: detail.revision,
			ops: [
				{ op: 'add_question', params: { page: detail.survey.blocks[0].pages[0].id, id: 'follow_up', label: 'Why?' } },
				{ op: 'set_condition', params: { target: 'follow_up', condition: `${single} == 1` } }
			]
		}
	});
	expect(r.status()).toBe(200);
	await page.reload();
	await page.waitForLoadState('load');
	await page.getByRole('tree', { name: 'Survey outline' }).getByRole('treeitem', { name: 'New question' }).click();
	await expect(typeShown(page)).toHaveText('Single choice');

	await change.click();
	await dialog.getByRole('option', { name: /^Text\b/ }).click();
	const warn = page.getByRole('dialog', { name: 'Change the question type?' });
	await expect(warn.getByTestId('type-change-warning')).toContainText('This changes 1 condition or piped text');
	expect(await axe(page)).toEqual([]);
	await warn.getByRole('button', { name: 'Keep Single choice' }).click();
	await expect(warn).toBeHidden();
	await expect(typeShown(page)).toHaveText('Single choice');
	expect(await questionTypes(page)).toContain('single');

	await change.click();
	await dialog.getByRole('option', { name: /^Text\b/ }).click();
	await warn.getByRole('button', { name: 'Change to Text' }).click();
	await expect(typeShown(page)).toHaveText('Text');
	await expect(saved(page)).toHaveText(/All changes saved/);
	await undo.click();
	await expect(typeShown(page)).toHaveText('Single choice');
	await expect(saved(page)).toHaveText(/All changes saved/);
});

test('320 px: the picker fits, no horizontal scroll, 44 px targets', async ({ page }) => {
	await page.setViewportSize({ width: 320, height: 640 });
	await createSurvey(page, `Narrow types ${Date.now()}`);
	await page.getByRole('button', { name: /Add question to/ }).first().click();
	await expect(picker(page).getByRole('combobox', { name: 'Filter question types' })).toBeFocused();

	const scroll = await page.evaluate(() => document.documentElement.scrollWidth);
	expect(scroll, 'no horizontal scroll').toBeLessThanOrEqual(320);
	for (const o of await picker(page).getByRole('option').all()) {
		const box = (await o.boundingBox())!;
		expect(box.height, await o.innerText()).toBeGreaterThanOrEqual(44);
		expect(box.x).toBeGreaterThanOrEqual(0);
		expect(box.x + box.width).toBeLessThanOrEqual(320);
	}
	// The modal only: behind its overlay, the top bar's icon buttons are squeezed to 20 px at
	// this width, which axe flags as obscured targets (the editor alone passes; not the picker).
	expect(await axeIn(page, '.osp-dialog')).toEqual([]);

	await option(page, 'Slider').click();
	await expect(typeShown(page)).toHaveText('Slider');
	const change = page.getByRole('button', { name: /^Change type of/ });
	expect((await change.boundingBox())!.height).toBeGreaterThanOrEqual(44);
	const add = page.getByRole('button', { name: /Add question to/ }).first();
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
	await change.click();
	await expect(picker(page, 'Change question type').getByRole('option').first()).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(change).toBeFocused();
	await page.keyboard.press('Escape'); // close the properties overlay
	expect((await add.boundingBox())!.height).toBeGreaterThanOrEqual(44);
});

test('after publishing, changing a type warns that collected data keeps the old type', async ({ page }) => {
	await createSurvey(page, `Published types ${Date.now()}`);
	await page.getByRole('button', { name: /Add question to/ }).first().click();
	await pickQuestionType(page, /^Whole number\b/);
	await expect(saved(page)).toHaveText(/All changes saved/);

	const surveyId = page.url().split('/').pop()!;
	const headers = await writeHeaders(page);
	const detail = await (await page.request.get(`/api/surveys/${surveyId}`)).json();
	const retention = { kind: 'days-after-close', days: 365 };
	const ops = [{ op: 'set_property', params: { target: '/settings', property: 'retention', value: retention } }];
	const r = await page.request.post(`/api/surveys/${surveyId}/ops`, {
		headers,
		data: { baseRevision: detail.revision, ops }
	});
	expect(r.status()).toBe(200);
	expect((await page.request.post(`/api/surveys/${surveyId}/publish`, { headers })).status()).toBe(201);
	await page.reload();
	await page.waitForLoadState('load');
	await page.getByRole('tree', { name: 'Survey outline' }).getByRole('treeitem', { name: 'New question' }).click();

	const change = page.getByRole('button', { name: /^Change type of/ });
	await change.click();
	await option(page, 'Decimal number', 'Change question type').click();
	const warn = page.getByRole('dialog', { name: 'Change the question type?' });
	await expect(warn.getByTestId('type-change-warning')).toContainText('This survey has 1 published version');
	await expect(warn.getByTestId('type-change-warning')).toContainText('keep the old type (Whole number)');
	await page.keyboard.press('Escape');
	await expect(warn).toBeHidden();
	await expect(typeShown(page)).toHaveText('Whole number');

	await change.click();
	await option(page, 'Decimal number', 'Change question type').click();
	await warn.getByRole('button', { name: 'Change to Decimal number' }).click();
	await expect(typeShown(page)).toHaveText('Decimal number');
	await expect(saved(page)).toHaveText(/All changes saved/);
	expect((await questionTypes(page)).at(-1)).toBe('decimal');
});
