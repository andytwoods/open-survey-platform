<script lang="ts">
	import { RadioGroup } from 'bits-ui';
	import './choices.css';
	import { safeId } from './locale';
	import { arrowSelect } from './radio-arrows';
	import QuestionFrame from './QuestionFrame.svelte';
	import RichText from './RichText.svelte';
	import type { SingleChoiceProps } from './types';

	/**
	 * One answer from a list (Bits UI RadioGroup): arrow keys move and select, Tab leaves
	 * the group. Each whole row is the radio, so the full row is the hit area.
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
		choices,
		choiceStyle = 'list'
	}: SingleChoiceProps = $props();

	// Bits holds the selection; it follows `value` and reports changes through onchange.
	let current = $state('');
	$effect.pre(() => {
		current = value ?? '';
	});

	function select(v: string) {
		current = v;
		onchange?.(v === '' ? null : v);
	}
	const arrows = arrowSelect(() => current === '', select);
</script>

<QuestionFrame {id} {label} {help} {required} {error} {disabled} {lang} {revealed} {messages} kind="group">
	{#snippet children(ctx)}
		<RadioGroup.Root
			class="osp-choices"
			data-style={choiceStyle}
			orientation={choiceStyle === 'buttons' ? 'horizontal' : 'vertical'}
			bind:value={current}
			onValueChange={(v) => onchange?.(v === '' ? null : v)}
			{disabled}
			aria-labelledby={ctx.labelId}
			aria-describedby={ctx.describedBy}
			aria-invalid={ctx.invalid ? 'true' : undefined}
		>
			{#each choices as choice (choice.value)}
				<RadioGroup.Item
					id="{id}-c-{safeId(choice.value)}"
					class="osp-choice"
					value={choice.value}
					disabled={choice.disabled}
					onkeydown={arrows.onkeydown}
					onfocus={() => arrows.onfocus(choice.value)}
				>
					<span class="osp-choice-ind" data-kind="radio" aria-hidden="true"></span>
					<span class="osp-choice-text">
						<span class="osp-choice-label"><RichText text={choice.label} /></span>
						{#if choice.help}<span class="osp-choice-help"><RichText text={choice.help} /></span>{/if}
					</span>
				</RadioGroup.Item>
			{/each}
		</RadioGroup.Root>
	{/snippet}
</QuestionFrame>
