import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';
import { axe, signIn, writeHeaders } from './fixtures';

// Researcher hooks are authored in Survey settings, stored in the draft (`survey.hooks`,
// the set_hooks op), run in the Preview's sandbox, and published inside the plan (task R11,
// runtime-design §7a). A hook that records a value when a page is shown is visible in the
// preview's debugger and, through the hook that reads it on Next, in a published run.

const FIXTURE = '05-showif-null';
const survey = () => {
	const s = JSON.parse(readFileSync(new URL(`../../../fixtures/${FIXTURE}/survey.json`, import.meta.url), 'utf8'));
	s.settings = { ...(s.settings ?? {}), retention: { kind: 'indefinite' } };
	s.consent = { text: 'This is a test survey.' };
	return s;
};

// One line: the editor indents typed newlines. `seen` is set when the page is shown and
// read when Next is pressed, so the published run shows what the onPageShown hook set.
const SOURCE = [
	'var seen = 0;',
	"osp.on('onPageShown', function (ctx, data, act) { seen = ctx.trial; act.addParadata('shownTrial', ctx.trial); });",
	"osp.on('onPageNext', function (ctx, data, act) { var a = ctx.results.a; if (a && a.value === 99) act.rejectPage({ itemId: 'a', message: 'Hook saw trial ' + seen + ': not 99.' }); });"
].join(' ');

const banner = (page: Page) => page.getByRole('banner');
const saved = (page: Page) => banner(page).getByRole('status').first();
const section = (page: Page) => page.locator('#settings-hooks');
const problems = (page: Page) => section(page).getByTestId('hooks-problems');
const hookRow = (page: Page, event: string) => page.locator(`[data-testid="dbg-hook"][data-event="${event}"]`);

async function createAndOpenSettings(page: Page): Promise<string> {
	await signIn(page);
	const res = await page.request.post('/api/surveys', {
		headers: await writeHeaders(page),
		data: { title: `Hooks e2e ${Date.now()}`, survey: survey() }
	});
	expect(res.status()).toBe(201);
	const { id } = await res.json();
	await page.goto(`/surveys/${id}/settings`);
	await expect(page.getByRole('heading', { name: 'Survey settings' })).toBeVisible();
	return id;
}

async function typeSource(page: Page, text: string) {
	const editor = section(page).getByTestId('hooks-source').locator('.cm-content');
	await editor.click();
	await page.keyboard.press('ControlOrMeta+a');
	await page.keyboard.press('Delete');
	await page.keyboard.type(text);
}

