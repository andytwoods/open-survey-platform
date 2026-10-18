import { expect, test, type Page } from '@playwright/test';
import { axe, signIn, writeHeaders } from './fixtures';

// The question bank in the builder (task QB5), end to end against a real osp-api on
// SQLite: the Bank section under the outline (search, preview, Insert at the selection,
// drag onto the canvas, the provenance line with Details / Detach, undo), "Save to bank…"
// from the context menu with the preview of what travels and what is cut, the Bank page
// (edit, share with relicensing, export, delete, the bundled library, the licensed-
// instrument wizard), axe, 320 px with tap-to-place.

const banner = (page: Page) => page.getByRole('banner');
const saved = (page: Page) => banner(page).getByRole('status').first();
const tree = (page: Page) => page.getByRole('tree', { name: 'Survey outline' });
const item = (page: Page, name: string | RegExp) => tree(page).getByRole('treeitem', { name, exact: typeof name === 'string' });
const bankToggle = (page: Page) => page.getByRole('button', { name: 'Bank', exact: true });
const bankPane = (page: Page) => page.getByTestId('bank-pane');
const result = (page: Page, id: string) => bankPane(page).locator(`[data-bank-result="${id}"]`);

type Block = { id: string; title?: string; source?: { bank: string; version: number; library: string }; pages: { id: string; items: { id: string; source?: unknown }[] }[] };
type Survey = { blocks: Block[]; flow: { type: string; block?: string }[]; variables?: { id: string }[] };

async function stored(page: Page, id: string): Promise<Survey> {
	return (await (await page.request.get(`/api/surveys/${id}`)).json()).survey;
}

/** A survey with b1: p1 (q_a Alpha, q_b Bravo), p_two (q_c Charlie); opened in the editor. */
async function seeded(page: Page, title: string): Promise<string> {
	await signIn(page);
	const res = await page.request.post('/api/surveys', { headers: await writeHeaders(page), data: { title } });
	expect(res.status(), await res.text()).toBe(201);
	const id = (await res.json()).id as string;
	const detail = await (await page.request.get(`/api/surveys/${id}`)).json();
	const block = detail.survey.blocks[0];
	const p1 = block.pages[0].id;
	const r = await page.request.post(`/api/surveys/${id}/ops`, {
		headers: await writeHeaders(page),
		data: {
			baseRevision: detail.revision,
			ops: [
				{ op: 'add_question', params: { page: p1, id: 'q_a', label: 'Alpha' } },
				{ op: 'add_question', params: { page: p1, id: 'q_b', label: 'Bravo' } },
				{ op: 'add_page', params: { block: block.id, id: 'p_two' } },
				{ op: 'add_question', params: { page: 'p_two', id: 'q_c', label: 'Charlie' } }
			]
		}
	});
	expect(r.status(), await r.text()).toBe(200);
	await page.goto(`/surveys/${id}`);
	await expect(page.getByRole('button', { name: /Add question to/ }).first()).toBeVisible();
	return id;
}

async function openBank(page: Page) {
	const toggle = bankToggle(page);
	if ((await toggle.getAttribute('aria-expanded')) !== 'true') await toggle.click();
	await expect(toggle).toHaveAttribute('aria-expanded', 'true');
	await expect(bankPane(page).locator('[data-bank-result]').first()).toBeVisible();
}

/** Save `targetId` of survey `id` to the lab bank through the API; the item's id. */
async function savedItem(page: Page, id: string, targetId: string, title: string, extra: Record<string, unknown> = {}) {
	const r = await page.request.post('/api/bank', {
		headers: await writeHeaders(page),
		data: { surveyId: id, targetId, title, ...extra }
	});
	expect(r.status(), await r.text()).toBe(201);
	return (await r.json()).item.summary as { id: string; title: string; version: number };
}

