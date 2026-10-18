import '@testing-library/svelte/vitest';
import { fireEvent, render } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import { activate, blurField, typeInto } from '../richtext/test-utils';
import type { Outcome } from '../sync/survey-store.svelte';
import type { Invocation } from '../sync/transport';
import { editingLanguage } from '../translations/editing-language.svelte';
import ConsentEditor from './ConsentEditor.svelte';

// The store applies an edit only when the server answers. Every set_consent sends the whole
// consent object, so an edit made while the previous one is still in flight must build on
// what was sent, not on the not-yet-updated survey (the publish e2e lost the consent text
// this way when the agree label was committed before the text's echo arrived).
// The fields are rich-text editors (RT3): tests drive them through the editor's commands.

type Consent = Record<string, unknown> | null;

function setup(consent: Record<string, unknown> = { text: { en: '' } }, languages = ['en']) {
	const sent: Consent[] = [];
	const answers: ((o: Outcome) => void)[] = [];
	const submit = (ops: Invocation[]) => {
		sent.push((ops[0]!.params as { consent: Consent }).consent);
		return new Promise<Outcome>((resolve) => answers.push(resolve));
	};
	const survey = { metadata: { title: 'S', languages }, consent, blocks: [] };
	const view = render(ConsentEditor, { survey, defaultLanguage: 'en', submit });
	return { ...view, sent, answers };
}

afterEach(() => {
	editingLanguage.requested = null;
});

/** Edit a consent field as a researcher would: focus, replace the text, leave. */
async function edit(el: HTMLElement, text: string) {
	const ed = await activate(el);
	await typeInto(ed, text);
	await blurField(el.id);
}

describe('ConsentEditor', () => {
	it('keeps an edit still in flight when the next field is committed', async () => {
		const { getByLabelText, getByRole, sent } = setup();
		await edit(getByLabelText('Consent text'), 'Taking part is voluntary.');
		await edit(getByLabelText('Agree button'), 'Yes, I take part');
		await fireEvent.click(getByRole('checkbox', { name: 'Count declines' }));

		expect(sent).toHaveLength(3);
		expect(sent[1]).toEqual({ text: { en: 'Taking part is voluntary.' }, agreeLabel: { en: 'Yes, I take part' } });
		expect(sent[2]).toEqual({
			text: { en: 'Taking part is voluntary.' },
			agreeLabel: { en: 'Yes, I take part' },
			countDeclines: true
		});
	});

	it('builds on the survey again once nothing is in flight', async () => {
		const { getByLabelText, rerender, sent, answers } = setup();
		await edit(getByLabelText('Consent text'), 'Draft');
		// The server refuses it: the survey keeps the old consent, and the next edit starts there.
		answers[0]!({ status: 'rejected', message: 'No.', diagnostics: [] } as unknown as Outcome);
		await Promise.resolve();
		await rerender({
			survey: { metadata: { title: 'S', languages: ['en'] }, consent: { text: { en: 'Server' } }, blocks: [] }
		});
		await edit(getByLabelText('Agree button'), 'OK');
		expect(sent[1]).toEqual({ text: { en: 'Server' }, agreeLabel: { en: 'OK' } });
	});

	it('shows a rich consent text with its formatting, offers no pipes, and keeps the tree when editing', async () => {
		const rich = { type: 'rich', blocks: [{ type: 'h', level: 1, content: [{ text: 'Information' }] }, { type: 'p', content: [{ text: 'Read ', marks: ['b'] }, { text: 'this' }] }] };
		const { getByLabelText, getByTestId, container, sent } = setup({ text: { en: rich } });
		const field = getByLabelText('Consent text');
		expect(field.querySelector('.osp-rv-h')!.textContent).toBe('Information');
		expect(getByTestId('consent-preview').querySelector('strong')!.textContent).toBe('Read ');
		const ed = await activate(field);
		expect(container.querySelector('[role="toolbar"] [aria-label="Insert answer"]')).toBeNull();
		expect(container.querySelector('[role="toolbar"] select[aria-label="Text style"]')).not.toBeNull();
		ed.commands.insertContentAt(ed.state.doc.content.size - 1, ' now');
		await blurField(field.id);
		expect(sent[0]).toEqual({
			text: { en: { type: 'rich', blocks: [{ type: 'h', level: 1, content: [{ text: 'Information' }] }, { type: 'p', content: [{ text: 'Read ', marks: ['b'] }, { text: 'this now' }] }] } }
		});
	});

	it('edits the page\'s editing language, with the default text as reference and Copy from it (RT6)', async () => {
		editingLanguage.requested = 'de';
		const { getByLabelText, getByTestId, container, sent } = setup({ text: { en: 'Voluntary.' }, agreeLabel: { en: 'Yes' } }, ['en', 'de']);
		expect((getByLabelText('Editing language') as HTMLSelectElement).value).toBe('de');
		expect(getByTestId('consent-missing').textContent).toContain('de');
		const field = getByLabelText('Consent text');
		expect(field.textContent).toBe(''); // de has no text yet
		expect(field.getAttribute('lang')).toBe('de');
		const strips = container.querySelectorAll('[data-testid="reference-strip"]');
		expect(strips).toHaveLength(2); // text and the agree label; the decline label has no default text
		expect(strips[0]!.querySelector('.osp-rt-ref-body')!.textContent).toBe('Voluntary.');
		await fireEvent.click(strips[0]!.querySelector('.osp-rt-ref-copy')!);
		expect(sent[0]).toEqual({ text: { en: 'Voluntary.', de: 'Voluntary.' }, agreeLabel: { en: 'Yes' } });
	});
});
