<script lang="ts">
	import { Slider } from 'bits-ui';
	import { dirFor, fill, formatDecimal, messagesFor, parseDecimal } from './locale';
	import QuestionFrame from './QuestionFrame.svelte';
	import RichText from './RichText.svelte';
	import TextControl from './TextControl.svelte';
	import type { SliderProps } from './types';

	/**
	 * A visual analogue / rating slider (Bits UI Slider) that starts **unanswered**: no thumb
	 * or fill is drawn and the value reads "Not answered" until the participant touches the
	 * track or presses a key on the (still focusable) thumb. The midpoint is never a silent
	 * answer. Arrow keys step, Home/End jump; the current value is always visible; and a
	 * typed number is an alternative to dragging.
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
		onchange,
		min,
		max,
		step = 1,
		minLabel,
		maxLabel
	}: SliderProps = $props();

	const m = $derived(messagesFor(messages));
	// Where Bits keeps the (invisible) thumb before the first touch.
	const resting = $derived(min + Math.round((max - min) / 2 / step) * step);
	// What the track shows: follows `value`, and updates at once while dragging.
	let shown = $derived<number | null>(value ?? null);

	const numberFormat = $derived(new Intl.NumberFormat(lang, { maximumFractionDigits: 6 }));
	const valueText = $derived(shown === null ? m.notAnswered : numberFormat.format(shown));

	/**
	 * The nearest step on the track (what Bits can draw). A typed value off the step grid is
	 * never snapped silently (semantics C2c-4): it is reported as typed, the engine refuses it
	 * (`value.off_step`) and the participant sees the error; only the thumb is drawn at the
	 * nearest step meanwhile.
	 */
	function snap(x: number): number {
		const k = Math.round((x - min) / step);
		const v = Math.min(max, Math.max(min, min + k * step));
		return Number(v.toFixed(10));
	}
	const trackValue = $derived(shown === null ? resting : snap(shown));

	function fromTrack(v: number) {
		// Bits echoing the snapped position of a typed off-step value is not an answer.
		if (shown !== null && v !== shown && v === snap(shown)) return;
		emit(v);
	}

	function emit(v: number) {
		shown = v;
		typed = null;
		if (v !== value) onchange?.(v);
	}

	// Typed alternative. `typed` holds the text while it is being edited.
	let typed = $state<string | null>(null);
	let typedTouched = $state(false);
	const typedText = $derived(typed ?? (shown === null ? '' : formatDecimal(String(shown), lang)));
	const typedError = $derived.by(() => {
		if (typed === null) return null;
		const p = parseDecimal(typed, lang);
		if (p === null) return null;
		const n = p === undefined ? NaN : Number(p);
		return Number.isFinite(n) && n >= min && n <= max ? null : fill(m.outOfRange, { min, max });
	});
	const shownError = $derived(error || (typedTouched ? typedError : null));

	function onTyped(text: string) {
		typed = text;
		if (typedError === null) typedTouched = false;
		const p = parseDecimal(text, lang);
		if (p === null) {
			shown = null;
			if (value !== null) onchange?.(null);
			return;
		}
		if (p === undefined || typedError) return;
		const n = Number(p);
		shown = n;
		if (n !== value) onchange?.(n);
	}
</script>

