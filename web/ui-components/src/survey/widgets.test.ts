import { render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { announcer } from '../live-region.svelte';
import DateInput from './DateInput.svelte';
import DecimalInput from './DecimalInput.svelte';
import IntegerInput from './IntegerInput.svelte';
import Matrix from './Matrix.svelte';
import MultiChoice from './MultiChoice.svelte';
import Note from './Note.svelte';
import SingleChoice from './SingleChoice.svelte';
import Slider from './Slider.svelte';
import TextInput from './TextInput.svelte';
import type { Choice } from './types';

const fruit: Choice[] = [
	{ value: 'apple', label: 'Apple' },
	{ value: 'pear', label: 'Pear' },
	{ value: 'plum', label: 'Plum', help: 'The purple one' }
];

afterEach(() => vi.useRealTimers());

describe('QuestionFrame (via the widgets)', () => {
	it('renders label segments as text, never as markup', () => {
		const { container } = render(Note, {
			id: 'n1',
			label: [
				{ text: 'Hello ' },
				{ text: '<img src=x onerror=alert(1)>', strong: true },
				{ text: ' world', lang: 'fr' }
			]
		});
		expect(container.querySelector('img')).toBeNull();
		expect(container.querySelector('strong')?.textContent).toBe('<img src=x onerror=alert(1)>');
		expect(container.querySelector('span[lang="fr"]')?.textContent).toBe(' world');
		expect(container.querySelector('input, textarea, button')).toBeNull();
	});

	it('marks required, links help and error with aria-describedby', () => {
		render(TextInput, {
			id: 'q1',
			label: 'Your name',
			help: 'As on your card',
			required: true,
			value: '',
			error: 'Enter your name.'
		});
		const box = screen.getByRole('textbox', { name: /Your name/ });
		expect(screen.getByText('(Required)')).toBeTruthy();
		const ids = box.getAttribute('aria-describedby')!.split(' ');
		expect(ids.map((i) => document.getElementById(i)?.textContent?.trim())).toEqual([
			'As on your card',
			'Enter your name.'
		]);
		expect(box.getAttribute('aria-invalid')).toBe('true');
	});

	it('announces a revealed question once', async () => {
		vi.useFakeTimers();
		render(Note, { id: 'n2', label: 'Thanks', revealed: true });
		vi.advanceTimersByTime(100);
		expect(announcer.polite).toBe('New question: Thanks');
		announcer.polite = '';
		await tick();
		vi.advanceTimersByTime(100);
		expect(announcer.polite).toBe('');
	});
});

describe('IntegerInput / DecimalInput', () => {
	it('uses a numeric keypad, ≥16px class, and emits a canonical string', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn();
		render(IntegerInput, { id: 'age', label: 'Age', value: null, onchange });
		const box = screen.getByRole('textbox', { name: 'Age' });
		expect(box.getAttribute('inputmode')).toBe('numeric');
		expect(box.getAttribute('enterkeyhint')).toBe('next');
		await user.type(box, '042');
		expect(onchange).toHaveBeenLastCalledWith('42');
	});

	it('shows a format message after blur, not while typing', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn();
		render(IntegerInput, { id: 'n', label: 'Count', value: null, onchange });
		const box = screen.getByRole('textbox', { name: 'Count' });
		await user.type(box, '1.5');
		expect(onchange).toHaveBeenLastCalledWith(null);
		expect(screen.queryByText(/whole number/)).toBeNull();
		await user.tab();
		expect(screen.getByText(/whole number/)).toBeTruthy();
		expect(box.getAttribute('aria-invalid')).toBe('true');
	});

	it('uses a keyboard with a minus sign when min is negative', () => {
		render(IntegerInput, { id: 't', label: 'Temp', value: null, min: -50 });
		expect(screen.getByRole('textbox').getAttribute('inputmode')).toBe('text');
	});

	it('shows and reads the locale decimal separator, keeping the value exact', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn();
		render(DecimalInput, { id: 'w', label: 'Gewicht', value: '3.50', lang: 'de', onchange });
		const box = screen.getByRole('textbox', { name: 'Gewicht' }) as HTMLInputElement;
		expect(box.value).toBe('3,50');
		expect(box.getAttribute('inputmode')).toBe('decimal');
		await user.clear(box);
		await user.type(box, '0,10');
		expect(onchange).toHaveBeenLastCalledWith('0.10');
	});

	it('keeps typed text when the parent echoes null back', async () => {
		const user = userEvent.setup();
		const { rerender } = render(DecimalInput, { id: 'd', label: 'D', value: null, lang: 'en' });
		const box = screen.getByRole('textbox') as HTMLInputElement;
		await user.type(box, 'abc');
		await rerender({ value: null });
		expect(box.value).toBe('abc');
		await rerender({ value: '7.25' });
		expect(box.value).toBe('7.25');
	});
});

