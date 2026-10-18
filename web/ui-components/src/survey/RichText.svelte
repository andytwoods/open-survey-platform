<script lang="ts">
	import { isBlocks } from './locale';
	import RichInline from './RichInline.svelte';
	import type { Text, WidgetMessages } from './types';

	/**
	 * Display text (planning/rich-text.md §7): a string or inline runs render inline; blocks
	 * render as `<p>`, `<h3>`–`<h5>` (headings 1–3 under the page's h2) and `<ul>`/`<ol>`.
	 * Runs are text nodes (RichInline); this component never uses {@html}, so researcher
	 * text and piped participant values cannot inject markup. A single paragraph renders
	 * without a `<p>` wrapper, so it is valid inside a `<label>` or `<legend>`; `block`
	 * keeps the wrapper (a reading page of paragraphs).
	 */
	let {
		text,
		messages,
		block = false
	}: { text: Text | undefined; messages?: Partial<WidgetMessages>; block?: boolean } = $props();
	const blocks = $derived(isBlocks(text) ? text : null);
	const single = $derived(!block && blocks && blocks.length === 1 && blocks[0]!.type === 'p' ? blocks[0] : null);
</script>

{#if !blocks}<RichInline {text} {messages} />{:else if single}<RichInline
		text={single.content}
		{messages}
	/>{:else}{#each blocks as b, i (i)}{#if b.type === 'p'}<p class="osp-rt"><RichInline text={b.content} {messages} /></p
			>{:else if b.type === 'h'}{#if b.level === 1}<h3 class="osp-rt"><RichInline text={b.content} {messages} /></h3
				>{:else if b.level === 2}<h4 class="osp-rt"><RichInline text={b.content} {messages} /></h4
				>{:else}<h5 class="osp-rt"><RichInline text={b.content} {messages} /></h5>{/if}{:else if b.type === 'ul'}<ul
				class="osp-rt"
			>
				{#each b.items as item, j (j)}<li><RichInline text={item} {messages} /></li>{/each}
			</ul>{:else}<ol class="osp-rt">
				{#each b.items as item, j (j)}<li><RichInline text={item} {messages} /></li>{/each}
			</ol>{/if}{/each}{/if}

<style>
	.osp-rt {
		margin: 0;
	}
	p.osp-rt + .osp-rt,
	ul.osp-rt + .osp-rt,
	ol.osp-rt + .osp-rt,
	h3.osp-rt + .osp-rt,
	h4.osp-rt + .osp-rt,
	h5.osp-rt + .osp-rt {
		margin-block-start: var(--space-3);
	}
	h3.osp-rt,
	h4.osp-rt,
	h5.osp-rt {
		font-weight: var(--weight-semibold, 600);
		line-height: var(--leading-tight);
	}
	h3.osp-rt {
		font-size: var(--text-lg);
	}
	h4.osp-rt {
		font-size: var(--text-md);
	}
	h5.osp-rt {
		font-size: var(--text-md);
		font-weight: var(--weight-medium);
	}
	ul.osp-rt,
	ol.osp-rt {
		padding-inline-start: 1.5em;
	}
</style>
