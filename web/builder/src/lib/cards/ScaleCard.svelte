<script lang="ts">
	import { Slider } from '@osp/ui-components/survey';
	import CardShell from './CardShell.svelte';
	import { scaleRange, textFor } from './logic';
	import type { CardProps } from './types';

	/** `scale` family: a slider that starts unanswered. */
	let props: CardProps = $props();
	const question = $derived(props.question);
	const lang = $derived(props.lang ?? 'en');

	const label = $derived(textFor(question.label, lang));
	const range = $derived(scaleRange(question));
	const minLabel = $derived(textFor(question.minLabel, lang) || undefined);
	const maxLabel = $derived(textFor(question.maxLabel, lang) || undefined);
</script>

<CardShell {...props} family="scale">
	{#snippet preview(id)}
		<Slider {id} {label} value={null} {...range} {minLabel} {maxLabel} {lang} />
	{/snippet}
</CardShell>
