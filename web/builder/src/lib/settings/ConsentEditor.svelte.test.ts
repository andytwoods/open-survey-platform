import '@testing-library/svelte/vitest';
import { fireEvent, render } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import type { Outcome } from '../sync/survey-store.svelte';
import type { Invocation } from '../sync/transport';
import ConsentEditor from './ConsentEditor.svelte';

// The store applies an edit only when the server answers. Every set_consent sends the whole
// consent object, so an edit made while the previous one is still in flight must build on
// what was sent, not on the not-yet-updated survey (the publish e2e lost the consent text
// this way when the agree label was committed before the text's echo arrived).

type Consent = Record<string, unknown> | null;

function setup() {
	const sent: Consent[] = [];
	const answers: ((o: Outcome) => void)[] = [];
	const submit = (ops: Invocation[]) => {
		sent.push((ops[0]!.params as { consent: Consent }).consent);
		return new Promise<Outcome>((resolve) => answers.push(resolve));
	};
	const survey = { metadata: { title: 'S', languages: ['en'] }, consent: { text: { en: '' } }, blocks: [] };
	const view = render(ConsentEditor, { survey, defaultLanguage: 'en', submit });
	return { ...view, sent, answers };
}

describe('ConsentEditor', () => {
	it('keeps an edit still in flight when the next field is committed', async () => {
		const { getByLabelText, getByRole, sent } = setup();
		const text = getByLabelText('Consent text') as HTMLTextAreaElement;
		await fireEvent.input(text, { target: { value: 'Taking part is voluntary.' } });
		await fireEvent.change(text);
		const agree = getByLabelText('Agree button') as HTMLInputElement;
		await fireEvent.input(agree, { target: { value: 'Yes, I take part' } });
		await fireEvent.change(agree);
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
		const text = getByLabelText('Consent text') as HTMLTextAreaElement;
		await fireEvent.input(text, { target: { value: 'Draft' } });
		await fireEvent.change(text);
		// The server refuses it: the survey keeps the old consent, and the next edit starts there.
		answers[0]!({ status: 'rejected', message: 'No.', diagnostics: [] } as unknown as Outcome);
		await Promise.resolve();
		await rerender({
			survey: { metadata: { title: 'S', languages: ['en'] }, consent: { text: { en: 'Server' } }, blocks: [] }
		});
		const agree = getByLabelText('Agree button') as HTMLInputElement;
		await fireEvent.input(agree, { target: { value: 'OK' } });
		await fireEvent.change(agree);
		expect(sent[1]).toEqual({ text: { en: 'Server' }, agreeLabel: { en: 'OK' } });
	});
});
