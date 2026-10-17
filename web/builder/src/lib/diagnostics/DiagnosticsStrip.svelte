<script lang="ts">
	import ChevronUp from '@lucide/svelte/icons/chevron-up';
	import { Select, announce } from '@osp/ui-components';
	import { untrack } from 'svelte';
	import type { SurveyStore } from '../sync/survey-store.svelte';
	import type { ExportCheckState } from './export-check.svelte';
	import {
		TARGET_OPTIONS,
		countItems,
		countsText,
		stripItems,
		targetLabel,
		type StripItem,
		type TargetChoice
	} from './model';

	/**
	 * The diagnostics strip (builder-design §2, task B10): validation errors and warnings for
	 * the draft plus, with an export target picked, that target's export issues. Each item
	 * goes to its property (or card). Count changes are announced through the live region.
	 */
	let {
		store,
		check,
		open = $bindable(false),
		ongo
	}: {
		store: SurveyStore;
		check: ExportCheckState;
		open?: boolean;
		ongo: (item: StripItem) => void;
	} = $props();

	const items = $derived(stripItems(store.survey, store.diagnostics, check.diagnostics));
	const counts = $derived(countItems(items));
	const summary = $derived(countsText(counts, check.target));

	// Fetch the export check when the target or the draft revision changes.
	$effect(() => {
		void check.target;
		const id = store.surveyId;
		const rev = store.revision;
		untrack(() => check.request(id, rev));
	});

	// Announce count changes (not the first render).
	let announced: string | null = null;
	$effect(() => {
		const text = summary;
		if (check.loading) return;
		if (announced !== null && announced !== text) announce(`Diagnostics: ${text}.`);
		announced = text;
	});

	const kindLabel = (i: StripItem) =>
		i.kind === 'export'
			? i.level === 'error'
				? 'Export error'
				: i.level === 'unsupported'
					? 'Unsupported'
					: 'Approximated'
			: i.kind === 'error'
				? 'Error'
				: i.kind === 'warning'
					? 'Warning'
					: 'Info';
	const tone = (i: StripItem) =>
		i.kind === 'error' || i.level === 'error' || i.level === 'unsupported'
			? 'danger'
			: i.kind === 'warning' || i.level === 'approximated'
				? 'warning'
				: 'neutral';
</script>

<section class="strip" aria-labelledby="diagnostics-heading" data-testid="diagnostics-strip">
	<div class="head">
		<h2 id="diagnostics-heading" class="osp-visually-hidden">Diagnostics</h2>
		<button
			type="button"
			class="toggle"
			aria-expanded={open}
			aria-controls="diagnostics-list"
			onclick={() => (open = !open)}
		>
			<span class="chev" class:open aria-hidden="true"><ChevronUp size={16} /></span>
			Diagnostics
			<span class="osp-visually-hidden">: {summary}</span>
		</button>
		<ul class="counts" aria-hidden="true">
			<li data-tone={counts.errors ? 'danger' : 'neutral'} data-testid="count-errors">
				{counts.errors} {counts.errors === 1 ? 'error' : 'errors'}
			</li>
			<li data-tone={counts.warnings ? 'warning' : 'neutral'} data-testid="count-warnings">
				{counts.warnings} {counts.warnings === 1 ? 'warning' : 'warnings'}
			</li>
			{#if check.target !== 'none'}
				<li data-tone={counts.exportIssues ? 'warning' : 'neutral'} data-testid="count-export">
					{counts.exportIssues} export {counts.exportIssues === 1 ? 'issue' : 'issues'}
				</li>
			{/if}
		</ul>
		{#if check.loading}<span class="muted">Checking {targetLabel(check.target)}…</span>{/if}
		{#if check.error}<span class="muted" role="status">Export check failed: {check.error}</span>{/if}
		<div class="target">
			<Select
				label="Export target"
				options={TARGET_OPTIONS}
				value={check.target}
				onValueChange={(v) => check.setTarget(v as TargetChoice)}
			/>
		</div>
	</div>
	<div id="diagnostics-list" class="list" hidden={!open}>
		{#if items.length === 0}
			<p class="muted">
				No problems{check.target !== 'none' ? ` and nothing lost in ${targetLabel(check.target)}` : ''}.
			</p>
		{:else}
			<ul>
				{#each items as item (item.key)}
					<li data-kind={item.kind} data-level={item.level}>
						<button type="button" class="item" onclick={() => ongo(item)}>
							<span class="kind" data-tone={tone(item)}>{kindLabel(item)}</span>
							<span class="where">{item.where}</span>
							<span class="msg">{item.message}</span>
						</button>
					</li>
				{/each}
			</ul>
		{/if}
	</div>
</section>

<style>
	.strip {
		flex: none;
		border-top: 1px solid var(--color-border);
		background: var(--color-surface);
		color: var(--color-text);
		font-size: var(--text-sm);
	}
	.head {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-3);
		padding: var(--space-1) var(--space-3);
	}
	.toggle {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		padding: var(--space-1) var(--space-2);
		border: 0;
		border-radius: var(--radius-sm);
		background: none;
		color: inherit;
		font: inherit;
		font-weight: var(--weight-bold);
		cursor: pointer;
	}
	.toggle:hover {
		background: var(--color-surface-sunken);
	}
	.chev {
		display: inline-flex;
		transition: transform 0.15s;
	}
	.chev.open {
		transform: rotate(180deg);
	}
	.counts {
		display: flex;
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.counts li,
	.kind {
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-full);
		font-size: var(--text-xs);
		line-height: 1.6;
		white-space: nowrap;
	}
	[data-tone='danger'] {
		border-color: var(--color-danger);
		color: var(--color-danger);
		font-weight: var(--weight-medium);
	}
	[data-tone='warning'] {
		border-color: var(--color-warning);
		color: var(--color-warning);
		font-weight: var(--weight-medium);
	}
	.target {
		display: flex;
		align-items: center;
		margin-inline-start: auto;
	}
	.target :global(.osp-field) {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.muted {
		margin: 0;
		color: var(--color-text-muted);
	}
	.list {
		max-height: 30vh;
		overflow: auto;
		padding: 0 var(--space-3) var(--space-2);
	}
	.list ul {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.item {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		width: 100%;
		padding: var(--space-1) var(--space-2);
		border: 0;
		border-radius: var(--radius-sm);
		background: none;
		color: inherit;
		font: inherit;
		text-align: start;
		cursor: pointer;
	}
	.item:hover {
		background: var(--color-surface-sunken);
	}
	.where {
		flex: none;
		color: var(--color-text-muted);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}
	.msg {
		min-width: 0;
		overflow-wrap: anywhere;
	}
</style>
