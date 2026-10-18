<script lang="ts">
	import Eye from '@lucide/svelte/icons/eye';
	import EyeOff from '@lucide/svelte/icons/eye-off';
	import GripVertical from '@lucide/svelte/icons/grip-vertical';
	import Presentation from '@lucide/svelte/icons/presentation';
	import Radio from '@lucide/svelte/icons/radio';
	import X from '@lucide/svelte/icons/x';
	import { Button, cssVarsToStyle, theme, themeToCssVars } from '@osp/ui-components';
	import { onDestroy, onMount, tick, untrack } from 'svelte';
	import LayoutBar from './LayoutBar.svelte';
	import { LayoutsController } from './layouts.svelte';
	import type { Card } from './types';
	import { readTokens } from './charts/theme';
	import type { ThemeTokens } from './charts/types';
	import ExportAll from './export/ExportAll.svelte';
	import { suppressCard } from './export/model';
	import FilterBar from './FilterBar.svelte';
	import { IDLE_AFTER_MS, liveIn, liveModeIn, pendingText, presentFooter, statusText, withLive, type PresentRefresh } from './live';
	import { conditionVariables, describeOutcomes } from './model';
	import { layoutIn, presentIn, withPresent } from './presentation';
	import { presentation } from './presentation.svelte';
	import PresentDialog from './PresentDialog.svelte';
	import ResultCard from './ResultCard.svelte';
	import { surveyThemeOf } from './results-theme';
	import { apiSource, ResultsController, type ResultsSource } from './results.svelte';
	import { enterFullscreen, exitFullscreen, keepAwake } from './screen';
	import ThemePicker from './ThemePicker.svelte';

	/**
	 * The Results page (task V2, planning/results-viewer.md): a filter bar, the active
	 * filters in words, and one card per question in survey order. Every number is the
	 * server's (V1); this page only asks and draws. Lazily loaded by the shell. Task V6
	 * adds the page's own theme (the cards and every export are drawn in it) and a
	 * presentation mode that shows only the cards (`?present=1`, Escape to leave). Task LV3
	 * adds Live: the page polls the watermark and refreshes as responses arrive (by itself
	 * when idle; a "N new responses · Refresh" badge while the researcher is busy). Task LV4
	 * makes presentation mode live too, through the Present dialog: refreshes in batches (k
	 * new responses or the time cap) with small cells hidden on screen by default, a footer
	 * with the count and time (never the size of a delta), fullscreen and a wake lock.
	 */
	let {
		surveyId,
		survey,
		publishedVersions,
		source,
		minRefreshMs
	}: {
		surveyId: string;
		/** The survey draft: its assigned variables give the condition filter's options, its theme the "survey's theme" option. */
		survey: unknown;
		publishedVersions: number;
		/** Where results come from (default: the API). */
		source?: ResultsSource;
		/** Live: the least time between automatic refreshes (tests shorten it). */
		minRefreshMs?: number;
	} = $props();

	// The source and version count are fixed for the page's life (a new publish reloads).
	// svelte-ignore state_referenced_locally
	const controller = new ResultsController(source ?? apiSource(surveyId), publishedVersions, { minRefreshMs });
	const live = controller.live;

	// -- live (LV3): busy means badge, not yank ----------------------------------------------
	/** When the researcher last touched the page (plain: read at poll time, never rendered). */
	let lastActivity = 0;
	const touch = () => (lastActivity = Date.now());
	controller.busyCheck = () =>
		Date.now() - lastActivity < IDLE_AFTER_MS ||
		!!document.querySelector('[role="dialog"][data-state="open"], [role="menu"], [role="listbox"][data-state="open"]');
	const liveStatus = $derived(
		live
			? statusText({
					status: live.status,
					intervalMs: live.intervalMs,
					retryMs: live.retryMs,
					error: live.error,
					lastRefreshAt: live.lastRefreshAt
				})
			: ''
	);
	/** One polite line per automatic refresh, never per card. */
	const announce = $derived.by(() => {
		const u = controller.liveUpdate;
		if (!u) return '';
		return `Results updated: ${u.responses} ${u.responses === 1 ? 'response' : 'responses'}.`;
	});
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

	// -- presentation mode (V6, live in LV4) ---------------------------------------------------
	const presenting = $derived(presentation.active);
	let presentButton = $state<HTMLButtonElement | null>(null);
	let exitButton = $state<HTMLButtonElement | null>(null);
	let presentDialog = $state(false);
	let urlSynced = false;
	$effect(() => {
		// Mirror the flag into the URL once the page has read its initial state.
		const on = presentation.active;
		if (!urlSynced || typeof history === 'undefined') return;
		const next = withPresent(location.href, on);
		if (next !== location.href) history.replaceState(history.state, '', next);
	});
	/** Start presenting with the dialog's choices (LV-D5); a palette toggle or `?present=1` take the defaults. */
	async function present(on: boolean, choice?: { live: boolean; refresh: PresentRefresh; exact: boolean; fullscreen: boolean }) {
		if (on) {
			if (choice) live?.set(choice.live);
			presentation.enter(choice);
			if (choice?.fullscreen) void enterFullscreen();
		} else {
			presentation.exit();
			void exitFullscreen();
		}
		await tick();
		(on ? exitButton : presentButton)?.focus();
	}
	/** The cards as shown: presenting, cells below k are hidden on screen (LV-D5) unless exact counts were chosen. */
	const shownCards = $derived(
		cards.map((card) => {
			const k = presentation.k;
			if (k === null) return { card, hidden: 0 };
			const s = suppressCard($state.snapshot(card) as Card, k);
			return { card: s.card, hidden: s.hidden };
		})
	);
	/** The projected footer: count and time, never "N new" (LV-D5). */
	const footer = $derived(
		controller.response
			? presentFooter({ responses: controller.response.responses, updatedAt: controller.receivedAt, live: live?.on ?? false, k: presentation.k })
			: ''
	);
	$effect(() => {
		// A live lab screen stays awake (ignored where the browser does not allow it).
		if (!presentation.active || !live?.on || typeof navigator === 'undefined') return;
		return keepAwake();
	});
	function onWindowKey(e: KeyboardEvent) {
		touch();
		if (!presenting || e.key !== 'Escape' || e.defaultPrevented) return;
		// Escape inside an open dialog closes only the dialog.
		if (document.querySelector('[role="dialog"][data-state="open"]')) return;
		e.preventDefault();
		void present(false);
	}
	$effect(() => {
		// Mirror the live flag (and the presentation cadence, LV4) into the URL once the page has
		// read its initial state (LV3). The suppression switch is never in the URL.
		const on = live?.on ?? false;
		const mode = presentation.refresh;
		if (!urlSynced || typeof history === 'undefined') return;
		const next = withLive(location.href, on, mode);
		if (next !== location.href) history.replaceState(history.state, '', next);
	});
	$effect(() => {
		// Entering or leaving presentation mode, or changing its cadence, changes the live policy:
		// check now. Only the flags are dependencies: wake() reads and writes the poller's own state.
		void presentation.active;
		void presentation.refresh;
		untrack(() => live?.wake());
	});

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
		// `?live=` in a shared link wins over the layout's setting; absent, the layout decides.
		// `?live=every|batched` also carries the presentation cadence (never the suppression switch).
		const urlLive = liveIn(search);
		const urlMode = liveModeIn(search);
		if (urlMode) presentation.refresh = urlMode;
		urlSynced = true;
		if (publishedVersions === 0) return;
		void controller.theme.load(controller.source.themes?.bind(controller.source));
		// The survey's default layout opens first; without one (or if the list fails), the defaults.
		const first = layouts ? layouts.init(layoutIn(search)).then((opened) => (opened ? true : controller.load())) : controller.load();
		void first.then(() => {
			if (urlLive !== null) live?.set(urlLive);
		});
	});
	onDestroy(() => {
		controller.dispose();
		presentation.exit();
	});
