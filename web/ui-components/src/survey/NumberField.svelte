<script lang="ts">
	import { decimalSeparator, fill, formatDecimal, messagesFor, parseDecimal, parseInteger } from './locale';
	import QuestionFrame from './QuestionFrame.svelte';
	import TextControl from './TextControl.svelte';
	import type { QuestionProps } from './types';

	/**
	 * Shared body of IntegerInput and DecimalInput (internal). The participant's text is
	 * kept as typed; the emitted value is the canonical string, or null when empty or not a
	 * number (a format message then shows after the field loses focus).
	 */
	type Props = QuestionProps<string | null> & { mode: 'integer' | 'decimal'; min?: number };

	let {
		id,
		label,
		help,
		required = false,
		value,
		error,
		disabled = false,
		lang,
		revealed = false,
		messages,
		onchange,
		mode,
		min
	}: Props = $props();

	const m = $derived(messagesFor(messages));
	const parse = (s: string) => (mode === 'integer' ? parseInteger(s) : parseDecimal(s, lang));
	const format = (v: string | null) => (mode === 'integer' ? (v ?? '') : formatDecimal(v, lang));

	let text = $state('');
	let touched = $state(false);
	// The value we last reported. A different incoming value replaces the text box.
	const NONE = Symbol('none');
	let emitted: string | null | typeof NONE = NONE;

	$effect.pre(() => {
		const v = value ?? null;
		if (v !== emitted) {
			text = format(v);
			emitted = v;
		}
	});

	const parsed = $derived(parse(text));
	const formatError = $derived.by(() => {
		if (parsed !== undefined) return null;
		if (mode === 'integer') return m.invalidInteger;
		return fill(m.invalidDecimal, { example: `12${decimalSeparator(lang)}5` });
	});
	const shownError = $derived(error || (touched ? formatError : null));
	const negative = $derived(min !== undefined && min < 0);
	const inputmode = $derived(negative ? 'text' : mode === 'integer' ? 'numeric' : 'decimal');

	function onInput(next: string) {
		text = next;
		if (formatError === null) touched = false;
		const v = parse(next) ?? null;
		if (v !== emitted) {
			emitted = v;
			onchange?.(v);
		}
	}
</script>

<QuestionFrame {id} {label} {help} {required} error={shownError} {disabled} {lang} {revealed} {messages}>
	{#snippet children(ctx)}
		<TextControl
			id={ctx.controlId}
			value={text}
			chars={mode === 'integer' ? 10 : 12}
			invalid={ctx.invalid}
			aria-labelledby={ctx.labelledBy}
			aria-describedby={ctx.describedBy}
			{inputmode}
			enterkeyhint="next"
			autocomplete="off"
			spellcheck={false}
			{disabled}
			oninput={onInput}
			onblur={() => (touched = true)}
		/>
	{/snippet}
</QuestionFrame>
