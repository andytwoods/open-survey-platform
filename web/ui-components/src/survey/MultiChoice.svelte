<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import { Checkbox } from 'bits-ui';
	import './choices.css';
	import { safeId } from './locale';
	import QuestionFrame from './QuestionFrame.svelte';
	import RichText from './RichText.svelte';
	import type { MultiChoiceProps } from './types';

	/**
	 * Any number of answers (Bits UI Checkbox per row, inside a fieldset). Space toggles the
	 * focused row; Tab moves between rows. The value lists choices in choice order.
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
	}: MultiChoiceProps = $props();

	const selected = $derived(new Set(value ?? []));

	function toggle(choice: string, on: boolean) {
		const next = new Set(selected);
		if (on) next.add(choice);
		else next.delete(choice);
		onchange?.(choices.map((c) => c.value).filter((v) => next.has(v)));
	}
</script>

<QuestionFrame {id} {label} {help} {required} {error} {disabled} {lang} {revealed} {messages} kind="fieldset">
	{#snippet children(ctx)}
		<div class="osp-choices" data-style={choiceStyle}>
			{#each choices as choice (choice.value)}
				<Checkbox.Root
					id="{id}-c-{safeId(choice.value)}"
					class="osp-choice"
					checked={selected.has(choice.value)}
					onCheckedChange={(on) => toggle(choice.value, on)}
					disabled={disabled || choice.disabled}
					aria-invalid={ctx.invalid ? 'true' : undefined}
				>
					{#snippet children({ checked })}
						<span class="osp-choice-ind" data-kind="checkbox" aria-hidden="true">
							{#if checked}<Check strokeWidth={3} />{/if}
						</span>
						<span class="osp-choice-text">
							<span class="osp-choice-label"><RichText text={choice.label} /></span>
							{#if choice.help}<span class="osp-choice-help"><RichText text={choice.help} /></span>{/if}
						</span>
					{/snippet}
				</Checkbox.Root>
			{/each}
		</div>
	{/snippet}
</QuestionFrame>
