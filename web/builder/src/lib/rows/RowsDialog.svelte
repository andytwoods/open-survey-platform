<script lang="ts">
	import { Button, Dialog } from '@osp/ui-components';
	import type { ComponentProps } from 'svelte';
	import { labelIn } from '../choices/model';
	import RowsEditor from './RowsEditor.svelte';

	/**
	 * The rows editor in a modal, opened from the property panel's "Edit rows…" (like the
	 * choices editor). Edits are sent as they happen, so "Done" only closes.
	 */
	type Props = ComponentProps<typeof RowsEditor> & { open?: boolean };
	let { open = $bindable(false), ...editor }: Props = $props();

	const description = $derived(
		labelIn(editor.question.label, editor.lang ?? editor.defaultLanguage) || editor.question.id
	);
</script>

<Dialog bind:open title="Edit rows" {description} size="lg" placement="top">
	<RowsEditor {...editor} />
	{#snippet footer()}
		<Button variant="primary" onclick={() => (open = false)}>Done</Button>
	{/snippet}
</Dialog>
