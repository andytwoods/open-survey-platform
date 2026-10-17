import '@testing-library/svelte/vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import axe from 'axe-core';
import { describe, expect, it } from 'vitest';
import { orderTypes, type QuestionTypeId } from './catalogue';
import TypePicker from './TypePicker.svelte';

// The type picker on its own (the dialog around it is ui-components' Dialog): keyboard,
// filter, last used first, the current type when changing, a11y.

function setup(props: { lastUsed?: QuestionTypeId | null; current?: QuestionTypeId } = {}) {
	const chosen: QuestionTypeId[] = [];
	const t = render(TypePicker, {
		types: orderTypes(props.current ? null : props.lastUsed),
		lastUsed: props.lastUsed ?? null,
		current: props.current,
		onchoose: (id: QuestionTypeId) => chosen.push(id)
	});
	const input = screen.getByRole('combobox', { name: 'Filter question types' });
	const options = () => screen.getAllByRole('option');
	const active = () => options().find((o) => o.getAttribute('aria-selected') === 'true');
	return { t, input, options, active, chosen };
}

describe('TypePicker', () => {
	it('lists all nine types with names and descriptions; the first is active', () => {
		const { input, options, active } = setup();
		expect(options()).toHaveLength(9);
		expect(options()[0]?.textContent).toContain('Text');
		expect(options()[0]?.textContent).toContain('A typed answer');
		expect(active()).toBe(options()[0]);
		expect(input.getAttribute('aria-activedescendant')).toBe(options()[0].id);
		expect(screen.getByRole('listbox', { name: 'Question types' })).toBeTruthy();
	});

	it('arrows move (wrapping), Home/End jump, Enter chooses', async () => {
		const { input, options, active, chosen } = setup();
		await fireEvent.keyDown(input, { key: 'ArrowDown' });
		await fireEvent.keyDown(input, { key: 'ArrowDown' });
		expect(active()?.textContent).toContain('Decimal number');
		expect(input.getAttribute('aria-activedescendant')).toBe(active()!.id);
		await fireEvent.keyDown(input, { key: 'ArrowUp' });
		await fireEvent.keyDown(input, { key: 'ArrowUp' });
		await fireEvent.keyDown(input, { key: 'ArrowUp' });
		expect(active()).toBe(options()[8]); // wrapped to Note
		await fireEvent.keyDown(input, { key: 'Home' });
		expect(active()).toBe(options()[0]);
		await fireEvent.keyDown(input, { key: 'End' });
		expect(active()?.textContent).toContain('Note');
		await fireEvent.keyDown(input, { key: 'Enter' });
		expect(chosen).toEqual(['note']);
	});

	it('typing filters; the best match is active; no match says so', async () => {
		const { input, options, active, chosen } = setup();
		await fireEvent.input(input, { target: { value: 'check' } });
		expect(options()).toHaveLength(1);
		expect(active()?.textContent).toContain('Multiple choice');
		await fireEvent.keyDown(input, { key: 'Enter' });
		expect(chosen).toEqual(['multi']);
		await fireEvent.input(input, { target: { value: 'number' } });
		expect(options().map((o) => o.dataset.type)).toEqual(['integer', 'decimal']);
		await fireEvent.input(input, { target: { value: 'zzz' } });
		expect(screen.queryAllByRole('option')).toHaveLength(0);
		expect(screen.getByRole('status')?.textContent).toContain('No question type matches');
		await fireEvent.keyDown(input, { key: 'Enter' });
		expect(chosen).toEqual(['multi']);
	});

	it('a click chooses', async () => {
		const { options, chosen } = setup();
		await fireEvent.click(options()[6]);
		expect(chosen).toEqual(['matrix']);
	});

	it('puts the last used type first, marked and active', () => {
		const { options, active } = setup({ lastUsed: 'slider' });
		expect(options()[0]?.textContent).toContain('Slider');
		expect(options()[0]?.textContent).toContain('Last used');
		expect(active()).toBe(options()[0]);
		expect(options().filter((o) => o.textContent?.includes('Last used'))).toHaveLength(1);
	});

	it('changing a type: the current one is marked, the next one is active', async () => {
		const { options, active, input, chosen } = setup({ current: 'text' });
		expect(options()[0]?.textContent).toContain('Current');
		expect(options()[0].hasAttribute('data-current')).toBe(true);
		expect(active()?.textContent).toContain('Whole number');
		await fireEvent.keyDown(input, { key: 'Enter' });
		expect(chosen).toEqual(['integer']);
	});

	it('passes axe', async () => {
		const { t } = setup({ lastUsed: 'single' });
		const res = await axe.run(t.container, {
			rules: { 'color-contrast': { enabled: false }, region: { enabled: false } }
		});
		expect(res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(', ')}`)).toEqual([]);
	});
});
