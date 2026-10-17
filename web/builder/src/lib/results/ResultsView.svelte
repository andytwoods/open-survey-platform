<script lang="ts">
	import Eye from '@lucide/svelte/icons/eye';
	import EyeOff from '@lucide/svelte/icons/eye-off';
	import GripVertical from '@lucide/svelte/icons/grip-vertical';
	import Presentation from '@lucide/svelte/icons/presentation';
	import X from '@lucide/svelte/icons/x';
	import { Button, cssVarsToStyle, theme, themeToCssVars } from '@osp/ui-components';
	import { onDestroy, onMount, tick } from 'svelte';
	import LayoutBar from './LayoutBar.svelte';
	import { LayoutsController } from './layouts.svelte';
	import type { Card } from './types';
	import { readTokens } from './charts/theme';
	import type { ThemeTokens } from './charts/types';
	import ExportAll from './export/ExportAll.svelte';
	import FilterBar from './FilterBar.svelte';
	import { conditionVariables } from './model';
	import { layoutIn, presentIn, withPresent } from './presentation';
	import { presentation } from './presentation.svelte';
	import ResultCard from './ResultCard.svelte';
	import { surveyThemeOf } from './results-theme';
	import { apiSource, ResultsController, type ResultsSource } from './results.svelte';
	import ThemePicker from './ThemePicker.svelte';

	/**
	 * The Results page (task V2, planning/results-viewer.md): a filter bar, the active
	 * filters in words, and one card per question in survey order. Every number is the
	 * server's (V1); this page only asks and draws. Lazily loaded by the shell. Task V6
	 * adds the page's own theme (the cards and every export are drawn in it) and a
	 * presentation mode that shows only the cards (`?present=1`, Escape to leave).
	 */
	let {
		surveyId,
		survey,
		publishedVersions,
		source
	}: {
		surveyId: string;
		/** The survey draft: its assigned variables give the condition filter's options, its theme the "survey's theme" option. */
		survey: unknown;
		publishedVersions: number;
		/** Where results come from (default: the API). */
		source?: ResultsSource;
	} = $props();

	// The source and version count are fixed for the page's life (a new publish reloads).
	// svelte-ignore state_referenced_locally
	const controller = new ResultsController(source ?? apiSource(surveyId), publishedVersions);
	/** Saved layouts (V5b), when the source offers them. */
	const layouts = controller.source.layouts ? new LayoutsController(controller.source.layouts, controller) : null;
	const conditions = $derived(conditionVariables(survey));
	const cards = $derived(controller.cards);
	const notices = $derived(controller.chartNotices);

	// -- the page's theme (V6) ---------------------------------------------------------------
	$effect(() => {
		controller.theme.surveyTheme = surveyThemeOf(survey);
	});
	const appMode = $derived(theme.resolved);
	const pageTheme = $derived(controller.theme.theme);
	const themeMode = $derived(controller.theme.mode(appMode));
	/** The theme's tokens as CSS custom properties, for the cards (or, presenting, the page). */
	const themeStyle = $derived(pageTheme ? cssVarsToStyle(themeToCssVars(pageTheme, themeMode)) : undefined);

	// -- presentation mode (V6) ----------------------------------------------------------------
	const presenting = $derived(presentation.active);
	let presentButton = $state<HTMLButtonElement | null>(null);
	let exitButton = $state<HTMLButtonElement | null>(null);
	let urlSynced = false;
	$effect(() => {
		// Mirror the flag into the URL once the page has read its initial state.
		const on = presentation.active;
		if (!urlSynced || typeof history === 'undefined') return;
		const next = withPresent(location.href, on);
		if (next !== location.href) history.replaceState(history.state, '', next);
	});
	async function present(on: boolean) {
		if (on) presentation.enter();
		else presentation.exit();
		await tick();
		(on ? exitButton : presentButton)?.focus();
	}
	function onWindowKey(e: KeyboardEvent) {
		if (!presenting || e.key !== 'Escape' || e.defaultPrevented) return;
		// Escape inside an open dialog closes only the dialog.
		if (document.querySelector('[role="dialog"][data-state="open"]')) return;
		e.preventDefault();
		void present(false);
	}

	// -- reordering (drag the handle, or focus it and use the arrow keys) --------------------
	const uid = $props.id();
	let dragging = $state<string | null>(null);
	let over = $state<string | null>(null);
	let moveMessage = $state('');
	const nameOf = (c: Card) => c.label || c.name;

	async function moveTo(question: string, to: number, refocus: boolean) {
		const n = cards.length;
		const target = Math.max(0, Math.min(n - 1, to));
		if (cards[target]?.question === question) return;
		controller.move(question, target);
		const card = cards.find((c) => c.question === question);
		moveMessage = `${card ? nameOf(card) : question} moved to position ${target + 1} of ${n}.`;
		if (refocus) {
			await tick();
			document.querySelector<HTMLElement>(`[data-move="${CSS.escape(question)}"]`)?.focus();
		}
	}

	function onHandleKey(e: KeyboardEvent, question: string, i: number) {
		const to =
			e.key === 'ArrowUp' ? i - 1 : e.key === 'ArrowDown' ? i + 1 : e.key === 'Home' ? 0 : e.key === 'End' ? cards.length - 1 : null;
		if (to === null) return;
		e.preventDefault();
		void moveTo(question, to, true);
	}

	function onDrop(e: DragEvent, target: string) {
		e.preventDefault();
		const q = dragging ?? e.dataTransfer?.getData('text/plain');
		dragging = null;
		over = null;
		if (!q || q === target) return;
		void moveTo(
			q,
			cards.findIndex((c) => c.question === target),
			false
		);
	}

	function hide(question: string, hidden: boolean) {
		controller.charts.setHidden(question, hidden);
		void tick().then(() =>
			document.querySelector<HTMLElement>(`[data-${hidden ? 'show' : 'hide'}="${CSS.escape(question)}"]`)?.focus()
		);
	}
	const response = $derived(controller.response);
	const active = $derived(controller.activeFilters);
	const slow = $derived(controller.loading && controller.elapsed >= 1);
	/**
	 * The app's design tokens, re-read when light/dark changes: chart palettes are baked into
	 * the specs (V3), so every card rebuilds its spec from these.
	 */
	let tokens = $state<ThemeTokens>(readTokens());
	/** What the charts are drawn with: the page theme's tokens (V6), else the app's. */
	const chartTokens = $derived(controller.theme.tokens(appMode) ?? tokens);
	$effect(() => {
		void theme.resolved;
		const reread = () => {
			const next = readTokens();
			if (JSON.stringify(next) !== JSON.stringify(tokens)) tokens = next;
		};
		reread();
		// <html data-theme> or the media query can settle a frame later.
		const mq = globalThis.matchMedia?.('(prefers-color-scheme: dark)');
		mq?.addEventListener('change', reread);
		const mo = new MutationObserver(reread);
		mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class', 'style'] });
		return () => {
			mq?.removeEventListener('change', reread);
			mo.disconnect();
		};
	});

	let innerWidth = $state(1280);
	const narrow = $derived(innerWidth < 720);

	onMount(() => {
		// A shared or printed link: `?present=1` opens in presentation mode, `?layout=` a layout.
		const search = typeof location === 'undefined' ? '' : location.search;
		presentation.active = presentIn(search);
		urlSynced = true;
		if (publishedVersions === 0) return;
		void controller.theme.load(controller.source.themes?.bind(controller.source));
		// The survey's default layout opens first; without one (or if the list fails), the defaults.
		if (layouts) void layouts.init(layoutIn(search)).then((opened) => (opened ? undefined : controller.load()));
		else void controller.load();
	});
	onDestroy(() => {
		controller.dispose();
		presentation.exit();
	});
