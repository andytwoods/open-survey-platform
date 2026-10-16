<script lang="ts">
	import { checkDate, dateOrder, isoToFields, messagesFor, type DateFields, type DatePart } from './locale';
	import QuestionFrame from './QuestionFrame.svelte';
	import TextControl from './TextControl.svelte';
	import type { DateInputProps } from './types';

	/**
	 * Date as three labelled number fields in the participant's locale order (en-GB: day,
	 * month, year; en-US: month, day, year). No native picker (§6). Strict: a 4-digit year
	 * and a date that exists. Emits ISO "YYYY-MM-DD", or null while incomplete or invalid;
	 * the format message shows once focus leaves the three fields.
	 */
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
		onchange
	}: DateInputProps = $props();

	const m = $derived(messagesFor(messages));
	const order = $derived(dateOrder(lang));
	const chars: Record<DatePart, number> = { day: 2, month: 2, year: 4 };

	let fields = $state<DateFields>({ day: '', month: '', year: '' });
	let touched = $state(false);
	const NONE = Symbol('none');
	let emitted: string | null | typeof NONE = NONE;

	$effect.pre(() => {
		const v = value ?? null;
		if (v !== emitted) {
			fields = isoToFields(v);
			emitted = v;
		}
	});

	const check = $derived(checkDate(fields));
	const formatError = $derived(
		check.kind === 'incomplete' ? m.incompleteDate : check.kind === 'invalid' ? m.invalidDate : null
	);
	const shownError = $derived(error || (touched ? formatError : null));

	function onInput(part: DatePart, text: string) {
		fields = { ...fields, [part]: text };
		if (formatError === null) touched = false;
		const v = check.kind === 'valid' ? check.iso : null;
		if (v !== emitted) {
			emitted = v;
			onchange?.(v);
		}
	}

	function onFocusOut(e: FocusEvent) {
		const group = e.currentTarget as HTMLElement;
		if (!group.contains(e.relatedTarget as Node | null)) touched = true;
	}
</script>

<QuestionFrame {id} {label} {help} {required} error={shownError} {disabled} {lang} {revealed} {messages} kind="fieldset">
	{#snippet children(ctx)}
		<div class="date" onfocusout={onFocusOut}>
			{#each order as part (part)}
				<div class="part">
					<label for="{id}-{part}">{m[part]}</label>
					<TextControl
						id="{id}-{part}"
						value={fields[part]}
						chars={chars[part]}
						invalid={ctx.invalid}
						inputmode="numeric"
						enterkeyhint="next"
						autocomplete="off"
						maxlength={chars[part]}
						{disabled}
						oninput={(t) => onInput(part, t)}
					/>
				</div>
			{/each}
		</div>
	{/snippet}
</QuestionFrame>

<style>
	.date {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
	}
	.part {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	label {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
</style>
