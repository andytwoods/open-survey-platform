import { expect, test, type Locator, type Page } from '@playwright/test';
import { axe, caretToEnd, fillRich, focused, openRich, pickQuestionType, signIn } from './fixtures';

// The rich-text editor (planning/rich-text.md §9, task RT3) on the property panel gallery
// (/dev/properties: every op is logged as JSON, the fake server echoes it back after 150 ms)
// and in the real editor: formatting, links, lists, headings per level, pipe chips and the
// picker, paste cleaning, the keyboard-only path, Escape, counts, axe in both themes and
// snapshots at 320 / 375 / 1440.

async function open(page: Page, type = 'single') {
	await page.goto('/dev/properties');
	await expect(page.getByRole('heading', { level: 1, name: 'Property panel' })).toBeVisible();
	if (type !== 'single') await page.getByTestId('type').selectOption(type);
}

const log = (page: Page) => page.getByTestId('op-log');
const toolbar = (page: Page) => page.getByRole('toolbar', { name: 'Text formatting' });
/** Select the word before the caret; ProseMirror reads the browser's selection asynchronously, so wait for it. */
async function selectWordLeft(page: Page) {
	await page.keyboard.press('Shift+ControlOrMeta+ArrowLeft');
	await page.waitForTimeout(100);
}

/** Insert a chip through the toolbar's picker. */
async function insertPipe(page: Page, id: string) {
	await toolbar(page).getByRole('button', { name: 'Insert answer' }).click();
	const picker = page.getByRole('dialog', { name: 'Insert answer' });
	await picker.getByRole('combobox').fill(id);
	await expect(picker.getByRole('option', { name: new RegExp(id) })).toHaveCount(1);
	await page.keyboard.press('Enter');
	await expect(picker).toBeHidden();
}


/** Paste HTML into the open editor (Chromium lets a test build the clipboard event). */
async function pasteHtml(field: Locator, html: string, text = '') {
	await field.evaluate(
		(el, [h, t]) => {
			const data = new DataTransfer();
			data.setData('text/html', h);
			data.setData('text/plain', t);
			el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }));
		},
		[html, text] as const
	);
}

test('the field is a labelled textbox at rest and an editor with a toolbar when focused', async ({ page }) => {
	await open(page);
	const field = page.getByLabel('Question text');
	await expect(field).toHaveAttribute('role', 'textbox');
	await expect(field).toHaveAttribute('aria-multiline', 'true');
	await expect(field).not.toHaveAttribute('contenteditable', 'true');
	await expect(toolbar(page)).toHaveCount(0);
	await expect(page.locator('[data-property="label"] .osp-rt-count')).toHaveText(/28 \/ 2,000/);

	await openRich(page, field);
	const tb = toolbar(page);
	await expect(tb).toBeVisible();
	for (const name of ['Bold', 'Italic', 'Link', 'Bulleted list', 'Numbered list', 'Insert answer', 'Line break', 'Clear formatting', 'Undo', 'Redo']) {
		await expect(tb.getByRole('button', { name, exact: true })).toBeVisible();
	}
	// A stem (an answerable question's text) offers no headings.
	await expect(tb.getByRole('combobox', { name: 'Text style' })).toHaveCount(0);
	expect(await axe(page)).toEqual([]);
});

test('bold, italic and a list become a rich value; clear formatting makes it plain again', async ({ page }) => {
	await open(page);
	const field = page.getByLabel('Question text');
	await fillRich(page, field, 'Thinking about last week');
	await selectWordLeft(page); // select "week"
	await page.keyboard.press('ControlOrMeta+b');
	await expect(toolbar(page).getByRole('button', { name: 'Bold' })).toHaveAttribute('aria-pressed', 'true');
	await expect(field.locator('strong')).toHaveText('week');
	await page.keyboard.press('Tab');
	await expect(log(page)).toContainText('{"text":"Thinking about last "},{"text":"week","marks":["b"]}');

	// Italic from the toolbar button (a click never blurs the text), then a bulleted list.
	await openRich(page, field);
	await page.keyboard.press('ControlOrMeta+a');
	await toolbar(page).getByRole('button', { name: 'Italic' }).click();
	await expect(field).toBeFocused();
	await expect(toolbar(page).getByRole('button', { name: 'Italic' })).toHaveAttribute('aria-pressed', 'true');
	await toolbar(page).getByRole('button', { name: 'Bulleted list' }).click();
	await expect(field.locator('ul li')).toHaveCount(1);
	await page.keyboard.press('Tab');
	await expect(log(page)).toContainText('"type":"ul","items":[[{"text":"Thinking about last ","marks":["i"]},{"text":"week","marks":["b","i"]}]]');

	await openRich(page, field);
	await page.keyboard.press('ControlOrMeta+a');
	await toolbar(page).getByRole('button', { name: 'Clear formatting' }).click();
	await expect(field.locator('strong, em, ul')).toHaveCount(0);
	await page.keyboard.press('Tab');
	await expect(log(page)).toContainText('"value":{"en":"Thinking about last week"}');
});