test('the Bank section: search, preview, Insert at the selection, provenance, Detach, undo, axe', async ({ page }) => {
	const id = await seeded(page, `Bank insert ${Date.now()}`);
	await openBank(page);
	// Folding the bank opens nothing else; the question types fold while the bank is open.
	await expect(page.getByRole('button', { name: 'Question types' })).toHaveAttribute('aria-expanded', 'false');
	expect(await axe(page)).toEqual([]);

	await bankPane(page).getByRole('searchbox', { name: 'Search the bank' }).fill('anxiety ultra');
	await expect(result(page, 'gad2')).toBeVisible();
	await expect(bankPane(page).locator('[data-bank-result]')).toHaveCount(1);
	// The preview: items, scoring, the licence statement.
	await result(page, 'gad2').getByRole('button', { name: /^Generalized Anxiety Disorder-2/ }).click();
	const preview = result(page, 'gad2').getByTestId('bank-preview');
	await expect(preview).toBeVisible();
	await expect(preview.getByRole('list', { name: 'Items' })).toContainText('Feeling nervous');
	await expect(preview).toContainText('gad2_total');
	await expect(preview).toContainText('Public domain');
	expect(await axe(page)).toEqual([]);

	// Insert with Alpha selected: a block goes after Alpha's block (b1), in the flow.
	await item(page, 'Alpha').click();
	await result(page, 'gad2').getByRole('button', { name: /^Insert / }).click();
	await expect(item(page, 'GAD-2')).toBeVisible();
	await expect(saved(page)).toHaveText(/All changes saved/);
	let survey = await stored(page, id);
	expect(survey.blocks.map((b) => b.id)).toEqual(['b1', 'gad2_block']);
	expect(survey.blocks[1].source).toEqual(expect.objectContaining({ bank: 'gad2', version: 1, library: 'bundled' }));
	expect(survey.flow.filter((n) => n.type === 'block').map((n) => n.block)).toEqual(['b1', 'gad2_block']);
	expect(survey.variables?.map((v) => v.id)).toContain('gad2_total');

	// The provenance line on the block heading, its Details, and Detach (clear_source).
	const line = page.locator('[data-provenance="gad2_block"]');
	await expect(line).toContainText(/GAD-2.*bundled.*v1/);
	await line.getByRole('button', { name: /Details/ }).click();
	const details = page.getByRole('dialog', { name: 'From the question bank' });
	await expect(details.getByTestId('provenance-details')).toContainText('version 1');
	await expect(details.getByRole('list', { name: 'Items' })).toContainText('Not being able to stop');
	expect(await axe(page)).toEqual([]);
	await details.getByRole('button', { name: 'Close', exact: true }).click();
	await expect(details).toBeHidden();
	await line.getByRole('button', { name: /Detach/ }).click();
	await expect(line).toHaveCount(0);
	await expect(saved(page)).toHaveText(/All changes saved/);
	survey = await stored(page, id);
	expect(survey.blocks[1].source).toBeUndefined();

	// Undo twice: the source comes back, then the whole insert goes (one undo step).
	await banner(page).getByRole('button', { name: 'Undo', exact: true }).click();
	await expect(page.locator('[data-provenance="gad2_block"]')).toBeVisible();
	await banner(page).getByRole('button', { name: 'Undo', exact: true }).click();
	await expect(item(page, 'GAD-2')).toHaveCount(0);
	await expect(saved(page)).toHaveText(/All changes saved/);
	survey = await stored(page, id);
	expect(survey.blocks.map((b) => b.id)).toEqual(['b1']);
	expect(survey.variables?.map((v) => v.id) ?? []).not.toContain('gad2_total');
});

test('dragging a bank item onto the canvas inserts it as a block there', async ({ page }) => {
	const id = await seeded(page, `Bank drag ${Date.now()}`);
	await openBank(page);
	await bankPane(page).getByRole('searchbox', { name: 'Search the bank' }).fill('phq-2');
	// The debounced search re-lays the list out: measure only once it holds the one result.
	await expect(bankPane(page).locator('[data-bank-result]')).toHaveCount(1);
	await expect(result(page, 'phq2')).toBeVisible();
	const from = (await result(page, 'phq2').boundingBox())!;
	// Onto the very first gap of the first block (above the starter question): a block
	// dropped there goes before b1.
	const firstCard = page.locator('[data-canvas-question]').first();
	const top = (await firstCard.boundingBox())!;
	await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
	await page.mouse.down();
	await page.mouse.move(from.x + from.width / 2 + 12, from.y + from.height / 2 - 8, { steps: 3 });
	await page.mouse.move(top.x + top.width / 2, top.y + 4, { steps: 10 });
	await expect(firstCard).toHaveAttribute('data-drop', 'before');
	await page.mouse.up();
	await expect(item(page, 'PHQ-2')).toBeVisible();
	await expect(saved(page)).toHaveText(/All changes saved/);
	const survey = await stored(page, id);
	expect(survey.blocks.map((b) => b.id)).toEqual(['phq2_block', 'b1']);
	expect(survey.blocks[0].source?.bank).toBe('phq2');

	// Escape mid-drag inserts nothing.
	const from2 = (await result(page, 'phq2').boundingBox())!;
	const alpha = (await page.locator('[data-canvas-question="q_a"]').boundingBox())!;
	await page.mouse.move(from2.x + from2.width / 2, from2.y + from2.height / 2);
	await page.mouse.down();
	await page.mouse.move(from2.x + from2.width / 2 + 12, from2.y + from2.height / 2 - 8, { steps: 3 });
	await page.mouse.move(alpha.x + alpha.width / 2, alpha.y + alpha.height - 4, { steps: 10 });
	await page.keyboard.press('Escape');
	await page.mouse.up();
	await expect(page.locator('[data-drop]')).toHaveCount(0);
	expect((await stored(page, id)).blocks.map((b) => b.id)).toEqual(['phq2_block', 'b1']);
});

