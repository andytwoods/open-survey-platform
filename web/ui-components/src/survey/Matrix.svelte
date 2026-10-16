<script lang="ts">
	import { RadioGroup } from 'bits-ui';
	import './choices.css';
	import { safeId } from './locale';
	import { arrowSelect } from './radio-arrows';
	import QuestionFrame from './QuestionFrame.svelte';
	import RichText from './RichText.svelte';
	import type { MatrixProps } from './types';

	/**
	 * Single choice per row. **One DOM** in two layouts (§6 Matrix):
	 *  - table: rows line up under a header of scale labels (header is aria-hidden; every
	 *    radio is still named by its own scale label);
	 *  - cards: each row is a bordered fieldset with its label as the legend and the scale
	 *    labels shown beside each radio.
	 * Each row is a Bits UI RadioGroup rendered as a <fieldset>/<legend>. The layout is picked
	 * by measuring: a hidden probe lays the header out at its narrowest (row label minimum +
	 * each column at max(touch target, longest word)); if that fits the available width we
	 * use the table. A ResizeObserver re-measures; there is no fixed breakpoint.
	 */
	let {
		id,
		label,
		help,
		required = false,
		value,
		error,
		disabled = false,
		lang,
		revealed = false,
		messages,
		onchange,
		rows,
		choices
	}: MatrixProps = $props();

	let root = $state<HTMLElement | null>(null);
	let probe = $state<HTMLElement | null>(null);
	let layout = $state<'table' | 'cards'>('cards');

	function measure() {
		if (!root || !probe) return;
		const needed = probe.offsetWidth;
		// Not laid out (hidden, or no layout engine): stay with cards, which always fit.
		if (needed === 0) return;
		layout = needed <= root.clientWidth ? 'table' : 'cards';
	}

	$effect(() => {
		if (!root || !probe || typeof ResizeObserver === 'undefined') return;
		const ro = new ResizeObserver(() => measure());
		ro.observe(root);
		ro.observe(probe);
		measure();
		return () => ro.disconnect();
	});

	// Per-row selection held for Bits; follows `value`, reports through onchange.
	let current = $derived<Record<string, string>>(
		Object.fromEntries(rows.map((r) => [r.value, value?.[r.value] ?? '']))
	);

	function setRow(row: string, col: string) {
		current = { ...current, [row]: col };
		const next: Record<string, string | null> = {};
		for (const r of rows) next[r.value] = current[r.value] || null;
		onchange?.(next);
	}
	const arrowsFor = (row: string) => arrowSelect(() => !current[row], (col) => setRow(row, col));
</script>

<QuestionFrame {id} {label} {help} {required} {error} {disabled} {lang} {revealed} {messages} kind="fieldset">
	{#snippet children(ctx)}
		<div class="matrix" data-layout={layout} bind:this={root} style:--cols={choices.length}>
			<div class="m-head" aria-hidden="true">
				<span></span>
				{#each choices as col (col.value)}<span class="m-col"><RichText text={col.label} /></span>{/each}
			</div>
			{#each rows as row (row.value)}
				{@const legendId = `${id}-r-${safeId(row.value)}`}
				{@const arrows = arrowsFor(row.value)}
				<RadioGroup.Root
					bind:value={() => current[row.value] ?? '', (v) => (current = { ...current, [row.value]: v })}
					onValueChange={(v) => setRow(row.value, v)}
					orientation="horizontal"
					disabled={disabled || row.disabled}
					aria-labelledby={legendId}
					aria-invalid={ctx.invalid ? 'true' : undefined}
				>
					{#snippet child({ props })}
						<fieldset {...props} class="m-row">
							<legend id={legendId} class="m-legend"><RichText text={row.label} /></legend>
							{#each choices as col (col.value)}
								<RadioGroup.Item
									id="{legendId}-{safeId(col.value)}"
									class="osp-choice m-cell"
									value={col.value}
									disabled={col.disabled}
									onkeydown={arrows.onkeydown}
									onfocus={() => arrows.onfocus(col.value)}
								>
									<span class="osp-choice-ind" data-kind="radio" aria-hidden="true"></span>
									<span class="osp-choice-text m-cell-label"><RichText text={col.label} /></span>
								</RadioGroup.Item>
							{/each}
						</fieldset>
					{/snippet}
				</RadioGroup.Root>
			{/each}
			<div class="m-probe-clip" aria-hidden="true">
				<div class="m-probe" bind:this={probe}>
					<span></span>
					{#each choices as col (col.value)}<span class="m-col"><RichText text={col.label} /></span>{/each}
				</div>
			</div>
		</div>
	{/snippet}
</QuestionFrame>

<style>
	.matrix {
		--m-label-col: minmax(var(--survey-matrix-label-min), 2fr);
		--m-gap: var(--space-1);
		position: relative;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		min-inline-size: 0;
	}

	/* Shared by both layouts: the legend is floated so it stops being the fieldset's
	   "rendered legend" and becomes an ordinary flex/grid item (float itself has no effect
	   inside flex or grid). It only un-renders the legend; direction is unaffected. */
	.m-legend {
		float: left;
		padding: 0;
		font-weight: var(--weight-medium);
	}
	.m-row {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		min-inline-size: 0;
		margin: 0;
		padding: var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
	}
	.m-head {
		display: none;
	}
	.m-col {
		padding-inline: var(--space-1);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		text-align: center;
		overflow-wrap: normal;
		hyphens: manual;
	}

	/* Table layout */
	.matrix[data-layout='table'] {
		gap: 0;
	}
	.matrix[data-layout='table'] .m-head,
	.matrix[data-layout='table'] .m-row {
		display: grid;
		grid-template-columns: var(--m-label-col) repeat(var(--cols), minmax(var(--survey-target-size), 1fr));
		column-gap: var(--m-gap);
		align-items: center;
	}
	.matrix[data-layout='table'] .m-head {
		align-items: end;
		padding-block-end: var(--space-2);
		border-block-end: 1px solid var(--color-border-strong);
	}
	.matrix[data-layout='table'] .m-row {
		padding-block: var(--space-1);
		padding-inline: var(--space-2) 0;
		border: 0;
		border-block-end: 1px solid var(--color-border);
		border-radius: 0;
	}
	.matrix[data-layout='table'] .m-row:nth-child(odd) {
		background: var(--color-surface);
	}
	.matrix[data-layout='table'] :global(.m-cell) {
		justify-content: center;
		align-items: center;
		padding: var(--space-2);
		border-color: transparent;
		background: transparent;
		box-shadow: none;
	}
	.matrix[data-layout='table'] :global(.m-cell:hover:not(:disabled)) {
		border-color: var(--color-border-strong);
		background: var(--color-surface-raised);
	}
	.matrix[data-layout='table'] :global(.m-cell-label) {
		/* Still the radio's accessible name; the visible header carries the text. */
		position: absolute;
		inline-size: 1px;
		block-size: 1px;
		overflow: hidden;
		clip-path: inset(50%);
		white-space: nowrap;
	}

	/* Measuring probe: the narrowest the table could be. Clipped so it never adds scroll. */
	.m-probe-clip {
		position: absolute;
		inset: 0;
		overflow: hidden;
		visibility: hidden;
		pointer-events: none;
	}
	.m-probe {
		display: grid;
		inline-size: max-content;
		grid-template-columns:
			var(--survey-matrix-label-min)
			repeat(var(--cols), minmax(var(--survey-target-size), min-content));
		column-gap: var(--m-gap);
		/* The table rows' inline padding. */
		padding-inline-start: var(--space-2);
	}
</style>
