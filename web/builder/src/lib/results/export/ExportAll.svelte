<script lang="ts">
	import Archive from '@lucide/svelte/icons/archive';
	import { Button, Dialog } from '@osp/ui-components';
	import type { ResultsController } from '../results.svelte';
	import { smallCells, suppressCard, WARN_BELOW } from './model';
	import { bundleFormats, download, exportAll } from './run';
	import type { Bundle } from './settings.svelte';
	import SettingsFields from './SettingsFields.svelte';

	/**
	 * "Export all" (tasks V4, V6): one ZIP with every shown card's figure files at the
	 * shared settings (captions as edited per card) and one manifest.json. The bundle is
	 * SVG only, PNG only (at the size and DPI chosen) or everything (SVG, PNG, CSV and the
	 * Vega-Lite spec); a saved layout keeps the choice.
	 */
	let { controller }: { controller: ResultsController } = $props();

	const BUNDLES: { id: Bundle; label: string; hint: string }[] = [
		{ id: 'svg', label: 'SVG only', hint: 'Vector images sized in mm' },
		{ id: 'png', label: 'PNG only', hint: 'Images at the width and resolution below' },
		{ id: 'all', label: 'Everything', hint: 'SVG, PNG, CSV and the Vega-Lite spec per question' }
	];

	let open = $state(false);
	let busy = $state(false);
	let progress = $state<{ done: number; total: number } | null>(null);
	let error = $state<string | null>(null);
	let done = $state<string | null>(null);

	const uid = $props.id();
	const s = $derived(controller.exports);
	const cards = $derived(controller.cards.filter((c) => c.type !== 'note' && !controller.charts.hidden(c.question)));
	const small = $derived(open ? cards.reduce((n, c) => n + smallCells(suppressCard(c, s.k).card), 0) : 0);
	const files = $derived(bundleFormats(s.bundle).map((f) => (f === 'vega-lite' ? 'Vega-Lite spec' : f.toUpperCase())));

	async function run() {
		if (busy) return;
		busy = true;
		error = null;
		done = null;
		try {
			const page = controller.exportPage();
			if (!page) throw new Error('Load the results first.');
			const zip = await exportAll(page, s, (d, total) => (progress = { done: d, total }));
			download(zip);
			done = `Downloaded ${zip.name}.`;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
			progress = null;
		}
	}
</script>

<Button onclick={() => (open = true)} disabled={!cards.length}>
	<Archive size={16} aria-hidden="true" /> Export all
</Button>

<Dialog bind:open title="Export all figures" description="A ZIP with a file set per shown question, in the page's order, and one manifest." size="md">
	<div class="body">
		<fieldset class="bundles">
			<legend>Contents</legend>
			{#each BUNDLES as b (b.id)}
				<label class="bundle">
					<input type="radio" name="{uid}-bundle" value={b.id} bind:group={s.bundle} />
					<span><strong>{b.label}</strong> <span class="muted">{b.hint}</span></span>
				</label>
			{/each}
		</fieldset>
		<SettingsFields settings={s} dpi={s.bundle !== 'svg'} />
		<p class="note" data-testid="export-all-note">
			{cards.length}
			{cards.length === 1 ? 'question' : 'questions'}, each as {files.join(', ')}, with its chart as chosen on its card and
			its caption (edited captions are kept). Colours: {controller.theme.exportDescription}.
		</p>
		{#if small > 0}
			<p class="warning" data-testid="small-cells-all">
				{small}
				{small === 1 ? 'shown cell has' : 'shown cells have'} fewer than {WARN_BELOW} responses. Consider “Hide counts
				below k” before sharing these figures.
			</p>
		{/if}
		<div class="live" role="status" aria-live="polite">
			{#if busy}
				{progress ? `Drawing ${Math.min(progress.done + 1, progress.total)} of ${progress.total}…` : 'Preparing the export…'}
			{:else if done}{done}{/if}
		</div>
		{#if error}<p class="error" role="alert">{error}</p>{/if}
	</div>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (open = false)}>Done</Button>
		<Button variant="primary" onclick={run} disabled={busy}>Download ZIP</Button>
	{/snippet}
</Dialog>

<style>
	.body {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.note {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.bundles {
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
	.bundle {
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
