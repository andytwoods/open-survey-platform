<script lang="ts">
	import { inlineNodes, messagesFor } from './locale';
	import type { InlineNode, Text, TextSegment, WidgetMessages } from './types';

	/**
	 * Inline display text (planning/rich-text.md §7): runs as text nodes inside `<strong>`,
	 * `<em>`, `<span lang>` and `<a>` (https links open in a new tab with a visually hidden
	 * "(opens in a new tab)"), breaks as `<br>`. Never {@html}: researcher text and piped
	 * participant values are both text nodes, so nothing can inject markup. Blocks given to
	 * it are flattened (a break between them): use RichText where block content is valid.
	 */
	let { text, messages }: { text: Text | undefined; messages?: Partial<WidgetMessages> } = $props();

	type Group = { href: string; runs: TextSegment[] } | { href: null; node: InlineNode };

	/** Adjacent runs with the same href are one link. */
	function group(nodes: readonly InlineNode[]): Group[] {
		const out: Group[] = [];
		for (const n of nodes) {
			const last = out[out.length - 1];
			if (!('br' in n) && n.href) {
				if (last && last.href === n.href) last.runs.push(n);
				else out.push({ href: n.href, runs: [n] });
			} else out.push({ href: null, node: n });
		}
		return out;
	}

	const groups = $derived(group(inlineNodes(text)));
	const suffix = $derived(' ' + messagesFor(messages).opensInNewTab);
</script>

{#snippet run(seg: TextSegment)}{#if seg.strong && seg.em}<strong lang={seg.lang}><em>{seg.text}</em></strong
		>{:else if seg.strong}<strong lang={seg.lang}>{seg.text}</strong>{:else if seg.em}<em lang={seg.lang}>{seg.text}</em
		>{:else if seg.lang}<span lang={seg.lang}>{seg.text}</span>{:else}{seg.text}{/if}{/snippet}

{#snippet link(href: string, runs: TextSegment[])}<a {href} target="_blank" rel="noopener noreferrer"
		>{#each runs as seg, j (j)}{@render run(seg)}{/each}<span class="osp-visually-hidden">{suffix}</span></a
	>{/snippet}

{#each groups as g, i (i)}{#if g.href !== null}{@render link(g.href, g.runs)}{:else if 'br' in g.node}<br
		/>{:else}{@render run(g.node)}{/if}{/each}