test('Save to bank… from the context menu shows what travels and what is cut, then the item is in the bank', async ({ page }) => {
	const id = await seeded(page, `Bank save ${Date.now()}`);
	// Bravo pipes Alpha: saving page one keeps it; saving Bravo alone cuts the pipe.
	const detail = await (await page.request.get(`/api/surveys/${id}`)).json();
	const r = await page.request.post(`/api/surveys/${id}/ops`, {
		headers: await writeHeaders(page),
		data: {
			baseRevision: detail.revision,
			ops: [{ op: 'set_property', params: { target: 'q_b', property: 'label', value: 'Bravo after ${q_a}' } }]
		}
	});
	expect(r.status(), await r.text()).toBe(200);
	await page.reload();
	await expect(item(page, 'Alpha')).toBeVisible();

	const row = item(page, /^Bravo/);
	await row.click();
	await row.focus();
	await page.keyboard.press('Shift+F10');
	const menu = page.getByRole('menu');
	await expect(menu).toBeVisible();
	await menu.getByRole('menuitem', { name: 'Save to bank…' }).click();
	const dialog = page.getByRole('dialog', { name: 'Save question to the bank' });
	await expect(dialog).toBeVisible();
	const preview = dialog.getByTestId('save-to-bank-preview');
	await expect(preview).toContainText('1 item');
	await expect(preview).toContainText('Will be cut');
	await expect(preview).toContainText(/q_a/);
	expect(await axe(page)).toEqual([]);
	const title = `Bravo item ${Date.now()}`;
	await dialog.getByRole('textbox', { name: 'Title' }).fill(title);
	await dialog.getByRole('textbox', { name: 'Tags' }).fill('e2e, bravo');
	await expect(dialog.getByRole('combobox', { name: 'Licence' })).toHaveValue('unknown');
	await dialog.getByRole('button', { name: 'Save to bank' }).click();
	await expect(dialog).toBeHidden();

	// Found again in the Bank section, as the lab's own item with the default licence.
	await openBank(page);
	await bankPane(page).getByRole('searchbox', { name: 'Search the bank' }).fill(title);
	await expect(bankPane(page).locator('[data-bank-result]')).toHaveCount(1);
	const card = bankPane(page).locator('[data-bank-item][data-source="lab"]');
	await expect(card).toHaveCount(1);
	await expect(card).toContainText(title);
	await expect(card).toContainText('Licence not stated');
	const list = await (await page.request.get(`/api/bank?q=${encodeURIComponent(title)}`)).json();
	expect(list.items).toHaveLength(1);
	expect(list.items[0].tags).toEqual(['e2e', 'bravo']);
	expect(list.items[0].kind).toBe('question');

	// A page that came from the bank offers "new version of…": insert the item, then save that page.
	await card.getByRole('button', { name: /^Insert / }).click();
	await expect(saved(page)).toHaveText(/All changes saved/);
	const line = page.locator(`[data-provenance][data-bank="${list.items[0].id}"]`);
	await expect(line).toBeVisible();
	const inserted = await line.getAttribute('data-provenance');
	await item(page, /^Bravo after/).last().click();
	await page.keyboard.press('Shift+F10');
	await page.getByRole('menu').getByRole('menuitem', { name: 'Save to bank…' }).click();
	const again = page.getByRole('dialog', { name: 'Save question to the bank' });
	await expect(again.getByRole('radio', { name: /Version 2 of/ })).toBeVisible();
	await again.getByRole('radio', { name: /Version 2 of/ }).check();
	await again.getByRole('button', { name: 'Save new version' }).click();
	await expect(again).toBeHidden();
	await expect.poll(async () => (await (await page.request.get(`/api/bank/${list.items[0].id}`)).json()).version).toBe(2);
	// The inserted copy now shows "Replace with v2".
	await expect(page.locator(`[data-provenance="${inserted}"]`).getByRole('button', { name: /Replace with version 2/ })).toBeVisible();
});

