<script lang="ts">
	import { DecimalInput, IntegerInput } from '@osp/ui-components/survey';
	import CardShell from './CardShell.svelte';
	import { textFor } from './logic';
	import type { CardProps } from './types';

	/** `number` family: integer and decimal inputs. */
	let props: CardProps = $props();
	const question = $derived(props.question);
	const lang = $derived(props.lang ?? 'en');

	const label = $derived(textFor(question.label, lang));
</script>

<CardShell {...props} family="number">
	{#snippet preview(id)}
		{#if question.type === 'decimal'}
			<DecimalInput {id} {label} value={null} {lang} />
		{:else}
			<IntegerInput {id} {label} value={null} {lang} />
		{/if}
	{/snippet}
</CardShell>