</script>

<svelte:window bind:innerWidth onkeydown={onWindowKey} />

<div class="results" class:presenting aria-busy={controller.loading} style={presenting ? themeStyle : undefined} data-presenting={presenting || undefined}>
	<header class="page-head" class:visually-hidden={presenting}>
		<h2 id="results-heading">Results</h2>
		{#if !presenting}
			<p class="lead">
				One card per question, from the responses to the published survey. Counts are of responses, not
				participants.
			</p>
		{/if}
	</header>

	{#if publishedVersions === 0}
		<p class="empty" data-testid="results-unpublished">
			Nothing is published yet. Publish the survey and collect responses to see results here.
		</p>
	{:else}
		{#if !presenting}
			{#if layouts}<LayoutBar {layouts} />{/if}
			<FilterBar {controller} {conditions} {publishedVersions} {narrow} />

			<section class="summary" aria-labelledby="active-filters-h">
				<h3 id="active-filters-h" class="visually-hidden">Active filters</h3>
				<ul class="chips" data-testid="active-filters">
					{#each active as a (a)}<li>{a}</li>{/each}
				</ul>
				<div class="look">
					<ThemePicker theme={controller.theme} mode={appMode} />
				</div>
				{#if response}
					<div class="export-all">
						<ExportAll {controller} />
						<Button bind:ref={presentButton} onclick={() => void present(true)} disabled={!cards.length} aria-keyshortcuts="Escape">
							<Presentation size={16} aria-hidden="true" /> Present
						</Button>
					</div>
					<p class="count" data-testid="results-count">
						{`${response.responses} ${response.responses === 1 ? 'response' : 'responses'}`}{response.split
							? ` · ${response.split.groups.map((g) => `${g.label}: ${g.responses}`).join(', ')}`
							: ''}
					</p>
				{/if}
			</section>
		{:else}
			<button
				bind:this={exitButton}
				type="button"
				class="exit-present"
				data-testid="exit-presentation"
				aria-keyshortcuts="Escape"
				title="Exit presentation (Escape)"
				onclick={() => void present(false)}
			>
				<X size={16} aria-hidden="true" /> Exit presentation
			</button>
		{/if}

		<div class="live" role="status" aria-live="polite">
			{#if controller.loading}
				<span class="waiting" data-testid="results-waiting">
					<span class="spinner" aria-hidden="true"></span>
					{#if slow}
						Computing results… {controller.elapsed} s. Large surveys can take a while.
					{:else}
						Computing results…
					{/if}
				</span>
			{/if}
		</div>
		{#if slow}
			<div><Button onclick={() => controller.cancel()}>Cancel</Button></div>
		{/if}

		{#if controller.error}
			<div class="error" role="alert" data-testid="results-error">
				<p>
					{#if controller.error.status === 403}
						You need owner or editor access to this survey to see its results.
					{:else}
						{controller.error.message}
					{/if}
				</p>
				<Button onclick={() => void controller.load()}>Try again</Button>
			</div>
		{/if}

		{#if response?.warnings?.length && !presenting}
			<ul class="warnings" aria-label="Warnings">
				{#each response.warnings as w, i (i)}<li data-code={w.code}>{w.message}</li>{/each}
			</ul>
		{/if}

		{#if notices.length && !presenting}
			<ul class="warnings" aria-label="Layout notices" data-testid="layout-notices">
				{#each notices as n (n.question)}<li>{n.message}</li>{/each}
			</ul>
		{/if}

		{#if response}
			{#if cards.length}
				<p id="{uid}-move-help" class="visually-hidden">
					Drag the handle, or focus it and press the up or down arrow key, to move the card. Home and End move it
					to the start or end.
				</p>
				<div class="visually-hidden" role="status" aria-live="polite" data-testid="move-status">{moveMessage}</div>
				<ol class="cards" aria-label="Questions" style={presenting ? undefined : themeStyle} data-theme-mode={pageTheme ? themeMode : undefined}>
					{#each cards as card, i (card.question)}
						{@const name = nameOf(card)}
						{@const hidden = controller.charts.hidden(card.question)}
						{#if presenting}
							{#if !hidden}
								<li data-question={card.question}>
									<ResultCard {card} {controller} tokens={chartTokens} presenting />
								</li>
							{/if}
						{:else}
						<li
							class:over={over === card.question && dragging !== card.question}
							class:dragging={dragging === card.question}
							data-question={card.question}
							ondragover={(e) => {
								if (!dragging) return;
								e.preventDefault();
								over = card.question;
							}}
							ondragleave={() => {
								if (over === card.question) over = null;
							}}
							ondrop={(e) => onDrop(e, card.question)}
						>
							{#snippet handle()}
								<button
									type="button"
									class="tool handle"
									draggable="true"
									data-move={card.question}
									aria-label="Move {name}"
									aria-describedby="{uid}-move-help"
									title="Drag, or use the arrow keys, to move"
									onkeydown={(e) => onHandleKey(e, card.question, i)}
									ondragstart={(e) => {
										dragging = card.question;
										e.dataTransfer?.setData('text/plain', card.question);
										if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
									}}
									ondragend={() => {
										dragging = null;
										over = null;
									}}
								>
									<GripVertical size={16} aria-hidden="true" />
								</button>
							{/snippet}
							{#if hidden}
								<div class="hidden-card" data-testid="hidden-card">
									{@render handle()}
									<span class="hidden-name"><span class="visually-hidden">Hidden: </span>{name}</span>
									<button
										type="button"
										class="tool show"
										data-show={card.question}
										aria-label="Show {name}"
										onclick={() => hide(card.question, false)}
									>
										<Eye size={16} aria-hidden="true" /> Show
									</button>
								</div>
							{:else}
								<ResultCard {card} {controller} tokens={chartTokens}>
									{#snippet tools()}
										{@render handle()}
										<button
											type="button"
											class="tool"
											data-hide={card.question}
											aria-label="Hide {name}"
											title="Hide this card"
											onclick={() => hide(card.question, true)}
										>
											<EyeOff size={16} aria-hidden="true" />
										</button>
									{/snippet}
								</ResultCard>
							{/if}
						</li>
						{/if}
					{/each}
				</ol>
			{:else}
				<p class="empty">This version has no questions to show.</p>
			{/if}
		{/if}
	{/if}
</div>

<style>
	.results {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		max-width: 64rem;
		margin: 0 auto;
		padding: var(--space-5) var(--space-4) var(--space-6);
		color: var(--color-text);
	}
	.page-head h2 {
		margin: 0;
		font-size: var(--text-lg);
	}
	.lead,
	.count {
		margin: var(--space-1) 0 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.empty {
		padding: var(--space-4);
		border: 1px dashed var(--color-border-strong);
		border-radius: var(--radius-md);
		color: var(--color-text-muted);
	}
	.summary {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.export-all {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin-top: var(--space-2);
	}
	.look {
		margin-top: var(--space-2);
	}
	/* Presentation mode (V6): only the cards, on the theme's background, with a way out. */
	.results.presenting {
		min-height: 100vh;
		max-width: none;
		padding-top: var(--space-4);
		background: var(--color-bg);
		font-family: var(--font-sans);
	}
	.results.presenting .cards {
		max-width: 64rem;
		margin: 0 auto;
		width: 100%;
	}
	.exit-present {
		position: fixed;
		right: var(--space-3);
		bottom: var(--space-3);
		z-index: 10;
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		min-height: 2.75rem;
		padding: 0 var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-full);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
		box-shadow: var(--shadow-md, 0 1px 3px rgb(0 0 0 / 0.2));
		cursor: pointer;
	}
	.exit-present:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}
	@media print {
		.exit-present {
			display: none;
		}
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.chips li {
		padding: 2px var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-full);
		background: var(--color-surface-sunken);
		font-size: var(--text-xs);
	}
	.live:empty {
		display: none;
	}
	.waiting {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
	}
	.spinner {
		width: 1rem;
		height: 1rem;
		border: 2px solid var(--color-border-strong);
		border-top-color: var(--color-accent);
		border-radius: var(--radius-full);
		animation: spin 0.9s linear infinite;
	}
	@media (prefers-reduced-motion: reduce) {
		.spinner {
			animation: none;
		}
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	.error {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-3);
		padding: var(--space-3);
		border: 1px solid var(--color-danger);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
	}
	.error p {
		margin: 0;
	}
	.warnings {
		margin: 0;
		padding: var(--space-2) var(--space-3) var(--space-2) var(--space-5);
		border-inline-start: 4px solid var(--color-warning);
		background: var(--color-surface-raised);
		font-size: var(--text-sm);
	}
	.cards {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.cards > li {
		min-width: 0;
		border-radius: var(--radius-md);
	}
	.cards > li.over {
		outline: 2px dashed var(--color-accent);
		outline-offset: 2px;
	}
	.cards > li.dragging {
		opacity: 0.6;
	}
	.hidden-card {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-1) var(--space-2);
		border: 1px dashed var(--color-border-strong);
		border-radius: var(--radius-md);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.hidden-name {
		flex: 1 1 auto;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.tool {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-1);
		min-width: 2.75rem;
		min-height: 2.75rem;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
		cursor: pointer;
	}
	.tool.handle {
		cursor: grab;
	}
	.tool:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}
	@media (max-width: 30rem) {
		.results {
			padding-inline: var(--space-3);
		}
	}
</style>
