<script lang="ts">
	import { DateInput, TextInput } from '@osp/ui-components/survey';
	import CardShell from './CardShell.svelte';
	import { textFor } from './logic';
	import type { CardProps } from './types';

	/** `text` family: free text (short or long) and dates. */
	let props: CardProps = $props();
	const question = $derived(props.question);
	const lang = $derived(props.lang ?? 'en');

	const label = $derived(textFor(question.label, lang));
</script>

<CardShell {...props} family="text">
	{#snippet preview(id)}
		{#if question.type === 'date'}
			<DateInput {id} {label} value={null} {lang} />
		{:else}
			<TextInput {id} {label} value="" multiline={question.multiline === true} />
		{/if}
	{/snippet}
</CardShell>
