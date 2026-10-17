<script lang="ts">
	import type { ViewItem } from '@osp/engine';
	import {
		DateInput,
		DecimalInput,
		IntegerInput,
		Matrix,
		MultiChoice,
		Note,
		SingleChoice,
		Slider,
		TextInput
	} from '@osp/ui-components/survey';
	import { choicesOf, domId, errorText, segs, widgetValue } from './view-map';

	/** One engine ViewItem → one R5 widget. No logic: the engine decided all of it. */
	type Props = {
		item: ViewItem;
		lang: string;
		revealed: boolean;
		/**
		 * What was typed (the engine stores text trimmed and decimals canonical, `0.10` → `0.1`;
		 * the box must not jump while typing, R6-2).
		 */
		draft: string | undefined;
		/** Long text: a multi-line field that keeps line breaks (plan item `multiline`). */
		multiline?: boolean;
		onanswer: (id: string, value: unknown) => void;
	};
	let { item, lang, revealed, draft, multiline = false, onanswer }: Props = $props();

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

	// Matrix (semantics §2, C2c-1): each row is its own question. The widget reports the
	// whole grid; answer only the rows that changed, by their row ids.
	const rows = $derived((item.rows ?? []).map((r) => ({ value: r.id, label: segs(r.label) })));
	const grid = $derived(
		Object.fromEntries((item.rows ?? []).map((r) => [r.id, r.value === null ? null : String(r.value)]))
	);
	function setRows(next: Record<string, string | null>) {
		for (const r of item.rows ?? []) {
			const v = next[r.id] ?? null;
			if (v !== grid[r.id]) onanswer(r.id, v);
		}
	}

	// Slider (C2c-3): starts unanswered; the engine checks range and step.
	const track = $derived(item.slider);
	const sliderValue = $derived(item.value === null || item.value === undefined ? null : Number(item.value));
</script>

{#if item.type === 'integer'}
	<IntegerInput {...base} value={draft ?? (widgetValue(item) as string | null)} onchange={set} />
{:else if item.type === 'decimal'}
	<DecimalInput {...base} value={draft ?? (widgetValue(item) as string | null)} onchange={set} />
{:else if item.type === 'text'}
	<TextInput {...base} {multiline} value={draft ?? (widgetValue(item) as string)} onchange={set} />
{:else if item.type === 'single'}
	<SingleChoice {...base} choices={choicesOf(item)} value={widgetValue(item) as string | null} onchange={set} />
{:else if item.type === 'multi'}
	<MultiChoice {...base} choices={choicesOf(item)} value={widgetValue(item) as string[]} onchange={set} />
{:else if item.type === 'date'}
	<DateInput {...base} value={widgetValue(item) as string | null} onchange={set} />
{:else if item.type === 'matrix'}
	<Matrix {...base} {rows} choices={choicesOf(item)} value={grid} onchange={setRows} />
{:else if item.type === 'slider' && track}
	<Slider
		{...base}
		min={Number(track.min)}
		max={Number(track.max)}
		step={Number(track.step)}
		minLabel={track.minLabel ? segs(track.minLabel) : undefined}
		maxLabel={track.maxLabel ? segs(track.maxLabel) : undefined}
		value={sliderValue}
		onchange={set}
	/>
{:else if item.type === 'note'}
	<Note id={base.id} label={base.label} help={base.help} {lang} {revealed} />
{/if}
