import { readFileSync } from 'node:fs';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { axe, signIn, writeHeaders } from './fixtures';

// The flow editor (task B8) end to end against a real osp-api (e2e/api_server.py).
// The survey starts as the review.md §2.3 worked example (fixtures/20-worked-example)
// with its blocks, variables and an age quota, but an empty flow; the tests build the
// flow in the editor. §2.3's flow has every node type except a randomiser, which the
// keyboard test adds.

function seedSurvey(flow: unknown[] = []) {
	const s = JSON.parse(readFileSync(new URL('../../../fixtures/20-worked-example/survey.json', import.meta.url), 'utf8'));
	s.flow = flow;
	s.quotas = [
		{
			id: 'q_old',
			when: { kind: 'compare', op: '>=', left: { kind: 'ref', id: 'age' }, right: { kind: 'int', value: 40 } },
			limit: 150,
			onFull: { block: 'screenout', outcome: 'screened_out' }
		}
	];
	return s;
}

/** Create a survey through the API and open its flow view. */
async function openFlow(page: Page, title: string, flow: unknown[] = []) {
	const res = await page.request.post('/api/surveys', {
		headers: await writeHeaders(page),
		data: { title, survey: seedSurvey(flow) }
	});
	expect(res.status()).toBe(201);
	const { id } = await res.json();
	await page.goto(`/surveys/${id}/flow`);
	await expect(page.getByRole('heading', { name: 'Survey flow', level: 2 })).toBeVisible();
	return id as string;
}

async function serverFlow(page: Page, id: string) {
	const detail = await (await page.request.get(`/api/surveys/${id}`)).json();
	return detail.survey.flow as unknown[];
}

/** The flow without ids, for comparing shapes. */
function shape(nodes: unknown): unknown {
	if (Array.isArray(nodes)) return nodes.map(shape);
	if (nodes && typeof nodes === 'object') {
		const out: Record<string, unknown> = {};
		const isNode = 'type' in nodes;
		for (const [k, v] of Object.entries(nodes)) if (!(isNode && k === 'id')) out[k] = shape(v);
		return out;
	}
	return nodes;
}

const saveState = (page: Page) => page.getByRole('banner').getByRole('status').first();
const card = (page: Page, heading: string): Locator =>
	page.getByRole('heading', { name: heading, exact: true }).locator('xpath=ancestor::article[1]');
const handle = (page: Page, heading: string) => page.getByRole('button', { name: `Move ${heading}`, exact: true });
const plus = (page: Page, list: string, position: number) =>
	page.getByRole('button', { name: `Add node to ${list} at position ${position}`, exact: true });

async function addViaDialog(page: Page, open: Locator, type: string, fill: (d: Locator) => Promise<void> = async () => {}) {
	await open.click();
	const dialog = page.getByRole('dialog', { name: 'Add flow node' });
	await expect(dialog).toBeVisible();
	await dialog.getByLabel('Node type').selectOption({ label: type });
	await fill(dialog);
	await page.getByRole('button', { name: 'Add', exact: true }).click();
	await expect(dialog).toBeHidden();
	await expect(saveState(page)).toHaveText(/All changes saved/);
}

const EXPECTED_23 = [
	{ type: 'block', block: 'consent_blk' },
	{
		type: 'branch',
		if: { kind: 'compare', op: '==', left: { kind: 'ref', id: 'consent' }, right: { kind: 'int', value: 0 } },
		then: [{ type: 'end', outcome: 'declined' }]
	},
	{ type: 'block', block: 'demo' },
	{ type: 'quotaCheck', quota: 'q_old' },
	{ type: 'assign', variables: ['framing', 'incentive'] },
	{
		type: 'branch',
		if: { kind: 'compare', op: '==', left: { kind: 'ref', id: 'framing' }, right: { kind: 'text', value: 'gain' } },
		then: [{ type: 'block', block: 'stim_gain' }],
		else: [{ type: 'block', block: 'stim_loss' }]
	},
	{ type: 'block', block: 'attitudes' },
	{ type: 'end' }
];

