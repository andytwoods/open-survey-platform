<script lang="ts">
	import { Input } from '@osp/ui-components';
	import { onDestroy, untrack } from 'svelte';
	import type { SurveyStore } from '../sync/survey-store.svelte';
	import { TextBuffer } from '../sync/text-buffer';

	/**
	 * A text field over a local buffer: typing never round-trips; the value is sent
	 * (one transaction via `commit`) after a pause or on blur. While you are typing, a
	 * patch from the server doesn't overwrite your text or move focus.
	 */
	let {
		label,
		value,
		store,
		commit,
		description
	}: {
		label: string;
		/** The model's current value. */
		value: string;
		store: SurveyStore;
		/** Build and submit the edit for the new text. */
		commit: (text: string) => Promise<unknown> | void;
		description?: string;
	} = $props();

	let text = $state(untrack(() => value));
	let focused = $state(false);

	// Once the server has answered, show the model's value (the edit, or the old text if
	// it was rejected), unless the user has started typing again.
	// Bound once: a flush on teardown (selection moved on) must use this field's commit.
	const send = untrack(() => commit);
	const owner = untrack(() => store);
	const buffer = new TextBuffer(
		(v) =>
			void Promise.resolve(send(v)).then(() => {
				if (!focused && !buffer.dirty) text = value;
			}),
		{ onDirty: (d) => owner.markDirty(d) }
	);
	const off = owner.registerBuffer(buffer);
	onDestroy(() => {
		buffer.flush();
		off();
	});

	// Follow the model (undo, someone else's edit) unless the user is mid-edit.
	$effect(() => {
		const v = value;
		if (!untrack(() => focused || buffer.dirty)) text = v;
	});

	function oninput() {
		buffer.input(text);
	}
	function onblur() {
		focused = false;
		buffer.flush();
	}
</script>

<Input
	{label}
	{description}
	bind:value={text}
	{oninput}
	onfocus={() => (focused = true)}
	{onblur}
	onkeydown={(e: KeyboardEvent) => {
		if (e.key === 'Enter') buffer.flush();
	}}
/>
