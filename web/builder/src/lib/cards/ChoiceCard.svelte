<script lang="ts">
	import { MultiChoice, SingleChoice } from '@osp/ui-components/survey';
	import CardShell from './CardShell.svelte';
	import { choicesFor, textFor } from './logic';
	import type { CardProps } from './types';

	/** `choice` family: single (radios) or multi (checkboxes), inline or shared choices. */
	let props: CardProps = $props();
	const question = $derived(props.question);
	const lang = $derived(props.lang ?? 'en');

	const label = $derived(textFor(question.label, lang));
	const resolved = $derived(choicesFor(question, props.choiceLists, lang));
	const notice = $derived.by(() => {
		if (resolved.choices.length) return undefined;
		if (resolved.sharedList) return `Choices from shared list "${resolved.sharedList}"`;
		return 'No choices yet';
	});
</script>

<CardShell {...props} family="choice" {notice}>
	{#snippet preview(id)}
		{#if question.type === 'multi'}
			<MultiChoice {id} {label} value={[]} choices={resolved.choices} />
		{:else}
			<SingleChoice {id} {label} value={null} choices={resolved.choices} />
		{/if}
	{/snippet}
</CardShell>