test('build the §2.3 example flow with the mouse', async ({ page }) => {
	await signIn(page);
	const id = await openFlow(page, `Flow mouse ${Date.now()}`);
	await expect(page.getByText('The flow is empty.')).toBeVisible();
	expect(await axe(page)).toEqual([]);

	const block = (name: string) => async (d: Locator) => {
		await d.getByLabel('Block', { exact: true }).selectOption(name);
	};
	await addViaDialog(page, page.getByRole('button', { name: 'Add node', exact: true }), 'Block', block('consent_blk'));
	await addViaDialog(page, plus(page, 'Survey flow', 2), 'Branch', (d) => d.getByLabel('Condition').fill('consent == 0'));
	await expect(card(page, 'Branch: if consent == 0')).toBeVisible();
	await expect(card(page, 'Branch: if consent == 0').getByRole('button', { name: /^Empty/ })).toBeVisible();
	await addViaDialog(page, plus(page, 'Then of branch_1', 1), 'End', (d) => d.getByLabel('Outcome').fill('declined'));
	await expect(card(page, 'Branch: if consent == 0').getByRole('button', { name: /^Empty/ })).toHaveCount(0);

	await addViaDialog(page, plus(page, 'Survey flow', 3), 'Block', block('demo'));
	await addViaDialog(page, plus(page, 'Survey flow', 4), 'Quota check');
	await expect(card(page, 'Quota check: q_old')).toContainText('Limit 150');
	await addViaDialog(page, plus(page, 'Survey flow', 5), 'Assign', async (d) => {
		await expect(d.getByRole('checkbox', { name: /framing/ })).toBeChecked();
		await expect(d.getByRole('checkbox', { name: /incentive/ })).toBeChecked();
	});
	await addViaDialog(page, plus(page, 'Survey flow', 6), 'Branch', (d) => d.getByLabel('Condition').fill('framing == "gain"'));
	await addViaDialog(page, plus(page, 'Then of branch_2', 1), 'Block', block('stim_gain'));
	// Added at the top level, then dragged into the branch's "Otherwise" arm.
	await addViaDialog(page, plus(page, 'Survey flow', 7), 'Block', block('stim_loss'));
	await addViaDialog(page, plus(page, 'Survey flow', 8), 'Block', block('attitudes'));
	await addViaDialog(page, plus(page, 'Survey flow', 9), 'End');

	await handle(page, 'Block: stim_loss').dragTo(page.locator('[data-gap="branch_2:else:0"]'));
	await expect(saveState(page)).toHaveText(/All changes saved/);
	await expect(card(page, 'Branch: if framing == "gain"').getByRole('heading', { name: 'Block: stim_loss' })).toBeVisible();

	// Reorder by drag within a level, and back.
	await handle(page, 'Block: attitudes').dragTo(page.locator('[data-gap="flow::0"]'));
	await expect(page.locator('[data-node-id]').first()).toHaveAttribute('data-type', 'block');
	await expect(page.getByRole('heading', { level: 3 }).first()).toHaveText('Block: attitudes');
	await handle(page, 'Block: attitudes').dragTo(page.locator('[data-gap="flow::7"]'));
	await expect(saveState(page)).toHaveText(/All changes saved/);

	expect(shape(await serverFlow(page, id))).toEqual(EXPECTED_23);

	// Collapse a branch; its arms are hidden.
	await card(page, 'Branch: if framing == "gain"').getByRole('button', { name: /^Collapse/ }).click();
	await expect(page.getByRole('heading', { name: 'Block: stim_gain' })).toHaveCount(0);
	await page.getByRole('button', { name: /^Expand Branch: if framing/ }).click();
	await expect(page.getByRole('heading', { name: 'Block: stim_gain' })).toBeVisible();

	// Edit the branch condition through the condition builder (B7).
	await card(page, 'Branch: if consent == 0').getByRole('button', { name: 'Edit condition…', exact: true }).first().click();
	await expect(page.getByRole('dialog', { name: 'Edit branch condition' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Branch if…' })).toBeVisible();
	expect(await axe(page)).toEqual([]);
	await page.keyboard.press('Escape');
	await expect(page.getByRole('dialog', { name: 'Edit branch condition' })).toBeHidden();

	// Change a condition in the builder's text view; Apply sends set_condition on the branch.
	await card(page, 'Branch: if consent == 0').getByRole('button', { name: 'Edit condition…', exact: true }).first().click();
	const condDialog = page.getByRole('dialog', { name: 'Edit branch condition' });
	await condDialog.getByTestId('view-text').click();
	const editor = condDialog.locator('.cm-content');
	await expect(editor).toHaveText('consent == 0');
	await editor.click();
	await page.keyboard.press('ControlOrMeta+a');
	await page.keyboard.type('consent != 1');
	await condDialog.getByRole('button', { name: 'Apply', exact: true }).click();
	await expect(condDialog).toBeHidden();
	await expect(card(page, 'Branch: if consent != 1')).toBeVisible();
	await page.getByRole('banner').getByRole('button', { name: 'Undo', exact: true }).click();
	await expect(card(page, 'Branch: if consent == 0')).toBeVisible();

	expect(await axe(page)).toEqual([]);
	if (process.env.FLOW_SCREENSHOT) await page.screenshot({ path: process.env.FLOW_SCREENSHOT, fullPage: true });
});

test('build part of the flow with the keyboard only; move across levels; undo; reload', async ({ page }) => {
	await signIn(page);
	const id = await openFlow(page, `Flow keys ${Date.now()}`);

	const addFromPalette = async (type: string, fill: () => Promise<void>) => {
		await page.keyboard.press('ControlOrMeta+k');
		const palette = page.getByRole('dialog', { name: 'Command palette' });
		await expect(palette).toBeVisible();
		await page.keyboard.type('add flow node');
		await expect(palette.getByRole('option', { name: /Add flow node/ })).toBeVisible();
		await page.keyboard.press('Enter');
		const dialog = page.getByRole('dialog', { name: 'Add flow node' });
		await expect(dialog).toBeVisible();
		await expect(dialog.getByLabel('Node type')).toBeFocused();
		await page.keyboard.type(type);
		await expect(dialog.getByLabel('Node type')).toHaveValue(type === 'Branch' ? 'branch' : type === 'End' ? 'end' : type === 'Randomiser' ? 'randomiser' : 'block');
		await fill();
		await expect(dialog).toBeHidden();
		await expect(saveState(page)).toHaveText(/All changes saved/);
	};
	const submitWithAdd = async () => {
		// Tab to the dialog's Add button.
		for (let i = 0; i < 6; i++) {
			if (await page.getByRole('button', { name: 'Add', exact: true }).evaluate((el) => el === document.activeElement)) break;
			await page.keyboard.press('Tab');
		}
		await page.keyboard.press('Enter');
	};

	await addFromPalette('Block', submitWithAdd);
	await expect(handle(page, 'Block: consent_blk')).toBeFocused();
	await addFromPalette('Branch', async () => {
		await page.keyboard.press('Tab');
		await page.keyboard.type('consent == 0');
		await page.keyboard.press('Enter');
	});
	await expect(handle(page, 'Branch: if consent == 0')).toBeFocused();
	await addFromPalette('End', async () => {
		await page.keyboard.press('Tab');
		await page.keyboard.press('ControlOrMeta+a');
		await page.keyboard.type('declined');
		await page.keyboard.press('Enter');
	});
	// Move the End into the branch: up into "Otherwise", then up into "Then".
	await expect(handle(page, 'End: declined')).toBeFocused();
	await page.keyboard.press('Alt+ArrowUp');
	await expect(card(page, 'Branch: if consent == 0').getByRole('heading', { name: 'End: declined' })).toBeVisible();
	await expect(handle(page, 'End: declined')).toBeFocused();
	await page.keyboard.press('Alt+ArrowUp');
	await expect(saveState(page)).toHaveText(/All changes saved/);
	await expect(page.locator('[data-gap="branch_1:then:0"] + article')).toHaveAttribute('data-node-id', 'end_1');

	await addFromPalette('Randomiser', submitWithAdd);
	expect(shape(await serverFlow(page, id))).toEqual([
		{ type: 'block', block: 'consent_blk' },
		{
			type: 'branch',
			if: { kind: 'compare', op: '==', left: { kind: 'ref', id: 'consent' }, right: { kind: 'int', value: 0 } },
			then: [{ type: 'end', outcome: 'declined' }],
			else: []
		},
		{ type: 'randomiser', children: [{ type: 'block', block: 'demo' }] }
	]);

	// Undo (Mod+Z from the focused card handle) removes the randomiser; reload keeps it gone.
	await page.keyboard.press('ControlOrMeta+z');
	await expect(page.getByRole('heading', { name: /^Randomiser/ })).toHaveCount(0);
	await expect(saveState(page)).toHaveText(/All changes saved/);
	await page.reload();
	await expect(card(page, 'Branch: if consent == 0').getByRole('heading', { name: 'End: declined' })).toBeVisible();
	await expect(page.getByRole('heading', { name: /^Randomiser/ })).toHaveCount(0);
	expect(await axe(page)).toEqual([]);
});

test('an unreachable node is flagged, with a tooltip saying why', async ({ page }) => {
	await signIn(page);
	await openFlow(page, `Flow unreachable ${Date.now()}`, [
		{ type: 'block', id: 'n_consent', block: 'consent_blk' },
		{ type: 'end', id: 'end_early', outcome: 'complete' },
		{ type: 'block', id: 'n_demo', block: 'demo' }
	]);
	const demo = card(page, 'Block: demo');
	const flag = demo.getByRole('button', { name: /^Unreachable/ });
	await expect(flag).toBeVisible();
	await expect(demo).toHaveAttribute('data-flag', 'unreachable');
	await expect(card(page, 'Block: consent_blk').getByRole('button', { name: /^Unreachable/ })).toHaveCount(0);
	expect(await axe(page)).toEqual([]);
	await flag.hover();
	await expect(page.locator('.osp-tooltip')).toContainText('never reach');

	// Moving the End to the bottom (keyboard) clears the flag.
	await handle(page, 'End: complete').focus();
	await page.keyboard.press('Alt+ArrowDown');
	await expect(saveState(page)).toHaveText(/All changes saved/);
	await expect(demo.getByRole('button', { name: /^Unreachable/ })).toHaveCount(0);

	// Delete a node; undo brings it back.
	await card(page, 'Block: demo').getByRole('button', { name: 'Delete Block: demo' }).click();
	await expect(page.getByRole('heading', { name: 'Block: demo' })).toHaveCount(0);
	await expect(page.getByRole('status').filter({ hasText: 'Not in the flow' })).toContainText('demo');
	await page.getByRole('banner').getByRole('button', { name: 'Undo', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'Block: demo' })).toBeVisible();
});

test('the Flow tab switches views', async ({ page }) => {
	await signIn(page);
	const id = await openFlow(page, `Flow tab ${Date.now()}`);
	const views = page.getByRole('navigation', { name: 'Builder views' });
	await expect(views.getByRole('button', { name: 'Flow' })).toHaveAttribute('aria-current', 'page');
	await views.getByRole('button', { name: 'Questions' }).click();
	await expect(page).toHaveURL(new RegExp(`/surveys/${id}$`));
	await expect(page.getByRole('tree', { name: 'Survey outline' })).toBeVisible();
	await views.getByRole('button', { name: 'Flow' }).click();
	await expect(page).toHaveURL(new RegExp(`/surveys/${id}/flow$`));
});