test('hooks are authored in settings, checked, run in the preview and published with the survey', async ({ page }) => {
	const id = await createAndOpenSettings(page);

	// Off by default; switching on saves a starter manifest at once.
	const toggle = section(page).getByRole('checkbox', { name: 'This survey runs custom code (researcher hooks)' });
	await expect(toggle).not.toBeChecked();
	await toggle.check();
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect(section(page).locator('[data-testid="hooks-event"][data-event="onPageShown"]')).toHaveAttribute('data-on', 'true');
	await expect(problems(page)).toBeHidden();

	// The script and the events it handles; a declared event the script never registers is
	// flagged before anything is saved, and so is a registered event nobody declared.
	await typeSource(page, SOURCE);
	await expect(problems(page)).toContainText('registers onPageNext but it is not handled');
	await section(page).getByRole('checkbox', { name: 'Handle onPageNext' }).check();
	await expect(problems(page)).toBeHidden();
	await section(page).getByRole('checkbox', { name: 'Handle onBack' }).check();
	await expect(problems(page)).toContainText('onBack is handled but the script never registers it');
	await section(page).getByRole('checkbox', { name: 'Handle onBack' }).uncheck();

	// A read the survey does not have: the server refuses to build a plan and says where.
	await section(page).getByLabel('Reads for onPageNext').fill('a, nope');
	await section(page).getByLabel('Reads for onPageNext').blur();
	await section(page).getByTestId('hooks-save').click();
	await expect(section(page).getByTestId('hooks-status')).toHaveText('Hooks saved.');
	await expect(problems(page).locator('[data-code="hooks.unknown_ref"]')).toContainText("'nope' is not a question");
	await section(page).getByLabel('Reads for onPageNext').fill('a');
	await section(page).getByLabel('Reads for onPageNext').blur();
	await section(page).getByTestId('hooks-save').click();
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect(problems(page)).toBeHidden();
	expect(await axe(page)).toEqual([]);

	// The stored manifest is what was typed, with the handlers as declared.
	const draft = await (await page.request.get(`/api/surveys/${id}`)).json();
	expect(draft.survey.hooks.source).toBe(SOURCE);
	expect(draft.survey.hooks.handlers).toEqual({
		onPageShown: { reads: [], writes: [] },
		onPageNext: { reads: ['a'], writes: [] }
	});

	// The dry run: Preview runs the hooks in the participant sandbox; the debugger lists them.
	await section(page).getByTestId('hooks-preview').click();
	await expect(page.getByRole('heading', { name: 'Preview', level: 2 })).toBeVisible();
	const phone = page.frameLocator('[data-testid="preview-frame-phone"]');
	// Consent comes first (nothing runs before agreement); the first page then fires onPageShown.
	await phone.getByRole('button', { name: 'I agree' }).click({ timeout: 20_000 });
	await expect(hookRow(page, 'onPageShown')).toHaveAttribute('data-status', 'ok', { timeout: 15_000 });
	await expect(hookRow(page, 'onPageShown')).toContainText('addParadata shownTrial = 1');
	await phone.getByLabel('Pick any whole number (optional).').fill('99');
	await phone.getByRole('button', { name: 'Next' }).click();
	await expect(phone.getByTestId('error-summary')).toContainText('Hook saw trial 1: not 99.');
	await expect(hookRow(page, 'onPageNext')).toContainText('rejectPage a');

	// Publish; the participant link runs the same hooks from the published plan.
	await banner(page).getByRole('button', { name: 'Publish', exact: true }).click();
	const result = page.getByRole('dialog', { name: 'Publish' }).getByTestId('publish-result');
	await expect(result).toContainText('Published version 1');
	const link = await result.getByLabel('Participant link').inputValue();

	const participant = await page.context().newPage();
	await participant.goto(link);
	await participant.getByRole('button', { name: 'I agree' }).click({ timeout: 20_000 });
	await expect(participant.locator('iframe[title="hooks"]')).toHaveAttribute('sandbox', 'allow-scripts');
	await participant.getByLabel('Pick any whole number (optional).').fill('99');
	await participant.getByRole('button', { name: 'Next' }).click();
	await expect(participant.getByTestId('error-summary')).toContainText('Hook saw trial 1: not 99.');
	await participant.getByLabel('Pick any whole number (optional).').fill('3');
	await participant.getByRole('button', { name: 'Next' }).click();
	await expect(participant.getByText('This question is always shown.')).toBeVisible();
	await participant.close();
});

test('switching hooks off removes them; undo brings the code back', async ({ page }) => {
	const id = await createAndOpenSettings(page);
	const toggle = section(page).getByRole('checkbox', { name: 'This survey runs custom code (researcher hooks)' });
	await toggle.check();
	await expect(saved(page)).toHaveText(/All changes saved/);
	page.once('dialog', (d) => void d.accept());
	await toggle.uncheck();
	await expect(saved(page)).toHaveText(/All changes saved/);
	await expect(section(page).getByTestId('hooks-source')).toBeHidden();
	let draft = await (await page.request.get(`/api/surveys/${id}`)).json();
	expect(draft.survey.hooks).toBeUndefined();
	await page.getByRole('button', { name: 'Undo', exact: true }).click();
	await expect(toggle).toBeChecked();
	await expect(saved(page)).toHaveText(/All changes saved/);
	draft = await (await page.request.get(`/api/surveys/${id}`)).json();
	expect(draft.survey.hooks.format).toBe('osp-hooks/1');
});
