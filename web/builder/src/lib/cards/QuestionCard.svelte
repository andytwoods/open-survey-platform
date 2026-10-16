<script lang="ts">
	import CardShell from './CardShell.svelte';
	import { cardFor } from './dispatch';
	import { resolveFamily } from './logic';
	import type { CardProps } from './types';

	/**
	 * Picks the card for a question by family: the `family` prop, else the property schema's
	 * `family`, else the question type. An unknown family still gets a card (label, badges,
	 * a "no preview" notice) so it can be selected and fixed.
	 */
	let props: CardProps = $props();

	const family = $derived(resolveFamily(props.family, props.schema, props.question));
	const Card = $derived(cardFor(family));
</script>

{#if Card}
	<Card {...props} {family} />
{:else}
	<CardShell
		{...props}
		family={null}
		notice="No preview for question type “{String(props.question?.type ?? 'unknown')}”"
	/>
{/if}
