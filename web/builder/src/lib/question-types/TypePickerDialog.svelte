<script lang="ts">
	import { Dialog } from '@osp/ui-components';
	import { orderTypes, type QuestionTypeId } from './catalogue';
	import TypePicker from './TypePicker.svelte';

	/**
	 * The type picker in a modal: "Add a question" (the last used type first) or "Change
	 * question type" (the current one marked). `onchoose` runs after the dialog has closed.
	 * Escape, × or a click outside cancel, and focus goes back to whatever opened it; after
	 * adding, the caller moves focus on (to the new question's text) instead.
	 */
	let {
		open = $bindable(false),
		mode,
		current,
		lastUsed = null,
		returnFocusId = null,
		onchoose
	}: {
		open?: boolean;
		mode: 'add' | 'change';
		current?: QuestionTypeId;
		lastUsed?: QuestionTypeId | null;
		/** Where focus goes when the picker is cancelled (the opener, by id). */
		returnFocusId?: string | null;
		onchoose: (id: QuestionTypeId) => void;
	} = $props();

	const types = $derived(orderTypes(mode === 'add' ? lastUsed : null));
	let chosen: QuestionTypeId | null = null;

	function choose(id: QuestionTypeId) {
		chosen = id;
		open = false;
	}

	function onCloseAutoFocus(e: Event) {
		const id = chosen;
		chosen = null;
		if (!id) {
			// By id: the pane may redraw the opener while the picker is open, and the dialog's
			// own focus return would then land on a detached button.
			if (!returnFocusId) return;
			e.preventDefault();
			// After the focus trap has let go (focusing inside it now would be undone).
			const target = returnFocusId;
			setTimeout(() => document.getElementById(target)?.focus(), 0);
			return;
		}
		// Adding moves focus to the new question; changing returns it to the opener.
		if (mode === 'add') e.preventDefault();
		setTimeout(() => onchoose(id), 0);
	}
</script>

<Dialog
	bind:open
	title={mode === 'add' ? 'Add a question' : 'Change question type'}
	description={mode === 'add'
		? 'Choose what kind of answer participants give.'
		: 'The question keeps its text, help, variable name and display conditions.'}
	size="md"
	placement="top"
	{onCloseAutoFocus}
>
	{#if open}
		<TypePicker
			{types}
			{current}
			lastUsed={mode === 'add' ? lastUsed : null}
			label="Question types"
			onchoose={choose}
		/>
	{/if}
</Dialog>