test('the Bank page: edit, share with relicensing, export, delete, bundled library, licensed wizard, axe', async ({ page }) => {
	const id = await seeded(page, `Bank page ${Date.now()}`);
	const title = `Page item ${Date.now()}`;
	const mine = await savedItem(page, id, 'p_two', title, { abbreviation: 'PI', tags: ['e2e'] });
	await page.goto('/bank');
	await expect(page.getByRole('heading', { level: 2, name: 'Question bank' })).toBeVisible();
	const card = page.locator(`[data-bank-item="${mine.id}"]`);
	await expect(card).toBeVisible();
	await expect(card).toContainText('Licence not stated');
	expect(await axe(page)).toEqual([]);

	// Edit metadata.
	await card.getByRole('button', { name: 'Edit…' }).click();
	const form = page.getByRole('form', { name: `Edit ${title}` });
	await form.getByRole('textbox', { name: 'Abbreviation' }).fill('PI2');
	await form.getByRole('button', { name: 'Save' }).click();
	await expect(page.getByTestId('bank-message')).toContainText('updated');
	await expect(card).toContainText('PI2');

	// Share: refused for an unstated licence, then relicensed as the lab's own words.
	await card.getByRole('button', { name: 'Share with host' }).click();
	const relicense = page.getByRole('group', { name: `Share ${title}` });
	await expect(relicense).toContainText('Say what licence');
	await relicense.getByRole('button', { name: /CC BY 4.0/ }).click();
	await expect(page.getByTestId('bank-message')).toContainText('shared with every lab');
	await expect(card).toContainText('CC BY 4.0');
	await expect(card.getByRole('button', { name: 'Stop sharing' })).toBeVisible();
	const got = await (await page.request.get(`/api/bank/${mine.id}`)).json();
	expect(got.summary.visibility).toBe('host');
	expect(got.summary.licenceClass).toBe('cc-by-4.0');

	// Export downloads the portable file.
	const [download] = await Promise.all([page.waitForEvent('download'), card.getByRole('button', { name: `Export ${title}` }).click()]);
	expect(download.suggestedFilename()).toBe('PI2-v1.osp-bank.json');

	// Versions: one so far.
	await card.getByRole('button', { name: 'Versions' }).click();
	await expect(page.getByRole('group', { name: `Versions of ${title}` })).toContainText('v1');
	await page.getByRole('group', { name: `Versions of ${title}` }).getByRole('button', { name: 'Close' }).click();

	// Delete asks first.
	await card.getByRole('button', { name: 'Delete…' }).click();
	await page.getByRole('group', { name: `Delete ${title}?` }).getByRole('button', { name: 'Keep' }).click();
	await expect(card).toBeVisible();
	await card.getByRole('button', { name: 'Delete…' }).click();
	await page.getByRole('group', { name: `Delete ${title}?` }).getByRole('button', { name: 'Delete' }).click();
	await expect(card).toHaveCount(0);
	// Soft delete: it leaves every list (surveys that inserted it can still read it).
	expect((await (await page.request.get(`/api/bank/${mine.id}`)).json()).summary.deletedAt).toBeTruthy();
	expect((await (await page.request.get(`/api/bank?source=lab&q=${encodeURIComponent(title)}`)).json()).items).toEqual([]);

	// The bundled library shows the licence evidence.
	await page.getByRole('tab', { name: 'Bundled library' }).click();
	const phq9 = page.locator('[data-bank-item="phq9"]');
	await phq9.getByRole('button', { name: /^Patient Health Questionnaire-9/ }).click();
	await expect(phq9.getByTestId('bank-preview')).toContainText('no permission is required');
	await expect(phq9.getByRole('link', { name: /Terms page/ })).toHaveAttribute('href', /phqscreeners/);
	expect(await axe(page)).toEqual([]);

	// The licensed-instrument wizard: PSS-10 from the stub, ten pasted lines, attestation.
	await page.getByRole('tab', { name: 'Licensed instruments' }).click();
	await expect(page.locator('[data-stub="bdi-ii"]')).toContainText('Licence required');
	await page.locator('[data-stub="pss-10"]').getByRole('button', { name: 'Add our copy…' }).click();
	const wizard = page.getByRole('dialog', { name: 'Add a licensed instrument privately' });
	await expect(wizard.getByRole('radio', { name: /Perceived Stress Scale/ })).toBeChecked();
	await wizard.getByRole('button', { name: 'Continue' }).click();
	await expect(wizard.getByTestId('licensed-wizard')).toHaveAttribute('data-step', '2');
	const items = wizard.getByRole('textbox', { name: /Items, one per line/ });
	await items.fill(Array.from({ length: 9 }, (_, i) => `Item ${i + 1}`).join('\n'));
	await expect(wizard.getByRole('alert')).toContainText('has 10 items; you have 9 lines');
	await expect(wizard.getByRole('button', { name: 'Continue' })).toBeDisabled();
	await items.fill(Array.from({ length: 10 }, (_, i) => `Item ${i + 1}`).join('\n'));
	await wizard.getByRole('textbox', { name: /Response options/ }).fill('Never\nAlmost never\nSometimes\nFairly often\nVery often');
	expect(await axe(page)).toEqual([]);
	await wizard.getByRole('button', { name: 'Continue' }).click();
	await expect(wizard.getByRole('button', { name: 'Add to my bank' })).toBeDisabled();
	await wizard.getByRole('checkbox', { name: /Our lab holds a licence/ }).check();
	await wizard.getByRole('button', { name: 'Add to my bank' }).click();
	await expect(wizard).toBeHidden();
	await expect(page.getByTestId('bank-message')).toContainText('licensed to this lab');
	const lab = await (await page.request.get('/api/bank?source=lab&q=perceived+stress')).json();
	const pss = lab.items.find((i: { abbreviation: string }) => i.abbreviation === 'PSS-10');
	expect(pss).toBeTruthy();
	expect(pss.licenceClass).toBe('licensed-to-lab');
	expect(pss.itemCount).toBe(10);
	const doc = await (await page.request.get(`/api/bank/${pss.id}`)).json();
	expect(doc.document.fragment.variables.map((v: { id: string }) => v.id)).toEqual(['pss_10_total']);
	await expect(page.locator(`[data-bank-item="${pss.id}"]`)).toContainText('Licensed to this lab');
	// Clean up: a licensed item can be deleted like any other.
	const del = await page.request.delete(`/api/bank/${pss.id}`, { headers: await writeHeaders(page) });
	expect(del.status()).toBe(204);
});