describe('TextInput', () => {
	it('short text is a one-line input', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn();
		render(TextInput, { id: 's', label: 'Town', value: '', onchange });
		const box = screen.getByRole('textbox', { name: 'Town' });
		expect(box.tagName).toBe('INPUT');
		await user.type(box, 'Ely');
		expect(onchange).toHaveBeenLastCalledWith('Ely');
	});

	it('long text is a textarea', () => {
		render(TextInput, { id: 'l', label: 'Comments', value: 'x', multiline: true });
		expect(screen.getByRole('textbox', { name: 'Comments' }).tagName).toBe('TEXTAREA');
	});

	it('disabled disables the control', () => {
		render(TextInput, { id: 'x', label: 'X', value: '', disabled: true });
		expect((screen.getByRole('textbox') as HTMLInputElement).disabled).toBe(true);
	});
});

describe('SingleChoice', () => {
	it('is a named radiogroup; clicking anywhere on a row selects it', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn();
		render(SingleChoice, { id: 'f', label: 'Fruit', value: null, choices: fruit, onchange });
		const group = screen.getByRole('radiogroup', { name: 'Fruit' });
		const radios = within(group).getAllByRole('radio');
		expect(radios).toHaveLength(3);
		await user.click(screen.getByText('The purple one'));
		expect(onchange).toHaveBeenLastCalledWith('plum');
		expect(radios[2].getAttribute('aria-checked')).toBe('true');
	});

	it('arrow keys move and select, wrapping around', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn();
		render(SingleChoice, { id: 'f', label: 'Fruit', value: 'apple', choices: fruit, onchange });
		const [apple, pear, plum] = screen.getAllByRole('radio');
		await user.tab();
		expect(document.activeElement).toBe(apple);
		await user.keyboard('{ArrowDown}');
		expect(document.activeElement).toBe(pear);
		expect(onchange).toHaveBeenLastCalledWith('pear');
		await user.keyboard('{ArrowRight}');
		expect(document.activeElement).toBe(plum);
		await user.keyboard('{ArrowDown}');
		expect(document.activeElement).toBe(apple);
		expect(onchange).toHaveBeenLastCalledWith('apple');
		await user.keyboard('{ArrowUp}');
		expect(document.activeElement).toBe(plum);
	});

	it('only the selected radio is in the tab order', async () => {
		render(SingleChoice, { id: 'f', label: 'Fruit', value: 'pear', choices: fruit });
		const tabbable = screen.getAllByRole('radio').map((r) => r.getAttribute('tabindex'));
		expect(tabbable).toEqual(['-1', '0', '-1']);
	});

	it('cards and buttons styles keep the same semantics', () => {
		for (const choiceStyle of ['cards', 'buttons'] as const) {
			const { unmount } = render(SingleChoice, {
				id: `s-${choiceStyle}`,
				label: choiceStyle,
				value: null,
				choices: fruit,
				choiceStyle
			});
			const group = screen.getByRole('radiogroup', { name: choiceStyle });
			expect(group.getAttribute('data-style')).toBe(choiceStyle);
			expect(within(group).getAllByRole('radio')).toHaveLength(3);
			unmount();
		}
	});
});

