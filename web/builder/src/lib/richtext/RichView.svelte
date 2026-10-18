<script lang="ts">
	import type { InlineRun, RichBlock } from '@osp/engine';
	import { asRich, type RichValue } from './convert';

	/**
	 * Read-only rendering of a survey text (plain or rich) in the builder: the idle state of
	 * the editor, the question cards and the consent preview. Runs are text nodes inside
	 * `<strong>`, `<em>` and `<span lang>`; pipes are chips; links are styled spans, never
	 * anchors (this view sits inside buttons and textboxes). Never {@html}.
	 *
	 * `inline` flattens blocks to lines (a break between them, list items with their marker)
	 * so the view is valid phrasing content inside a `<button>` or `<label>`.
	 */
	let { value, inline = false, lang }: { value: RichValue | undefined | null; inline?: boolean; lang?: string } = $props();

	const tree = $derived(asRich(value));

	/** The blocks as lines of runs when flattened. */
	const lines = $derived.by((): InlineRun[][] => {
		const out: InlineRun[][] = [];
		for (const b of tree.blocks) {
			if ('items' in b) b.items.forEach((item, i) => out.push(b.type === 'ol' ? [{ text: `${i + 1}. ` }, ...item] : [{ text: '• ' }, ...item]));
			else out.push(b.content);
		}
		return out;
	});

	const headingLevel = (b: RichBlock) => (b.type === 'h' ? b.level : 0);
</script>

{#snippet run(r: InlineRun)}{#if 'br' in r}<br />{:else if 'pipe' in r}<span class="osp-rt-chip" title="Piped answer: {r.pipe}"
			>$&#123;{r.pipe}&#125;</span
		>{:else}{@const b = r.marks?.includes('b')}{@const i = r.marks?.includes('i')}{#if r.href}<span
				class="osp-rt-link"
				title={r.href}
				lang={r.lang}>{#if b && i}<strong><em>{r.text}</em></strong>{:else if b}<strong>{r.text}</strong>{:else if i}<em
						>{r.text}</em
					>{:else}{r.text}{/if}</span
			>{:else if b && i}<strong lang={r.lang}><em>{r.text}</em></strong>{:else if b}<strong lang={r.lang}>{r.text}</strong
			>{:else if i}<em lang={r.lang}>{r.text}</em>{:else if r.lang}<span lang={r.lang}>{r.text}</span>{:else}{r.text}{/if}{/if}{/snippet}

{#snippet runs(list: InlineRun[])}{#each list as r, i (i)}{@render run(r)}{/each}{/snippet}

{#if inline}<span class="osp-rv-inline" {lang}
		>{#each lines as line, i (i)}{#if i > 0}<br />{/if}{@render runs(line)}{/each}</span
	>{:else}<div class="osp-rv" {lang}>
		{#each tree.blocks as b, i (i)}
			{#if b.type === 'p'}
				<p class="osp-rv-p">{@render runs(b.content)}</p>
			{:else if b.type === 'h'}
				<p class="osp-rv-h" data-level={headingLevel(b)}>{@render runs(b.content)}</p>
			{:else if b.type === 'ul'}
				<ul class="osp-rv-list">
					{#each b.items as item, j (j)}<li>{@render runs(item)}</li>{/each}
				</ul>
			{:else}
				<ol class="osp-rv-list">
					{#each b.items as item, j (j)}<li>{@render runs(item)}</li>{/each}
				</ol>
			{/if}
		{/each}
	</div>{/if}

<style>
	.osp-rv,
	.osp-rv-inline {
		overflow-wrap: anywhere;
	}
	.osp-rv-p,
	.osp-rv-h {
		margin: 0;
	}
	.osp-rv > * + * {
		margin-block-start: var(--space-2);
	}
	.osp-rv-h {
		font-weight: var(--weight-bold);
		line-height: var(--leading-tight);
	}
	.osp-rv-h[data-level='1'] {
		font-size: 1.25em;
	}
	.osp-rv-h[data-level='2'] {
		font-size: 1.1em;
	}
	.osp-rv-list {
		margin: 0;
		padding-inline-start: 1.5em;
	}
	:global(.osp-rt-chip) {
		display: inline-block;
		padding: 0 var(--space-1);
		border: 1px solid var(--color-accent);
		border-radius: var(--radius-sm);
		background: var(--color-accent-subtle);
		color: var(--color-text);
		font-family: var(--font-mono, ui-monospace, monospace);
		font-size: 0.875em;
		font-style: normal;
		font-weight: var(--weight-normal);
		line-height: 1.4;
		white-space: nowrap;
	}
	:global(.osp-rt-chip-error) {
		border-color: var(--color-danger);
		border-style: dashed;
		text-decoration: underline wavy var(--color-danger);
	}
	:global(.osp-rt-link) {
		color: var(--color-accent);
		text-decoration: underline;
		text-underline-offset: 0.15em;
	}
</style>
