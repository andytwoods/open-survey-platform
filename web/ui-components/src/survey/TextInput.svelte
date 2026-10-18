<script lang="ts">
	import QuestionFrame from './QuestionFrame.svelte';
	import TextControl from './TextControl.svelte';
	import type { TextInputProps } from './types';

	/** Short text (one line) or long text (`multiline`: a textarea that grows as you type). */
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
		multiline = false,
		maxLength,
		autocomplete = 'off'
	}: TextInputProps = $props();
</script>

<QuestionFrame {id} {label} {help} {required} {error} {disabled} {lang} {revealed} {messages}>
	{#snippet children(ctx)}
		<TextControl
			id={ctx.controlId}
			value={value ?? ''}
			{multiline}
			invalid={ctx.invalid}
			aria-labelledby={ctx.labelledBy}
			aria-describedby={ctx.describedBy}
			maxlength={maxLength}
			enterkeyhint={multiline ? undefined : 'next'}
			autocomplete={autocomplete as never}
			{disabled}
			rows={multiline ? 3 : undefined}
			oninput={(v) => onchange?.(v)}
		/>
	{/snippet}
</QuestionFrame>
