<script lang="ts">
	import { Matrix } from '@osp/ui-components/survey';
	import CardShell from './CardShell.svelte';
	import { choicesFor, rowsFor, textFor } from './logic';
	import type { CardProps } from './types';

	/** `matrix` family: rows of sub-questions sharing one scale (columns = choices). */
	let props: CardProps = $props();
	const question = $derived(props.question);
	const lang = $derived(props.lang ?? 'en');

	const label = $derived(textFor(question.label, lang));
	const rows = $derived(rowsFor(question, lang));
	const columns = $derived(choicesFor(question, props.choiceLists, lang).choices);
	const notice = $derived(rows.length && columns.length ? undefined : 'No rows or columns yet');
</script>

<CardShell {...props} family="matrix" {notice}>
	{#snippet preview(id)}
		<Matrix {id} {label} value={{}} {rows} choices={columns} />
	{/snippet}
</CardShell>
