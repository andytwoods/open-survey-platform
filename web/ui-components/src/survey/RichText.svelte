<script lang="ts">
	import type { Text } from './types';

	/**
	 * Renders display text as text nodes. Segments are already escaped by the engine; this
	 * component never uses {@html}, so participant-piped values cannot inject markup.
	 */
	let { text }: { text: Text | undefined } = $props();
</script>

{#if typeof text === 'string'}{text}{:else if text}{#each text as seg, i (i)}{#if seg.strong && seg.em}<strong
				lang={seg.lang}><em>{seg.text}</em></strong
			>{:else if seg.strong}<strong lang={seg.lang}>{seg.text}</strong>{:else if seg.em}<em
				lang={seg.lang}>{seg.text}</em
			>{:else if seg.lang}<span lang={seg.lang}>{seg.text}</span>{:else}{seg.text}{/if}{/each}{/if}
