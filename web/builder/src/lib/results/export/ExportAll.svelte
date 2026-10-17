<script lang="ts">
	import Archive from '@lucide/svelte/icons/archive';
	import { Button, Dialog } from '@osp/ui-components';
	import type { ResultsController } from '../results.svelte';
	import { smallCells, suppressCard, WARN_BELOW } from './model';
	import { download, exportAll } from './run';
	import SettingsFields from './SettingsFields.svelte';

	/**
	 * "Export all" (task V4): one ZIP with every card's SVG, PNG, CSV and Vega-Lite spec at
	 * the shared settings (captions as edited per card) and one manifest.json.
	 */
	let { controller }: { controller: ResultsController } = $props();

	let open = $state(false);
	let busy = $state(false);
	let progress = $state<{ done: number; total: number } | null>(null);
	let error = $state<string | null>(null);
	let done = $state<string | null>(null);

	const s = $derived(controller.exports);
	const cards = $derived(
		(controller.response?.cards ?? []).filter((c) => c.type !== 'note' && !controller.charts.hidden(c.question))
	);
	const small = $derived(open ? cards.reduce((n, c) => n + smallCells(suppressCard(c, s.k).card), 0) : 0);

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

<Dialog bind:open title="Export all figures" description="A ZIP with each question's SVG, PNG, CSV and Vega-Lite spec, and one manifest." size="md">
	<div class="body">
		<SettingsFields settings={s} />
		<p class="note">
			{cards.length}
			{cards.length === 1 ? 'question' : 'questions'}, each with its chart as chosen on its card and its caption
			(edited captions are kept).
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
