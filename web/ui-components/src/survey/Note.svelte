<script lang="ts">
	import QuestionFrame from './QuestionFrame.svelte';
	import type { NoteProps } from './types';

	/** Text shown to the participant, with no answer. */
	let { id, label, help, disabled = false, lang, revealed = false, messages }: NoteProps = $props();
</script>

<QuestionFrame {id} {label} {help} {disabled} {lang} {revealed} {messages} kind="note" />