<QuestionFrame {id} {label} {help} {required} error={shownError} {disabled} {lang} {revealed} {messages} kind="fieldset">
	{#snippet children(ctx)}
		<div class="slider" data-answered={shown === null ? undefined : ''}>
			<p class="current" id="{id}-value">
				<span class="current-label">{m.sliderValue}:</span>
				<strong>{valueText}</strong>
			</p>
			<div class="track-wrap">
				<Slider.Root
					type="single"
					class="osp-slider-root"
					value={trackValue}
					{min}
					{max}
					{step}
					dir={dirFor(lang)}
					{disabled}
					onValueChange={(v) => fromTrack(v)}
					onValueCommit={(v) => {
						if (shown === null) emit(v);
					}}
				>
					<span class="osp-slider-track"><Slider.Range class="osp-slider-range" /></span>
					<Slider.Thumb
						index={0}
						class="osp-slider-thumb"
						aria-labelledby={ctx.labelId}
						aria-describedby="{id}-value"
						aria-valuetext={valueText}
						aria-invalid={ctx.invalid ? 'true' : undefined}
					/>
				</Slider.Root>
			</div>
			<div class="ends" aria-hidden="true">
				<span><RichText text={minLabel ?? numberFormat.format(min)} /></span>
				<span><RichText text={maxLabel ?? numberFormat.format(max)} /></span>
			</div>
			<div class="typed">
				<label for="{id}-typed">{m.sliderTypeValue}</label>
				<TextControl
					id="{id}-typed"
					value={typedText}
					chars={Math.max(String(min).length, String(max).length) + 2}
					invalid={ctx.invalid}
					inputmode={min < 0 ? 'text' : 'decimal'}
					enterkeyhint="next"
					autocomplete="off"
					{disabled}
					oninput={onTyped}
					onblur={() => {
						typedTouched = true;
						if (!typedError) typed = null;
					}}
				/>
			</div>
		</div>
	{/snippet}
</QuestionFrame>

<style>
	.slider {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.current {
		margin: 0;
	}
	.current-label {
		color: var(--color-text-muted);
	}
	.track-wrap {
		/* Room for half a thumb at each end, so the thumb never overflows the column. */
		padding-inline: calc(var(--survey-target-size) / 2);
	}
	.track-wrap :global(.osp-slider-root) {
		position: relative;
		display: block;
		block-size: var(--survey-target-size);
		touch-action: none;
		cursor: pointer;
	}
	.track-wrap :global(.osp-slider-root[data-disabled]) {
		cursor: not-allowed;
	}
	.osp-slider-track {
		position: absolute;
		inset-inline: 0;
		inset-block-start: calc(50% - var(--survey-track-size) / 2);
		block-size: var(--survey-track-size);
		border-radius: var(--radius-full);
		background: var(--color-border-strong);
	}
	.track-wrap :global(.osp-slider-range) {
		block-size: 100%;
		border-radius: var(--radius-full);
		background: var(--color-accent);
	}
	/* The thumb's box is the touch target; the visible knob is drawn inside it. */
	.track-wrap :global(.osp-slider-thumb) {
		inset-block-start: 0;
		display: grid;
		place-items: center;
		inline-size: var(--survey-target-size);
		block-size: var(--survey-target-size);
		border-radius: var(--radius-full);
		cursor: grab;
	}
	.track-wrap :global(.osp-slider-thumb)::after {
		content: '';
		inline-size: var(--survey-thumb-size);
		block-size: var(--survey-thumb-size);
		border: 2px solid var(--color-accent);
		border-radius: var(--radius-full);
		background: var(--color-surface-raised);
		box-shadow: var(--shadow-sm);
	}
	.track-wrap :global(.osp-slider-root[data-disabled] .osp-slider-range) {
		background: var(--color-text-muted);
	}
	.track-wrap :global(.osp-slider-root[data-disabled] .osp-slider-thumb) {
		cursor: not-allowed;
	}
	.track-wrap :global(.osp-slider-root[data-disabled] .osp-slider-thumb)::after {
		border-color: var(--color-text-muted);
		background: var(--color-surface-sunken);
		box-shadow: none;
	}
	.track-wrap :global(.osp-slider-thumb:focus-visible) {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 0;
	}
	/* Unanswered: no thumb and no fill, but the thumb stays focusable for keyboards. */
	.slider:not([data-answered]) :global(.osp-slider-range),
	.slider:not([data-answered]) :global(.osp-slider-thumb)::after {
		visibility: hidden;
	}
	.slider:not([data-answered]) :global(.osp-slider-thumb:focus-visible) {
		outline-style: dashed;
	}
	.ends {
		display: flex;
		justify-content: space-between;
		gap: var(--space-3);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.ends span:last-child {
		text-align: end;
	}
	.typed {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-3);
	}
	.typed label {
		color: var(--color-text-muted);
	}
</style>