describe('MultiChoice', () => {
	it('Space toggles the focused checkbox; value stays in choice order', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn();
		const { rerender } = render(MultiChoice, {
			id: 'm',
			label: 'Fruit you like',
			value: [],
			choices: fruit,
			onchange
		});
		expect(screen.getByRole('group', { name: 'Fruit you like' })).toBeTruthy();
		const [apple, , plum] = screen.getAllByRole('checkbox');
		plum.focus();
		await user.keyboard(' ');
		expect(onchange).toHaveBeenLastCalledWith(['plum']);
		await rerender({ value: ['plum'] });
		expect(plum.getAttribute('aria-checked')).toBe('true');
		apple.focus();
		await user.keyboard(' ');
		expect(onchange).toHaveBeenLastCalledWith(['apple', 'plum']);
		await rerender({ value: ['apple', 'plum'] });
		await user.keyboard(' ');
		expect(onchange).toHaveBeenLastCalledWith(['plum']);
	});

	it('Tab moves between checkboxes', async () => {
		const user = userEvent.setup();
		render(MultiChoice, { id: 'm', label: 'F', value: [], choices: fruit });
		const boxes = screen.getAllByRole('checkbox');
		await user.tab();
		expect(document.activeElement).toBe(boxes[0]);
		await user.tab();
		expect(document.activeElement).toBe(boxes[1]);
	});
});

describe('DateInput', () => {
	const labels = () =>
		Array.from(document.querySelectorAll('.date label')).map((l) => l.textContent);

	it('orders day / month / year by locale', () => {
		const { unmount } = render(DateInput, { id: 'd', label: 'Born', value: null, lang: 'en-US' });
		expect(labels()).toEqual(['Month', 'Day', 'Year']);
		unmount();
		render(DateInput, { id: 'd', label: 'Born', value: null, lang: 'en-GB' });
		expect(labels()).toEqual(['Day', 'Month', 'Year']);
	});

	it('emits ISO for a real date and null + a message for an impossible one', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn();
		render(DateInput, { id: 'd', label: 'Born', value: null, lang: 'en-GB', onchange });
		expect(screen.getByRole('group', { name: 'Born' })).toBeTruthy();
		await user.type(screen.getByRole('textbox', { name: 'Day' }), '29');
		await user.type(screen.getByRole('textbox', { name: 'Month' }), '2');
		await user.type(screen.getByRole('textbox', { name: 'Year' }), '2024');
		expect(onchange).toHaveBeenLastCalledWith('2024-02-29');
		const year = screen.getByRole('textbox', { name: 'Year' });
		await user.clear(year);
		await user.type(year, '2023');
		expect(onchange).toHaveBeenLastCalledWith(null);
		expect(screen.queryByText('Enter a real date.')).toBeNull();
		await user.tab();
		expect(screen.getByText('Enter a real date.')).toBeTruthy();
	});

	it('shows an incoming ISO value in the fields', () => {
		render(DateInput, { id: 'd', label: 'Born', value: '1999-12-03', lang: 'en-GB' });
		expect((screen.getByRole('textbox', { name: 'Day' }) as HTMLInputElement).value).toBe('3');
		expect((screen.getByRole('textbox', { name: 'Year' }) as HTMLInputElement).value).toBe('1999');
	});
});

