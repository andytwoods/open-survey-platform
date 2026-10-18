import '@testing-library/svelte/vitest';
import { fireEvent, render } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import EditingLanguageSelect from './EditingLanguageSelect.svelte';
import { editingLanguage, editLanguageOf, initEditingLanguage, setEditingLanguage, setReferenceOpen } from './editing-language.svelte';

// The shared editing language (planning/rich-text.md §5, RT6) in jsdom: read from the URL,
// else from what the survey remembers; written to both; the select bound to it.

const survey = { metadata: { languages: ['en', 'de', 'fr'], defaultLanguage: 'en' } };

afterEach(() => {
	history.replaceState(null, '', '/');
	localStorage.clear();
	editingLanguage.requested = null;
	editingLanguage.referenceOpen = true;
});

describe('editing language state', () => {
	it('starts from ?lang=, else from memory, else the default', () => {
		initEditingLanguage('s1');
		expect(editLanguageOf(survey)).toBe('en');

		localStorage.setItem('osp.editing-language.s1', 'fr');
		initEditingLanguage('s1');
		expect(editLanguageOf(survey)).toBe('fr');

		history.replaceState(null, '', '/surveys/s1?lang=de');
		initEditingLanguage('s1');
		expect(editLanguageOf(survey)).toBe('de');
		// A language the survey does not have falls back to the default.
		expect(editLanguageOf({ metadata: { languages: ['en', 'fr'] } })).toBe('en');
	});

	it('writes the choice to the URL (non-default only) and remembers it', () => {
		history.replaceState(null, '', '/surveys/s1#select=q1');
		initEditingLanguage('s1');
		setEditingLanguage('de', 'en');
		expect(location.search).toBe('?lang=de');
		expect(location.hash).toBe('#select=q1');
		expect(localStorage.getItem('osp.editing-language.s1')).toBe('de');
		expect(editLanguageOf(survey)).toBe('de');
		setEditingLanguage('en', 'en');
		expect(location.search).toBe('');
		expect(localStorage.getItem('osp.editing-language.s1')).toBe('en');
	});

	it('remembers the reference strip collapsed', () => {
		setReferenceOpen(false);
		expect(localStorage.getItem('osp.reference-strip')).toBe('closed');
		editingLanguage.referenceOpen = true;
		initEditingLanguage('s1');
		expect(editingLanguage.referenceOpen).toBe(false);
		setReferenceOpen(true);
		expect(localStorage.getItem('osp.reference-strip')).toBeNull();
	});
});

describe('EditingLanguageSelect', () => {
	it('lists the default first and drives the shared state', async () => {
		initEditingLanguage('s1');
		const { getByLabelText } = render(EditingLanguageSelect, { survey, id: 'el' });
		const select = getByLabelText('Editing language') as HTMLSelectElement;
		expect([...select.options].map((o) => o.textContent)).toEqual(['en (default)', 'de', 'fr']);
		expect(select.value).toBe('en');
		await fireEvent.change(select, { target: { value: 'de' } });
		expect(editLanguageOf(survey)).toBe('de');
		expect(location.search).toBe('?lang=de');
	});

	it('renders nothing for a single-language survey', () => {
		const { container } = render(EditingLanguageSelect, { survey: { metadata: { languages: ['en'] } } });
		expect(container.querySelector('select')).toBeNull();
	});
});