test('320 px: the Bank section fits, Insert picks the item up and Place here puts it down; the Bank page fits', async ({ page }) => {
	await page.setViewportSize({ width: 320, height: 720 });
	const id = await seeded(page, `Bank narrow ${Date.now()}`);
	await banner(page).getByRole('button', { name: 'Outline pane' }).click();
	await openBank(page);
	const pane = page.locator('#pane-outline');
	expect(await pane.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
	await bankPane(page).getByRole('searchbox', { name: 'Search the bank' }).fill('gad-2');
	await expect(bankPane(page).locator('[data-bank-result]')).toHaveCount(1);
	await expect(result(page, 'gad2')).toBeVisible();
	expect(await axe(page)).toEqual([]);
	await result(page, 'gad2').getByRole('button', { name: /^Insert / }).click();
	await expect(page.getByRole('group', { name: 'Placing a question' })).toContainText('GAD-2 block');
	await page.getByRole('button', { name: /^Place here at the end of p_two/ }).click();
	await expect(saved(page)).toHaveText(/All changes saved/);
	const survey = await stored(page, id);
	expect(survey.blocks.map((b) => b.id)).toEqual(['b1', 'gad2_block']);
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);

	await page.goto('/bank');
	await expect(page.getByRole('heading', { level: 2, name: 'Question bank' })).toBeVisible();
	await expect(page.getByRole('tab', { name: 'Bundled library' })).toBeVisible();
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
	expect(await axe(page)).toEqual([]);
});
