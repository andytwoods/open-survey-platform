<script lang="ts">
	/**
	 * The participant's own answers under the ending (end-of-survey plan §4.4, task EN5):
	 * a definition list of every answered question in path order, with the labels and the
	 * answers as the engine renders them (`answerSummary`), and a Print button. The page's
	 * print stylesheet (App.svelte) keeps only the ending and this list. Everything is text
	 * nodes (RichText), never HTML, so an answer cannot inject markup. The session decides
	 * whether there is anything to show (never after a consent decline, a withdrawal or a
	 * resume of an already-submitted session); this component only renders what it is given.
	 */
	import { RichText } from '@osp/ui-components/survey';
	import type { SummaryEntry } from '@osp/engine';
	import { ui } from './messages';
	import { segs } from './view-map';

	let { entries, print = () => window.print() }: { entries: SummaryEntry[]; print?: () => void } = $props();
</script>

{#if entries.length}
	<section class="summary" data-testid="answer-summary" aria-labelledby="answer-summary-h">
		<h2 id="answer-summary-h">{ui.summaryTitle}</h2>
		<p class="muted">{ui.summaryHelp}</p>
		<dl>
			{#each entries as e (e.id)}
				<div class="entry" data-item={e.id}>
					<dt><RichText text={segs(e.label)} /></dt>
					{#if e.rows}
						<dd>
							<dl class="rows">
								{#each e.rows as r (r.id)}
									<div class="row" data-item={r.id}>
										<dt><RichText text={segs(r.label)} /></dt>
										<dd><RichText text={segs(r.value)} /></dd>
									</div>
								{/each}
							</dl>
						</dd>
					{:else}
						<dd><RichText text={segs(e.value)} /></dd>
					{/if}
				</div>
			{/each}
		</dl>
		<div data-print="hide">
			<button type="button" class="btn" onclick={print} data-testid="print">{ui.print}</button>
		</div>
	</section>
{/if}

<style>
	.summary {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	h2 {
		margin: 0;
		font-size: var(--text-lg);
		line-height: var(--leading-tight);
	}
	p {
		margin: 0;
	}
	.muted {
		color: var(--color-text-muted);
	}
	dl {
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.entry {
		padding-block-end: var(--space-3);
		border-block-end: 1px solid var(--color-border);
	}
	.entry:last-child {
		border-block-end: 0;
	}
	dt {
		font-weight: var(--weight-medium);
	}
	dd {
		margin: var(--space-1) 0 0;
		white-space: pre-line;
		overflow-wrap: anywhere;
	}
	.rows {
		gap: var(--space-2);
	}
	.rows .row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1) var(--space-3);
	}
	.rows dt {
		font-weight: var(--weight-normal);
	}
	.rows dt::after {
		content: ':';
	}
	.rows dd {
		margin: 0;
	}
	.btn {
		min-block-size: 2.75rem;
		min-inline-size: 5.5rem;
		padding-inline: var(--space-4);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-weight: var(--weight-medium);
		cursor: pointer;
	}
	.btn:hover {
		filter: brightness(0.95);
	}
	.btn:focus-visible {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 2px;
	}
</style>