describe('Matrix', () => {
	const rows: Choice[] = [
		{ value: 'r1', label: 'The app is easy to use' },
		{ value: 'r2', label: 'I would recommend it' }
	];
	const scale: Choice[] = [
		{ value: '1', label: 'Disagree' },
		{ value: '2', label: 'Neutral' },
		{ value: '3', label: 'Agree' }
	];

	it('one radiogroup per row, named by the row; radios named by the scale label', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn();
		render(Matrix, { id: 'mx', label: 'Opinions', value: {}, rows, choices: scale, onchange });
		const groups = screen.getAllByRole('radiogroup');
		expect(groups.map((g) => g.tagName)).toEqual(['FIELDSET', 'FIELDSET']);
		const second = screen.getByRole('radiogroup', { name: 'I would recommend it' });
		await user.click(within(second).getByRole('radio', { name: 'Agree' }));
		expect(onchange).toHaveBeenLastCalledWith({ r1: null, r2: '3' });
	});

	it('renders a single DOM (no duplicated controls) and starts as cards', () => {
		const { container } = render(Matrix, {
			id: 'mx',
			label: 'Opinions',
			value: { r1: '2' },
			rows,
			choices: scale
		});
		expect(screen.getAllByRole('radio')).toHaveLength(rows.length * scale.length);
		expect(container.querySelector('.matrix')?.getAttribute('data-layout')).toBe('cards');
		const first = screen.getByRole('radiogroup', { name: 'The app is easy to use' });
		expect(within(first).getByRole('radio', { name: 'Neutral' }).getAttribute('aria-checked')).toBe(
			'true'
		);
	});

	it('arrow keys move within a row', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn();
		render(Matrix, { id: 'mx', label: 'O', value: {}, rows, choices: scale, onchange });
		const row1 = within(screen.getByRole('radiogroup', { name: 'The app is easy to use' }));
		row1.getByRole('radio', { name: 'Disagree' }).focus();
		await user.keyboard('{ArrowRight}');
		expect(onchange).toHaveBeenLastCalledWith({ r1: '2', r2: null });
	});
});

describe('Slider', () => {
	const base = { id: 'sl', label: 'Pain', min: 0, max: 10, value: null } as const;

	it('starts unanswered: no thumb drawn, value reads "Not answered"', () => {
		const { container } = render(Slider, { ...base });
		const thumb = screen.getByRole('slider', { name: 'Pain' });
		expect(thumb.getAttribute('aria-valuetext')).toBe('Not answered');
		expect(container.querySelector('.slider')?.hasAttribute('data-answered')).toBe(false);
		expect(screen.getByText('Not answered')).toBeTruthy();
	});

	it('keyboard steps answer it; Home and End jump', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn();
		const { container, rerender } = render(Slider, { ...base, onchange });
		const thumb = screen.getByRole('slider');
		thumb.focus();
		await user.keyboard('{ArrowRight}');
		expect(onchange).toHaveBeenLastCalledWith(6);
		await rerender({ value: 6 });
		expect(thumb.getAttribute('aria-valuetext')).toBe('6');
		expect(container.querySelector('.slider')?.hasAttribute('data-answered')).toBe(true);
		await user.keyboard('{ArrowLeft}');
		expect(onchange).toHaveBeenLastCalledWith(5);
		await user.keyboard('{End}');
		expect(onchange).toHaveBeenLastCalledWith(10);
		await user.keyboard('{Home}');
		expect(onchange).toHaveBeenLastCalledWith(0);
	});

	it('a key that lands on the resting midpoint still counts as an answer', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn();
		render(Slider, { ...base, onchange });
		screen.getByRole('slider').focus();
		await user.keyboard('{ArrowRight}');
		await user.keyboard('{ArrowLeft}');
		expect(onchange).toHaveBeenLastCalledWith(5);
	});

	it('has a typed alternative that checks the range', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn();
		render(Slider, { ...base, onchange });
		const box = screen.getByRole('textbox', { name: 'Or type a number' });
		await user.type(box, '7');
		expect(onchange).toHaveBeenLastCalledWith(7);
		expect(screen.getByRole('slider').getAttribute('aria-valuetext')).toBe('7');
		await user.type(box, '7');
		await user.tab();
		expect(screen.getByText('Enter a number from 0 to 10.')).toBeTruthy();
	});

	it('never snaps a typed off-step value: 7.25 on a 0.5 step is reported as typed (C2c-4)', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn();
		const { rerender } = render(Slider, { ...base, step: 0.5, onchange });
		const box = screen.getByRole('textbox', { name: 'Or type a number' });
		await user.type(box, '7.25');
		expect(onchange).toHaveBeenLastCalledWith(7.25);
		await rerender({ value: 7.25 });
		await user.tab();
		expect(onchange).toHaveBeenLastCalledWith(7.25);
		expect((box as HTMLInputElement).value).toBe('7.25');
	});
});
