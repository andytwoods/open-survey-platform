<script lang="ts">
	import { Button, Dialog } from '@osp/ui-components';
	import { ResultsChart } from '../charts';
	import type { ResultsController } from '../results.svelte';
	import type { Card } from '../types';
	import { figureSpec } from './figure';
	import {
		cardCsv,
		cssWidth,
		DERIVED_CHARTS,
		fileName,
		pixelHeight,
		pixelWidth,
		smallCells,
		suppressCard,
		WARN_BELOW
	} from './model';
	import { captionFor, download, exportCard, figureChoice, type ExportFormat } from './run';
	import SettingsFields from './SettingsFields.svelte';

	/**
	 * Export one card (task V4, V-D6–V-D8): format, final width and DPI, "Hide counts below
	 * k" with a warning about small shown cells, the editable automatic caption, and a
	 * preview at final size (96 px per inch) of exactly what will be downloaded.
	 */
	let {
		open = $bindable(false),
		format = $bindable('png'),
		card,
		controller
	}: { open?: boolean; format?: ExportFormat; card: Card; controller: ResultsController } = $props();

	const FORMATS: { id: ExportFormat; label: string; hint: string }[] = [
		{ id: 'png', label: 'PNG', hint: 'Image at a set size and resolution' },
		{ id: 'svg', label: 'SVG', hint: 'Vector image; sized in mm' },
		{ id: 'csv', label: 'CSV', hint: 'The aggregate table: counts, n, bin edges' },
		{ id: 'vega-lite', label: 'Vega-Lite spec', hint: 'Chart spec with its data, plus a manifest' }
	];

	const uid = $props.id();
	const s = $derived(controller.exports);
	let busy = $state(false);
	let error = $state<string | null>(null);
	let done = $state<string | null>(null);
	let previewSize = $state<{ w: number; h: number } | null>(null);

	// A plain copy of the card: Vega clones specs, and $state proxies cannot be cloned.
	const plain = $derived(open ? ($state.snapshot(card) as Card) : card);
	const page = $derived(open ? controller.exportPage() : null);
	const choice = $derived(figureChoice(plain, controller.charts));
	const denominator = $derived(page?.response.denominator ?? 'answered');
	const intervals = $derived(page?.query.intervals ?? false);
	const suppressed = $derived(suppressCard(plain, s.k));
	const caption = $derived(page ? captionFor(plain, page, s, suppressed.hidden) : { text: '', edited: false });
	const small = $derived(smallCells(suppressed.card));
	const tokens = $derived(page?.theme?.tokens ?? null);
	const figure = $derived(
		open && choice.chart && format !== 'csv'
			? figureSpec(plain, {
					chart: choice.chart,
					layout: choice.layout,
					denominator,
					intervals,
					widthMm: s.widthMm,
					caption: caption.text,
					k: s.k,
					tokens
				})
			: null
	);
	const csv = $derived(open && format === 'csv' ? cardCsv(suppressed.card, { denominator, k: s.k }) : '');
	const heightPx = $derived(
		previewSize ? pixelHeight(previewSize.w, previewSize.h, pixelWidth(s.widthMm, s.dpi)) : null
	);
	const files = $derived(
		format === 'vega-lite' ? [fileName(card, 'vega-lite'), fileName(card, 'manifest')] : [fileName(card, format)]
	);

	function measure() {
		requestAnimationFrame(() => {
			const svg = document.getElementById(`${uid}-preview`)?.querySelector('svg');
			if (svg) previewSize = { w: Number(svg.getAttribute('width')), h: Number(svg.getAttribute('height')) };
		});
	}

	async function run() {
		if (busy) return;
		busy = true;
		error = null;
		done = null;
		try {
			const p = controller.exportPage();
			if (!p) throw new Error('Load the results first.');
			const out = await exportCard(plain, p, s, format);
			for (const f of out) download(f);
			done = `Downloaded ${out.map((f) => f.name).join(' and ')}.`;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}

	const onCaption = (e: Event) => s.setCaption(card.question, (e.currentTarget as HTMLTextAreaElement).value);
</script>

<Dialog bind:open title="Export: {card.label || card.name}" size="lg">
	<div class="body">
		<fieldset class="formats">
			<legend>Format</legend>
			{#each FORMATS as f (f.id)}
				<label class="format">
					<input type="radio" name="{uid}-format" value={f.id} bind:group={format} />
					<span><strong>{f.label}</strong> <span class="muted">{f.hint}</span></span>
				</label>
			{/each}
		</fieldset>

		<SettingsFields settings={s} size={format === 'png' || format === 'svg'} dpi={format === 'png'} {heightPx} />

		{#if small > 0}
			<p class="warning" data-testid="small-cells">
				{small}
				{small === 1 ? 'shown cell has' : 'shown cells have'} fewer than {WARN_BELOW} responses. Consider “Hide counts
				below k” before sharing this figure.
			</p>
		{/if}
		{#if s.k !== null && choice.chart && DERIVED_CHARTS.includes(choice.chart) && format !== 'csv'}
			<p class="warning">
				This chart is drawn from every answer (curve or quartiles), so it can still show small counts. The CSV hides
				them.
			</p>
		{/if}

		{#if format !== 'csv'}
			<div class="caption">
				<label for="{uid}-caption">Caption</label>
				<textarea id="{uid}-caption" rows="4" value={caption.text} oninput={onCaption}></textarea>
				<div class="caption-row">
					<span class="muted">{caption.edited ? 'Edited.' : 'Written from the question, filters and n.'}</span>
					{#if caption.edited}
						<Button size="sm" variant="ghost" onclick={() => s.resetCaption(card.question)}>Use the automatic caption</Button>
					{/if}
				</div>
			</div>
		{/if}

		<section class="preview" aria-labelledby="{uid}-preview-h">
			<h3 id="{uid}-preview-h">
				Preview{format === 'png' || format === 'svg' ? `, final size (${s.widthMm} mm wide)` : ''}
			</h3>
			{#if format === 'csv'}
				<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
				<pre class="text" role="region" tabindex="0" aria-label="CSV preview">{csv.split('\r\n').slice(0, 12).join('\n')}</pre>
			{:else if figure}
				<!-- A wide final size scrolls sideways; the scroller then takes keyboard focus. -->
				<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
				<div class="sheet" id="{uid}-preview" role="region" aria-label="Figure preview" tabindex="0">
					<div class="paper" style:width="{cssWidth(s.widthMm)}px" style:background={tokens?.bg ?? undefined}>
						<ResultsChart spec={figure.spec} theme="export" tokens={tokens ?? undefined} title={card.label || card.name} description={caption.text} onview={measure} />
					</div>
				</div>
			{:else}
				<p class="muted">This question has no chart to export; its CSV has the numbers.</p>
			{/if}
		</section>

		<p class="files">Downloads: {#each files as f, i (f)}{i ? ', ' : ''}<code>{f}</code>{/each}</p>
		{#if format !== 'csv' && page}
			<p class="files" data-testid="export-theme">Colours: {page.theme?.description}</p>
		{/if}
		<div class="live" role="status" aria-live="polite">
			{#if busy}Preparing the export…{:else if done}{done}{/if}
		</div>
		{#if error}<p class="error" role="alert">{error}</p>{/if}
	</div>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (open = false)}>Done</Button>
		<Button variant="primary" onclick={run} disabled={busy || (format !== 'csv' && !figure)}>Download</Button>
	{/snippet}
</Dialog>

<style>
	.body {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		min-width: 0;
	}
	.formats {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr));
		gap: var(--space-1) var(--space-3);
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		min-width: 0;
	}
	legend {
		padding: 0 var(--space-1);
		font-size: var(--text-sm);
		font-weight: var(--weight-bold);
	}
	.format {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-height: 2.75rem;
		font-size: var(--text-sm);
	}
	.muted {
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.warning {
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-inline-start: 4px solid var(--color-warning);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		font-size: var(--text-sm);
	}
	.caption {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		font-size: var(--text-sm);
	}
	.caption label {
		font-weight: var(--weight-bold);
	}
	textarea {
		width: 100%;
		box-sizing: border-box;
		padding: var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		resize: vertical;
	}
	.caption-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
	}
	.preview h3 {
		margin: 0 0 var(--space-2);
		font-size: var(--text-sm);
	}
	.sheet {
		max-height: 26rem;
		overflow: auto;
		padding: var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-sunken);
	}
	.paper {
		background: #ffffff;
		box-shadow: var(--shadow-md, 0 1px 3px rgb(0 0 0 / 0.2));
	}
	.text {
		max-height: 16rem;
		margin: 0;
		overflow: auto;
		padding: var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-sunken);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}
	.sheet:focus-visible,
	.text:focus-visible,
	textarea:focus-visible,
	input:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}
	.files {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--color-text-muted);
		overflow-wrap: anywhere;
	}
	.files code {
		font-family: var(--font-mono);
	}
	.live:empty {
		display: none;
	}
	.live {
		font-size: var(--text-sm);
	}
	.error {
		margin: 0;
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
</style>
