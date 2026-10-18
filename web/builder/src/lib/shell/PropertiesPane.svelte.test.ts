import '@testing-library/svelte/vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import '../richtext/test-utils';
import { propertyFocus } from '../diagnostics/focus.svelte';
import { outlineFromSurvey } from '../model/outline';
import fixture from '../properties/fixtures/property-schemas.json';
import { SelectionStore } from '../selection.svelte';
import type { SurveyStore } from '../sync/survey-store.svelte';
import PropertiesPane from './PropertiesPane.svelte';

// "Go to property" (B10, and "Add page" focusing the new page's title) must wait for the
// property schemas: they are fetched once per page load, and an edit made just after the
// page loads can beat them (F6). Focus then lands on the field, not the pane's heading.

const schemas = vi.hoisted(() => {
	let resolve: (r: { data?: unknown }) => void = () => {};
	const pending = new Promise<{ data?: unknown }>((r) => (resolve = r));
	return { pending, resolve: (r: { data?: unknown }) => resolve(r) };
});

vi.mock('../properties/schemas.svelte', async (original) => ({
	...(await original<typeof import('../properties/schemas.svelte')>()),
	fetchPropertySchemas: () => schemas.pending
}));

const survey = {
	metadata: { title: 'Focus', languages: ['en'] },
	choiceLists: [],
	blocks: [{ id: 'b1', pages: [{ id: 'p1', title: { en: 'Start' }, items: [] }] }],
	flow: [{ type: 'block', id: 'n1', block: 'b1' }]
};

function fakeStore(): SurveyStore {
	return {
		survey,
		surveyId: 's1',
		diagnostics: [],
		rejection: null,
		registerBuffer: () => () => {},
		submit: vi.fn(async () => ({ status: 'applied' })),
		markDirty: () => {}
	} as unknown as SurveyStore;
}

describe('PropertiesPane focus requests', () => {
	it('waits for the property schemas, then focuses the requested field', async () => {
		const selection = new SelectionStore();
		render(PropertiesPane, { props: { roots: outlineFromSurvey(survey), selection, store: fakeStore() } });
		selection.select('p1');
		propertyFocus.ask('p1', ['title']);
		await tick();
		await tick();
		// Still loading: the request waits, focus has not fallen back to the heading.
		expect(document.activeElement?.id).not.toBe('properties-heading');
		expect(propertyFocus.request).not.toBeNull();

		schemas.resolve({ data: fixture });
		const title = await screen.findByText('Title', { selector: 'label' });
		const id = (title as HTMLLabelElement).htmlFor;
		await waitFor(() => expect(document.activeElement?.id).toBe(id));
		expect(propertyFocus.request).toBeNull();
	});
});
