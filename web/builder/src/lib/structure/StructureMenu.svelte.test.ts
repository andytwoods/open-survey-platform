import '@testing-library/svelte/vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import axe from 'axe-core';
import { tick } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import { outlineFromSurvey } from '../model/outline';
import type { SurveyStore } from '../sync/survey-store.svelte';
import { StructureActions } from './actions.svelte';
import StructureMenu from './StructureMenu.svelte';

const SURVEY = {
	id: 's',
	metadata: { languages: ['en'] },
	blocks: [
		{
			id: 'b1',
			pages: [
				{ id: 'p1', title: { en: 'First' }, items: [{ id: 'qa', type: 'text', label: 'A' }] },
				{ id: 'p2', items: [{ id: 'qb', type: 'text', label: 'B ${qa}' }] }
			]
		}
	],
	flow: [{ type: 'block', id: 'n1', block: 'b1' }]
};
const roots = outlineFromSurvey(SURVEY);

type Ops = { op: string; params: Record<string, unknown> }[];

function fakeStore(answers: ((ops: Ops) => unknown)[]) {
	const submit = vi.fn(async (...[ops]: [Ops, unknown?]) => answers.shift()?.(ops) ?? { status: 'applied', result: { patch: [] } });
	return { store: { survey: SURVEY, submit } as unknown as SurveyStore, submit };
}

function actionsWith(store: SurveyStore | null) {
	const edit = vi.fn();
	const focus = vi.fn();
	const actions = new StructureActions({ store: () => store, roots: () => roots, edit, focus, language: () => 'en' });
	return { actions, edit, focus };
}

const flush = async () => {
	for (let i = 0; i < 4; i++) await tick();
};

describe('StructureMenu', () => {
	it('is a keyboard menu: focus in, arrows, Enter runs, focus goes back', async () => {
		const opener = document.createElement('button');
		opener.textContent = 'opener';
		document.body.append(opener);
		opener.focus();
		const { store, submit } = fakeStore([]);
		const { actions } = actionsWith(store);
		render(StructureMenu, { props: { target: { id: 'p1', label: 'First', anchor: opener }, actions } });
		await flush();
		const menu = screen.getByRole('menu', { name: 'Actions for First' });
		const items = screen.getAllByRole('menuitem').map((e) => e.textContent?.trim());
		expect(items).toEqual(['Add page after', 'Rename…', 'Duplicate', 'Delete…']);
		expect(document.activeElement?.textContent?.trim()).toBe('Add page after');
		await fireEvent.keyDown(menu, { key: 'ArrowDown' });
		await fireEvent.keyDown(menu, { key: 'ArrowDown' });
		expect(document.activeElement?.textContent?.trim()).toBe('Duplicate');
		expect((await axe.run(menu, { rules: { region: { enabled: false } } })).violations).toEqual([]);
		await fireEvent.keyDown(menu, { key: 'Enter' });
		await flush();
		expect(screen.queryByRole('menu')).toBeNull();
		expect(document.activeElement).toBe(opener);
		expect(submit).toHaveBeenCalledWith([{ op: 'duplicate_page', params: { id: 'p1', new_id: 'p1_copy' } }]);
		opener.remove();
	});

	it('Escape closes without running anything; blocks also offer Add block', async () => {
		const { store, submit } = fakeStore([]);
		const { actions } = actionsWith(store);
		render(StructureMenu, { props: { target: { id: 'b1', label: 'b1', anchor: null }, actions } });
		await flush();
		expect(screen.getAllByRole('menuitem').map((e) => e.textContent?.trim())).toContain('Add block after');
		await fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
		expect(screen.queryByRole('menu')).toBeNull();
		expect(submit).not.toHaveBeenCalled();
	});
});

describe('StructureActions', () => {
	it('adds a page after the selected one and focuses its title', async () => {
		const { store, submit } = fakeStore([]);
		const { actions, edit } = actionsWith(store);
		await actions.addPage('p1');
		expect(submit).toHaveBeenCalledWith([{ op: 'add_page', params: { block: 'b1', index: 1, id: 'page1' } }]);
		expect(edit).toHaveBeenCalledWith('page1', 'page', ['title']);
	});

	it('a referenced delete asks first, then retries with force; Keep does nothing', async () => {
		const dangling = {
			status: 'rejected',
			message: 'still referenced',
			diagnostics: [
				{ code: 'op.dangling_ref', message: 'summary', pointer: '/blocks/0/pages/1/items/0/label' },
				{ code: 'op.dangling_ref', message: "refers to 'qa'", pointer: '/blocks/0/pages/1/items/0/label/en' }
			]
		};
		const { store, submit } = fakeStore([() => dangling, () => dangling]);
		const { actions, focus } = actionsWith(store);
		await actions.remove('p1');
		expect(submit.mock.calls[0][1]).toEqual({ quiet: ['op.dangling_ref'] });
		expect(actions.deleteRequest).toMatchObject({ id: 'p1', type: 'page', name: 'First', sites: ['B ${qa} (text)'] });
		actions.resolveDelete(false);
		expect(actions.deleteRequest).toBeNull();
		expect(submit).toHaveBeenCalledTimes(1);

		await actions.remove('p1');
		actions.resolveDelete(true);
		await flush();
		expect(submit.mock.calls[2][0]).toEqual([{ op: 'delete_page', params: { id: 'p1', force: true } }]);
		expect(focus).toHaveBeenCalledWith('p2');
	});

	it('refuses to delete a block’s only page without asking the server', async () => {
		const { store, submit } = fakeStore([]);
		const single = { ...SURVEY, blocks: [{ id: 'b1', pages: [SURVEY.blocks[0].pages[0]] }] };
		const r = outlineFromSurvey(single);
		const actions = new StructureActions({ store: () => store, roots: () => r, edit: vi.fn(), focus: vi.fn(), language: () => 'en' });
		await actions.remove('p1');
		expect(submit).not.toHaveBeenCalled();
	});
});