test('links: https only, applied to the selection, removable', async ({ page }) => {
	await open(page);
	const field = page.getByLabel('Question text');
	await fillRich(page, field, 'Read the information sheet');
	await selectWordLeft(page);
	await toolbar(page).getByRole('button', { name: 'Link' }).click();
	const dialog = page.getByRole('dialog', { name: 'Add link' });
	await expect(dialog).toBeVisible();
	const url = dialog.getByLabel('Web address');
	await expect(url).toBeFocused();
	await url.fill('http://example.org/sheet');
	await dialog.getByRole('button', { name: 'Add link' }).click();
	await expect(url).toHaveAccessibleDescription(/must start with https:\/\//);
	await expect(dialog).toBeVisible();
	await url.fill('https://example.org/sheet');
	await url.press('Enter');
	await expect(dialog).toBeHidden();
	await expect(field.locator('a.osp-rt-link')).toHaveAttribute('href', 'https://example.org/sheet');
	await expect(field.locator('a.osp-rt-link')).toHaveAttribute('target', '_blank');
	await expect(field).toBeFocused();
	await page.keyboard.press('Tab');
	await expect(log(page)).toContainText('{"text":"sheet","href":"https://example.org/sheet"}');

	// The caret in the link: the Link button is pressed; the dialog offers Remove link.
	await openRich(page, field);
	await caretToEnd(field);
	await page.keyboard.press('ArrowLeft');
	await expect(toolbar(page).getByRole('button', { name: 'Link' })).toHaveAttribute('aria-pressed', 'true');
	await toolbar(page).getByRole('button', { name: 'Link' }).click();
	const edit = page.getByRole('dialog', { name: 'Edit link' });
	await expect(edit.getByLabel('Web address')).toHaveValue('https://example.org/sheet');
	await edit.getByRole('button', { name: 'Remove link' }).click();
	await expect(field.locator('a')).toHaveCount(0);
	await page.keyboard.press('Tab');
	await expect(log(page)).toContainText('"value":{"en":"Read the information sheet"}');
});

test('a note is a block field: headings from the Text style select', async ({ page }) => {
	await open(page, 'note');
	const field = page.getByRole('textbox', { name: 'Text', exact: true });
	await fillRich(page, field, 'Before you start');
	const style = toolbar(page).getByRole('combobox', { name: 'Text style' });
	await style.selectOption('1');
	await expect(field.locator('h1')).toHaveText('Before you start');
	await page.keyboard.press('End');
	await page.keyboard.press('Enter');
	await page.keyboard.type('Read this first.');
	await expect(style).toHaveValue('0');
	await page.keyboard.press('Tab');
	await expect(log(page)).toContainText('{"type":"h","level":1,"content":[{"text":"Before you start"}]},{"type":"p","content":[{"text":"Read this first."}]}');
	await expect(page.locator('[data-property="label"] .osp-rt-count')).toHaveText(/32 \/ 20,000/);
	// Back at rest the read-only view keeps the heading.
	await expect(field.locator('.osp-rv-h[data-level="1"]')).toHaveText('Before you start');
});

test('a page title is inline: one line, no lists, Enter commits', async ({ page }) => {
	await open(page, 'page');
	const field = page.getByLabel('Title');
	await expect(field).toHaveAttribute('aria-multiline', 'false');
	await openRich(page, field);
	const tb = toolbar(page);
	await expect(tb.getByRole('button', { name: 'Bulleted list' })).toHaveCount(0);
	await expect(tb.getByRole('button', { name: 'Line break' })).toHaveCount(0);
	await page.keyboard.press('ControlOrMeta+a');
	await page.keyboard.type('Your habits');
	await page.keyboard.press('Enter');
	await expect(log(page)).toContainText('"property":"title","value":{"en":"Your habits"}');
	await expect(field).toHaveText('Your habits'); // Enter never split the line
	await expect(page.locator('[data-property="title"] .osp-rt-count')).toHaveText(/11 \/ 500/);
});

test('pipes: the picker inserts a chip, typing ${ opens it, Escape leaves the text', async ({ page }) => {
	await open(page);
	const field = page.getByLabel('Question text');
	await fillRich(page, field, 'You said you are ');
	await toolbar(page).getByRole('button', { name: 'Insert answer' }).click();
	const picker = page.getByRole('dialog', { name: 'Insert answer' });
	await expect(picker).toBeVisible();
	const search = picker.getByRole('combobox');
	await expect(search).toBeFocused();
	// Only questions before this one, then variables and built-ins, grouped.
	await expect(picker.getByRole('option')).toContainText(['q_age', 'cond', '$trial']);
	await expect(picker.getByRole('option', { name: /q_after/ })).toHaveCount(0);
	await expect(picker.getByRole('option', { name: /q_sleep/ })).toHaveCount(0);
	await search.fill('q_a');
	await expect(picker.getByRole('option')).toHaveCount(1);
	await page.keyboard.press('Enter');
	await expect(picker).toBeHidden();
	const chip = field.locator('.osp-rt-chip');
	await expect(chip).toHaveText('${q_age}');
	await expect(chip).toHaveAttribute('aria-label', 'Piped answer: q_age');
	await expect(field).toBeFocused();
	await page.keyboard.type(' years old');
	await page.keyboard.press('Tab');
	// No formatting: stored as the plain string, the chip written back as ${id} (RT-D3).
	await expect(log(page)).toContainText('"value":{"en":"You said you are ${q_age} years old"}');
	// At rest the chip is drawn the same way.
	await expect(field.locator('.osp-rt-chip')).toHaveText('${q_age}');

	// Typing `${` opens the picker; Escape keeps the two characters as text.
	await openRich(page, field);
	await caretToEnd(field);
	await page.keyboard.type(' ${');
	await expect(picker).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(picker).toBeHidden();
	await expect(field).toHaveText(/years old \$\{$/);
	// Typing on to a complete `${id}` turns it into a chip.
	await page.keyboard.type('cond}');
	await expect(field.locator('.osp-rt-chip')).toHaveCount(2);
	await page.keyboard.press('Tab');
	await expect(log(page)).toContainText('"value":{"en":"You said you are ${q_age} years old ${cond}"}');
});

test('paste is cleaned to the schema and says what was simplified', async ({ page }) => {
	await open(page);
	const field = page.getByLabel('Question text');
	await fillRich(page, field, '');
	await pasteHtml(
		field,
		'<h1 style="color:red">Title</h1><p><u>Under</u> <b>bold</b> <a href="http://x.org">plain</a> <a href="https://x.org/a">link</a> ${q_age}</p><img src="x.png"><ul><li>a<ul><li>b</li></ul></li></ul>'
	);
	const status = page.locator('[data-property="label"] .osp-rt-status');
	await expect(status).toHaveText('Formatting simplified: colours and fonts, 1 image, underline, 1 heading and 1 nested list removed; 1 link removed: not https');
	await expect(field).toHaveAccessibleDescription(/Formatting simplified/);
	await expect(field.locator('strong')).toHaveText('bold');
	await expect(field.locator('a')).toHaveCount(1);
	await expect(field.locator('.osp-rt-chip')).toHaveText('${q_age}');
	await expect(field.locator('li')).toHaveCount(2);
	// (ProseMirror draws its own separator <img> after a trailing atom: not pasted content.)
	await expect(field.locator('h1, u, img:not(.ProseMirror-separator)')).toHaveCount(0);
	await page.keyboard.press('Tab');
	await expect(log(page)).toContainText('{"text":"Under "},{"text":"bold","marks":["b"]},{"text":" plain "},{"text":"link","href":"https://x.org/a"},{"text":" "},{"pipe":"q_age"}');

	// Plain text pastes as paragraphs (`${id}` as chips), nothing to report.
	await openRich(page, field);
	await page.keyboard.press('ControlOrMeta+a');
	await pasteHtml(field, '', 'one\ntwo ${cond}');
	await expect(field.locator('p')).toHaveCount(2);
	await expect(field.locator('.osp-rt-chip')).toHaveText('${cond}');
	await expect(status).toHaveCount(0);
});

test('keyboard only: Tab in and out, Alt+F10 to the toolbar and back, Escape reverts a draft', async ({ page }) => {
	await open(page);
	// Tabbing from the group heading reaches the field, which opens the editor.
	await page.getByRole('button', { name: 'Basics' }).focus();
	const field = page.getByLabel('Question text');
	await page.keyboard.press('Tab');
	await expect(field).toHaveAttribute('contenteditable', 'true');
	await expect(field).toBeFocused();

	await page.keyboard.press('Alt+F10');
	const bold = toolbar(page).getByRole('button', { name: 'Bold' });
	await expect(bold).toBeFocused();
	await page.keyboard.press('ArrowRight');
	await expect(toolbar(page).getByRole('button', { name: 'Italic' })).toBeFocused();
	await page.keyboard.press('End'); // Undo and Redo are disabled (nothing to undo yet): skipped
	await expect(toolbar(page).getByRole('button', { name: 'Clear formatting' })).toBeFocused();
	await page.keyboard.press('Home');
	await expect(bold).toBeFocused();
	// One tab stop: Tab from the toolbar leaves it; Escape returns to the text.
	await page.keyboard.press('Alt+F10');
	await page.keyboard.press('Escape');
	await expect(field).toBeFocused();

	// Shortcut toggles are announced.
	await page.keyboard.press('ControlOrMeta+a');
	await page.keyboard.press('ControlOrMeta+b');
	await expect(page.getByTestId('announcer')).toHaveText('Bold on');
	await page.keyboard.press('ControlOrMeta+b');

	// A draft is reverted by Escape (no op), and the field keeps the Escape to itself.
	await caretToEnd(field);
	await page.keyboard.type(' oops');
	await expect(field).toHaveText(/oops$/);
	await page.keyboard.press('Escape');
	await expect(field).toHaveText('How many hours do you sleep?');
	await expect(field).toBeFocused();
	// Tab leaves the editor (never inserts a tab) to the next control, with nothing sent.
	await page.keyboard.press('Tab');
	await expect(field).not.toBeFocused();
	await expect(focused(page)).toHaveAccessibleName(/Help/);
	await expect(log(page).getByRole('listitem')).toHaveCount(0);
	// Help is now the open editor; its toolbar is one tab stop before it, so two Shift+Tabs
	// come back into this field (which opens again on focus).
	const help = focused(page);
	await expect(help).toHaveAttribute('contenteditable', 'true');
	await page.keyboard.press('Shift+Tab');
	await expect(focused(page)).toHaveAccessibleName('Bold');
	await page.keyboard.press('Shift+Tab');
	await expect(field).toHaveAttribute('contenteditable', 'true');
	await expect(field).toBeFocused();
});

test('the count turns into an error over the limit, and the commit still happens', async ({ page }) => {
	await open(page, 'page');
	const field = page.getByLabel('Title');
	await openRich(page, field);
	await page.keyboard.press('ControlOrMeta+a');
	await pasteHtml(field, '', 'x'.repeat(501));
	const count = page.locator('[data-property="title"] .osp-rt-count');
	await expect(count).toHaveText(/501 \/ 500/);
	await expect(count).toContainText('too long');
	await expect(field).toHaveAttribute('aria-invalid', 'true');
	await page.keyboard.press('Tab');
	await expect(log(page).getByRole('listitem')).toHaveCount(1);
});

for (const scheme of ['light', 'dark'] as const) {
	test.describe(`rich text, ${scheme}`, () => {
		test.use({ colorScheme: scheme });

		test('axe-clean with the editor, the link dialog and the picker open', async ({ page }) => {
			await open(page, 'note');
			const field = page.getByRole('textbox', { name: 'Text', exact: true });
			await fillRich(page, field, 'Read this first');
			await insertPipe(page, 'q_age');
			expect(await axe(page)).toEqual([]);
			await toolbar(page).getByRole('button', { name: 'Link' }).click();
			await expect(page.getByRole('dialog', { name: 'Add link' })).toBeVisible();
			expect(await axe(page)).toEqual([]);
			await page.keyboard.press('Escape');
			await toolbar(page).getByRole('button', { name: 'Insert answer' }).click();
			await expect(page.getByRole('dialog', { name: 'Insert answer' })).toBeVisible();
			expect(await axe(page)).toEqual([]);
		});

		for (const width of [320, 375, 1440]) {
			test(`snapshot at ${width}`, async ({ page }) => {
				await page.setViewportSize({ width, height: 900 });
				await open(page, 'note');
				const field = page.getByRole('textbox', { name: 'Text', exact: true });
				await fillRich(page, field, 'Before you start');
				await toolbar(page).getByRole('combobox', { name: 'Text style' }).selectOption('1');
				await page.keyboard.press('End');
				await page.keyboard.press('Enter');
				await page.keyboard.type('Read the information sheet and keep your ');
				await page.keyboard.press('ControlOrMeta+b');
				await page.keyboard.type('code');
				await page.keyboard.press('ControlOrMeta+b');
				await page.keyboard.type(' ');
				await insertPipe(page, 'q_age');
				await page.keyboard.type(' handy.');
				// Under 480 px the rarely used controls fold into a More menu.
				const more = toolbar(page).getByRole('button', { name: 'More formatting' });
				if (width < 480) {
					await expect(more).toBeVisible();
					await expect(toolbar(page).getByRole('button', { name: 'Undo' })).toHaveCount(0);
				} else await expect(more).toHaveCount(0);
				await expect(page.locator('[data-property="label"]')).toHaveScreenshot(`richtext-${width}-${scheme}.png`);
			});
		}
	});
}

test('the More menu runs the folded commands at 320 px, from the keyboard', async ({ page }) => {
	await page.setViewportSize({ width: 320, height: 900 });
	await open(page);
	const field = page.getByLabel('Question text');
	await fillRich(page, field, 'Short');
	const more = toolbar(page).getByRole('button', { name: 'More formatting' });
	await more.focus();
	await page.keyboard.press('Enter');
	const menu = page.getByRole('menu');
	await expect(menu).toBeVisible();
	await expect(menu.getByRole('menuitem')).toHaveText([/Line break/, /Clear formatting/, /Undo/, /Redo/]);
	await menu.getByRole('menuitem', { name: /Undo/ }).click();
	await expect(menu).toBeHidden();
	await expect(field).toBeFocused();
	await expect(field).toHaveText('How many hours do you sleep?');
	expect(await axe(page)).toEqual([]);
});

test('in the editor against a real osp-api: formatting is saved, shown on the card and survives a reload', async ({ page }) => {
	await signIn(page);
	await page.getByLabel('New survey title').fill(`Rich text ${Date.now()}`);
	await page.getByRole('button', { name: 'Create survey' }).click();
	await expect(page).toHaveURL(/\/surveys\/[^/]+$/);
	await page.getByRole('button', { name: /Add question to/ }).first().click();
	await pickQuestionType(page);

	const saved = page.getByRole('banner').getByRole('status').first();
	const field = page.getByRole('complementary', { name: 'Properties' }).getByRole('textbox', { name: 'Question text' });
	await fillRich(page, field, 'How many hours did you sleep ');
	await page.keyboard.press('ControlOrMeta+b');
	await page.keyboard.type('last');
	await page.keyboard.press('ControlOrMeta+b');
	await page.keyboard.type(' night?');
	await page.keyboard.press('Tab');
	await expect(saved).toHaveText(/All changes saved/);
	const id = page.url().split('/').pop()!;
	// The new question is appended after the survey's starter item.
	const stored = async () => ((await (await page.request.get(`/api/surveys/${id}`)).json()) as { survey: { blocks: { pages: { items: { label: unknown }[] }[] }[] } }).survey.blocks[0]!.pages[0]!.items.at(-1)!.label;
	const card = page.locator('[data-question-card]').filter({ hasText: 'How many hours' });
	await expect(card.locator('strong')).toHaveText('last');
	expect(await axe(page)).toEqual([]);

	await page.reload();
	await expect(card.locator('strong')).toHaveText('last');
	await page.getByRole('tree', { name: 'Survey outline' }).getByRole('treeitem', { name: /How many hours/ }).click();
	await expect(field.locator('strong')).toHaveText('last');
	// The server's view: a rich tree with the bold run (a value edited in the default
	// language stays unwrapped, as the plain string was).
	expect(await stored()).toEqual({
		type: 'rich',
		blocks: [{ type: 'p', content: [{ text: 'How many hours did you sleep ' }, { text: 'last', marks: ['b'] }, { text: ' night?' }] }]
	});
});