</script>

<svelte:window bind:innerWidth onkeydown={onWindowKey} onpointerdown={touch} onpointermove={touch} onwheel={touch} />

<div class="results" class:presenting aria-busy={controller.loading} style={presenting ? themeStyle : undefined} data-presenting={presenting || undefined}>
	<header class="page-head" class:visually-hidden={presenting}>
		<!-- Presenting, the top bar (and its h1) is gone: this heading becomes the page's h1. -->
		<svelte:element this={presenting ? 'h1' : 'h2'} id="results-heading">Results</svelte:element>
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
						<Button bind:ref={presentButton} onclick={() => (presentDialog = true)} disabled={!cards.length} aria-haspopup="dialog">
							<Presentation size={16} aria-hidden="true" /> Present
						</Button>
					</div>
					<p class="count" data-testid="results-count">
						{`${response.responses} ${response.responses === 1 ? 'response' : 'responses'}`}{response.split
							? ` · ${response.split.groups.map((g) => `${g.label}: ${g.responses}`).join(', ')}`
							: ''}
					</p>
					{#if response.outcomes?.length}
						<!-- Every submitted response of the versions used, by how it ended (EN4): before any filter. -->
						<p
							class="count outcomes"
							data-testid="results-outcomes"
							title="Every submitted response of the versions used, by how the session ended, before filters"
						>
							By outcome: {describeOutcomes(response.outcomes)}
						</p>
					{/if}
				{/if}
				{#if live}
					<div class="live-bar" data-testid="live-bar">
						<button
							type="button"
							class="switch"
							role="switch"
							aria-checked={live.on}
							data-testid="live-toggle"
							title={live.on ? 'Stop checking for new responses' : 'Refresh as responses arrive'}
							onclick={() => live.set(!live.on)}
						>
							<Radio size={16} aria-hidden="true" />
							<span>Live</span>
							<span class="switch-state" aria-hidden="true">{live.on ? 'on' : 'off'}</span>
						</button>
						{#if liveStatus}
							<span class="live-status" data-testid="live-status">{liveStatus}</span>
						{/if}
						{#if live.on && live.changed}
							<span class="new-badge" data-testid="live-badge">{pendingText(live.pending)}</span>
							<Button size="sm" disabled={controller.loading} onclick={() => void live.refreshNow()}>Refresh</Button>
						{/if}
					</div>
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
		<div class="visually-hidden" role="status" aria-live="polite" data-testid="live-announce">{announce}</div>

		<div class="live" role="status" aria-live="polite">
			{#if controller.loading && (!controller.quiet || slow)}
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
					{#each shownCards as shown, i (shown.card.question)}
						{@const card = shown.card}
						{@const name = nameOf(card)}
						{@const hidden = controller.charts.hidden(card.question)}
						{@const pulse = controller.pulsing.includes(card.question)}
						{#if presenting}
							{#if !hidden}
								<li data-question={card.question}>
									<ResultCard {card} {controller} tokens={chartTokens} presenting {pulse} k={presentation.k} hiddenCells={shown.hidden} />
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
								<ResultCard {card} {controller} tokens={chartTokens} {pulse}>
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
			{#if presenting && footer}
				<p class="present-footer" data-testid="present-footer">{footer}</p>
			{/if}
		{/if}
	{/if}
</div>
<!-- Outside the non-presenting branch, so starting a presentation does not unmount the open dialog. -->
<PresentDialog bind:open={presentDialog} hasLive={!!live} liveOn={live?.on ?? false} onstart={(choice) => void present(true, choice)} />

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
	.page-head h2,
	.page-head h1 {
		margin: 0;
		font-size: var(--text-lg);
	}
	.lead,
	.count {
		margin: var(--space-1) 0 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.outcomes {
		margin-top: 0;
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
	/* Live (LV3): the switch, its status in words, and the "N new responses · Refresh" badge. */
	.live-bar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-3);
		margin-top: var(--space-2);
		font-size: var(--text-sm);
	}
	.switch {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		min-height: 2.75rem;
		padding: 0 var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-full);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
		cursor: pointer;
	}
	.switch[aria-checked='true'] {
		border-color: var(--color-accent);
		background: var(--color-selected);
	}
	.switch:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}
	.switch-state {
		padding: 1px var(--space-2);
		border-radius: var(--radius-full);
		background: var(--color-surface-sunken);
		color: var(--color-text-muted);
		font-weight: var(--weight-normal);
	}
	.switch[aria-checked='true'] .switch-state {
		background: var(--color-accent);
		color: var(--color-on-accent, #fff);
	}
	.live-status {
		color: var(--color-text-muted);
	}
	.new-badge {
		padding: 2px var(--space-2);
		border: 1px solid var(--color-accent);
		border-radius: var(--radius-full);
		font-weight: var(--weight-medium);
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
	/* The projected footer (LV4): the count and when the screen was drawn; never the delta. */
	.present-footer {
		max-width: 64rem;
		width: 100%;
		margin: 0 auto;
		padding-bottom: var(--space-6);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		font-variant-numeric: tabular-nums;
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
