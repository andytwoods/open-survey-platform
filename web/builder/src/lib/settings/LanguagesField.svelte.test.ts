import '@testing-library/svelte/vitest';
import { fireEvent, render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it } from 'vitest';
import type { Outcome } from '../sync/survey-store.svelte';
import type { Invocation } from '../sync/transport';
import LanguagesField from './LanguagesField.svelte';

// The store applies an edit only when the server answers. Every set_languages sends the whole
// list, so an add or remove made while the previous one is still in flight must build on what
// was sent, not on the not-yet-updated survey (two quick adds dropped the first, as F1 did
// for consent).

type Params = { languages: string[]; default_language?: string; cascade?: boolean };

const surveyWith = (languages: string[], defaultLanguage?: string) => ({
	metadata: { title: 'S', languages, ...(defaultLanguage ? { defaultLanguage } : {}) },
	blocks: []
});

function setup(languages: string[], defaultLanguage?: string) {
	const sent: Params[] = [];
	const answers: ((o: Outcome) => void)[] = [];
	const submit = (ops: Invocation[]) => {
		sent.push(ops[0]!.params as Params);
		return new Promise<Outcome>((resolve) => answers.push(resolve));
	};
	const view = render(LanguagesField, { survey: surveyWith(languages, defaultLanguage), submit });
	const input = view.getByLabelText(/Add a language/) as HTMLInputElement;
	const addTag = async (tag: string) => {
		await fireEvent.input(input, { target: { value: tag } });
		await fireEvent.keyDown(input, { key: 'Enter' });
	};
	return { ...view, sent, answers, input, addTag };
}

const applied = { status: 'applied' } as unknown as Outcome;

describe('LanguagesField', () => {
	it('keeps an add still in flight when a second language is added', async () => {
		const { sent, addTag } = setup(['en']);
		await addTag('de');
		await addTag('fr');
		expect(sent.map((p) => p.languages)).toEqual([
			['en', 'de'],
			['en', 'de', 'fr']
		]);
	});

	it('keeps a removal still in flight when a second language is removed', async () => {
		const { getByRole, sent } = setup(['en', 'de', 'fr'], 'de');
		await fireEvent.click(getByRole('button', { name: 'Remove language de' }));
		await fireEvent.click(getByRole('button', { name: 'Remove language fr' }));
		expect(sent).toEqual([{ languages: ['en', 'fr'] }, { languages: ['en'] }]);
	});

	it('does not clear a tag typed while the previous add was in flight', async () => {
		const { sent, answers, input, addTag } = setup(['en']);
		await addTag('de');
		await fireEvent.input(input, { target: { value: 'fr' } });
		answers[0]!(applied);
		await new Promise((r) => setTimeout(r, 0));
		await tick();
		expect(input.value).toBe('fr');
		expect(sent).toHaveLength(1);
	});

	it('builds on the survey again once nothing is in flight, and offers the cascade', async () => {
		const { getByRole, findByRole, rerender, sent, answers } = setup(['en', 'de']);
		await fireEvent.click(getByRole('button', { name: 'Remove language de' }));
		// The server refuses it (de still has translations): the survey keeps de.
		answers[0]!({
			status: 'rejected',
			message: 'No.',
			diagnostics: [{ code: 'op.dangling_ref', message: 'de still has translations.' }]
		} as unknown as Outcome);
		await rerender({ survey: surveyWith(['en', 'de']) });
		const cascade = await findByRole('button', { name: 'Remove de and delete its translations' });
		await fireEvent.click(cascade);
		expect(sent[1]).toEqual({ languages: ['en'], cascade: true });
	});
});
