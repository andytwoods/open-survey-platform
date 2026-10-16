<script lang="ts">
	import type { ViewItem } from '@osp/engine';
	import {
		DateInput,
		DecimalInput,
		IntegerInput,
		MultiChoice,
		Note,
		SingleChoice,
		TextInput
	} from '@osp/ui-components/survey';
	import { choicesOf, domId, errorText, segs, widgetValue } from './view-map';

	/** One engine ViewItem → one R5 widget. No logic: the engine decided all of it. */
	type Props = {
		item: ViewItem;
		lang: string;
		revealed: boolean;
		/** Text as typed (the engine stores it trimmed; the box must not jump while typing). */
		draft: string | undefined;
		onanswer: (id: string, value: unknown) => void;
	};
	let { item, lang, revealed, draft, onanswer }: Props = $props();

	const base = $derived({
		id: domId(item.id),
		label: segs(item.label),
		help: item.help ? segs(item.help) : undefined,
		required: item.required,
		error: errorText(item),
		lang,
		revealed
	});
	const set = (v: unknown) => onanswer(item.id, v);
</script>

{#if item.type === 'integer'}
	<IntegerInput {...base} value={widgetValue(item) as string | null} onchange={set} />
{:else if item.type === 'decimal'}
	<DecimalInput {...base} value={widgetValue(item) as string | null} onchange={set} />
{:else if item.type === 'text'}
	<TextInput {...base} value={draft ?? (widgetValue(item) as string)} onchange={set} />
{:else if item.type === 'single'}
	<SingleChoice {...base} choices={choicesOf(item)} value={widgetValue(item) as string | null} onchange={set} />
{:else if item.type === 'multi'}
	<MultiChoice {...base} choices={choicesOf(item)} value={widgetValue(item) as string[]} onchange={set} />
{:else if item.type === 'date'}
	<DateInput {...base} value={widgetValue(item) as string | null} onchange={set} />
{:else if item.type === 'note'}
	<Note id={base.id} label={base.label} help={base.help} {lang} {revealed} />
{/if}
