<script lang="ts">
	import CardShell from './CardShell.svelte';
	import type { CardProps } from './types';

	/** `note` family: text only. The card's label already is the participant view. */
	let props: CardProps = $props();
</script>

<CardShell {...props} family="note" />
