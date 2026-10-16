<script lang="ts">
	import { Button, Dialog } from '@osp/ui-components';
	import type { ComponentProps } from 'svelte';
	import ChoiceListEditor from './ChoiceListEditor.svelte';
	import { labelIn } from './model';

	/**
	 * The choice list editor in a modal, opened from the property panel's "Edit choices…".
	 * Takes the editor's props plus a bindable `open`. Edits are sent as they happen, so
	 * "Done" only closes.
	 */
	type Props = ComponentProps<typeof ChoiceListEditor> & { open?: boolean };
	let { open = $bindable(false), ...editor }: Props = $props();

	const description = $derived(
		labelIn(editor.question.label, editor.lang ?? editor.defaultLanguage) || editor.question.id
	);
</script>

<Dialog bind:open title="Edit choices" {description} size="lg" placement="top">
	<ChoiceListEditor {...editor} />
	{#snippet footer()}
		<Button variant="primary" onclick={() => (open = false)}>Done</Button>
	{/snippet}
</Dialog>
