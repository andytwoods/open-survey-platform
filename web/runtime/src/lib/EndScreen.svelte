<script lang="ts">
	/**
	 * The ending screen (end-of-survey plan §4.1, task EN1): the outcome's ending from the
	 * engine's view (`view.end`) with its pipes filled. The heading is the ending's title or
	 * the app's own "Thank you"; the end node's message comes first, then the ending's body,
	 * then the app's truthful status line, which researcher text never replaces. Everything
	 * is rendered as text nodes (RichText), never as HTML, so piped answers cannot inject
	 * markup.
	 */
	import { RichText } from '@osp/ui-components/survey';
	import type { EndView } from '@osp/engine';
	import { ui } from './messages';
	import { paragraphs, segs } from './view-map';

	let {
		end,
		testid,
		fallbackBody = null,
		heading = $bindable(null)
	}: {
		end: EndView | null;
		/** `thanks` after a submit, `declined` after a consent decline (harness, e2e). */
		testid: string;
		/** App text shown when the ending sets no body (the decline's own sentence). */
		fallbackBody?: string | null;
		heading?: HTMLElement | null;
	} = $props();

	const title = $derived(end?.ending?.title?.length ? end.ending.title : null);
	const message = $derived(paragraphs(end?.message));
	const body = $derived(paragraphs(end?.ending?.body));
	const status = $derived(end ? end.status : 'recorded');
	const statusText = $derived(status === 'not-recorded' ? ui.notRecorded : status === 'recorded' ? ui.thanks : '');
</script>

<h1 tabindex="-1" bind:this={heading} data-testid={testid} data-default={title ? undefined : ''}>
	{#if title}<RichText text={segs(title)} />{:else}{ui.thanksTitle}{/if}
</h1>
{#if message.length}
	<div class="ending-text" data-ending="message">
		{#each message as p, i (i)}<p><RichText text={segs(p)} /></p>{/each}
	</div>
{/if}
{#if body.length}
	<div class="ending-text" data-ending="body">
		{#each body as p, i (i)}<p><RichText text={segs(p)} /></p>{/each}
	</div>
{:else if fallbackBody}
	<p>{fallbackBody}</p>
{/if}
{#if statusText}
	<p class="status-line" data-ending-status={status}>{statusText}</p>
{/if}

<style>
	.ending-text p {
		margin: 0 0 var(--space-3);
		white-space: pre-line;
	}
	.ending-text p:last-child {
		margin-block-end: 0;
	}
	.status-line {
		color: var(--color-text-muted);
	}
</style>
