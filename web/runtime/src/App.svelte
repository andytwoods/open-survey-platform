<script lang="ts">
	import { announcer, resolveMode, themeDataAttributes, themeToCssVars, THEME_PRESETS, type Theme } from '@osp/ui-components';
	import { onMount, tick } from 'svelte';
	import { httpApi } from './lib/api';
	import { resolveApiBase } from './lib/api-base';
	import ErrorSummary from './lib/ErrorSummary.svelte';
	import { browserHooks } from './lib/hooks';
	import { keyboard } from './lib/keyboard.svelte';
	import { fill, negotiateLanguage, STRINGS, ui, useLanguage } from './lib/messages';
	import Question from './lib/Question.svelte';
	import { boot, BootError, type Env, type Session } from './lib/session';
	import { localStorageBackup, localStoragePointer, MemoryStore, openIndexedDb, sessionPointer } from './lib/storage';
	import { domId, errorText, plain } from './lib/view-map';
	import AnswerSummary from './lib/AnswerSummary.svelte';
	import ConsentPage from './lib/ConsentPage.svelte';
	import EndRedirect from './lib/EndRedirect.svelte';
	import EndScreen from './lib/EndScreen.svelte';
	import Withdraw from './lib/Withdraw.svelte';
	import { declinedConsent, type Device } from '@osp/engine';
	import type { PreviewMount } from './lib/preview-mount';

	/** Preview mode (B11): run on a given plan with no server and memory-only storage. */
	let { preview }: { preview?: PreviewMount } = $props();

	let session = $state.raw<Session | null>(null);
	let bootError = $state.raw<BootError | null>(null);
	/** Bumped on every session change: the session is a plain object, not reactive. */
	let version = $state(0);
	let drafts = $state<Record<string, string | undefined>>({});
	let heading = $state<HTMLElement | null>(null);
	let summary = $state<HTMLElement | null>(null);
	let navHeight = $state(0);
	let copied = $state(false);
	let slug = '';

	const view = $derived.by(() => {
		void version;
		return session ? session.view() : null;
	});
	const phase = $derived.by(() => {
		void version;
		return session?.phase ?? null;
	});
	const net = $derived.by(() => {
		void version;
		return session?.net ?? null;
	});

	// Items present when the page first rendered; anything that appears later is "revealed".
	let firstItems = new Set<string>();
	let firstKey = '';
	const pageKey = $derived(view ? `${view.page}#${view.trial}` : '');
	const revealed = $derived.by(() => {
		if (!view) return new Set<string>();
		if (pageKey !== firstKey) {
			firstKey = pageKey;
			firstItems = new Set(view.items.map((i) => i.id));
		}
		return new Set(view.items.filter((i) => !firstItems.has(i.id)).map((i) => i.id));
	});

	const errors = $derived.by(() => {
		if (!view) return [];
		const out = view.items
			.filter((i) => i.error)
			.map((i) => ({ id: i.id, domId: domId(i.id), label: plain(i.label), message: errorText(i) ?? '' }));
		// A hook's rejectPage without an item is a page-level message (§7a).
		const pageError = view.page ? view.errors[view.page] : undefined;
		if (pageError) out.unshift({ id: view.page!, domId: '', label: '', message: plain(pageError.message) || ui.constraint });
		return out;
	});
	const sessionNotice = $derived.by(() => {
		void version;
		const n = session?.notice ?? null;
		return n ? { kind: n, text: n === 'conflict' ? ui.conflict : ui.restarted } : null;
	});
	const hookRetry = $derived.by(() => {
		void version;
		return session?.hookRetry ?? false;
	});
	const title = $derived(view ? plain(view.title) : '');
	const resumeLink = $derived(
		session && session.saveMode === 'every-page'
			? `${location.origin}/s/${encodeURIComponent(slug)}#resume=${encodeURIComponent(session.rec.resumeToken)}`
			: ''
	);
	const notice = $derived.by(() => {
		if (!session?.storageBlocked) return '';
		if (session.memory === 'chosen') return ui.memoryChosen;
		return session.saveMode === 'end-only' ? ui.memoryEndOnly : ui.memoryEveryPage;
	});
	const status = $derived.by(() => {
		if (net === 'saved') return ui.saved;
		if (net === 'saving') return ui.saving;
		if (net === 'offline') return session?.storageBlocked ? ui.offlineNoStorage : ui.offline;
		return '';
	});

	// -- focus (§6): heading after navigation, error summary after a failed Next ---------
	let focusOnPage: 'heading' | null = null;
	let lastKey = '';
	let lastReplaced = 0;
	$effect(() => {
		void version;
		const key = `${pageKey}|${phase}`;
		const replaced = session?.replaced ?? 0;
		if (key === lastKey && replaced === lastReplaced) return;
		const changed = lastKey !== '' && key !== lastKey;
		lastKey = key;
		const wasReplaced = replaced !== lastReplaced;
		lastReplaced = replaced;
		if (changed || wasReplaced) drafts = {};
		// Wait out a quota check or the submit: focus goes to what comes after it.
		const waiting = phase === 'pending' || phase === 'hook' || phase === 'submitting';
		if (wasReplaced || (changed && focusOnPage && !waiting)) {
			focusOnPage = null;
			void tick().then(() => heading?.focus());
		}
	});

	async function onNext() {
		if (!session) return;
		focusOnPage = 'heading';
		const outcome = await session.next();
		if (outcome === 'invalid') {
			focusOnPage = null;
			await tick();
			summary?.focus();
			summary?.scrollIntoView({ block: 'start' });
		}
	}
	async function onBack() {
		if (!session) return;
		focusOnPage = 'heading';
		if (!(await session.back())) focusOnPage = null;
	}
	function onAnswer(id: string, value: unknown) {
		// What the widget holds as typed (null: empty or not a number yet).
		drafts[id] = typeof value === 'string' ? value : undefined;
		session?.answer(id, value);
	}
	async function onRetryHook() {
		focusOnPage = 'heading';
		await session?.retryHook();
	}

	// -- theme (§6a) -------------------------------------------------------------------
	const DEFAULT_THEME = (THEME_PRESETS.find((p) => p.id === 'clean') ?? THEME_PRESETS[0]!).theme as Theme;
	/** The theme on screen: the plan's (`plan.theme`, when the survey has one) or the default preset. */
	let currentTheme: Theme = DEFAULT_THEME;
	let darkQuery: MediaQueryList | undefined;
	function paintTheme() {
		const root = document.documentElement;
		const theme = currentTheme;
		const vars = themeToCssVars(theme, resolveMode(theme, !!darkQuery?.matches));
		for (const [k, v] of Object.entries(vars)) root.style.setProperty(k, v);
		// The browser's toolbar colour follows the page background.
		const bg = vars['--color-bg'];
		if (bg) document.querySelector('meta[name="theme-color"]')?.setAttribute('content', bg);
		for (const [k, v] of Object.entries(themeDataAttributes(theme))) root.setAttribute(k, v);
	}
	function applyTheme(theme: Theme) {
		currentTheme = theme;
		if (!darkQuery) {
			darkQuery = window.matchMedia?.('(prefers-color-scheme: dark)');
			darkQuery?.addEventListener?.('change', paintTheme);
		}
		try {
			paintTheme();
		} catch (e) {
			// A theme this app can't read (e.g. a newer format): keep the default preset.
			console.warn('[osp-runtime] theme not applied', e);
			currentTheme = DEFAULT_THEME;
			paintTheme();
		}
	}

	// -- boot ------------------------------------------------------------------------
	function readUrl() {
		const m = /^\/s\/([^/]+)\/?$/.exec(location.pathname);
		const params = [...new URLSearchParams(location.search)];
		slug = m ? decodeURIComponent(m[1]!) : (params.find(([k]) => k === 's')?.[1] ?? '');
		const hash = new URLSearchParams(location.hash.replace(/^#/, ''));
		const resumeToken = hash.get('resume');
		if (resumeToken) {
			// Keep the secret out of the address bar, history and bookmarks.
			history.replaceState(null, '', location.pathname + location.search);
		}
		// EX2: a return from an external task carries osp_token and the task's return values.
		const query = new URLSearchParams(location.search);
		const ospToken = query.get('osp_token');
		let externalReturn: { token: string; values: Record<string, string> } | null = null;
		if (ospToken) {
			const values: Record<string, string> = {};
			for (const [k, v] of query) if (k !== 's' && k !== 'osp_token' && k !== 'osp_return') values[k] = v;
			externalReturn = { token: ospToken, values };
			// Clean osp_* and the return values out of the address bar, keeping only `s`.
			const s = query.get('s');
			history.replaceState(null, '', location.pathname + (s ? `?s=${encodeURIComponent(s)}` : ''));
		}
		const urlParams = Object.fromEntries(
			params.filter(([k]) => k !== 's' && k !== 'osp_token' && k !== 'osp_return')
		);
		return { resumeToken, urlParams, externalReturn };
	}

	/** The host's API prefix (D15), from `<div id="app" data-api-base="…">`. */
	function apiBaseAttr(): string | null {
		return document.getElementById('app')?.getAttribute('data-api-base') ?? null;
	}

	function device(): Device {
		if (window.matchMedia?.('(max-width: 599px)').matches) return 'phone';
		if (window.matchMedia?.('(max-width: 1023px)').matches) return 'tablet';
		return 'desktop';
	}

	async function start() {
		bootError = null;
		const { resumeToken, urlParams, externalReturn } = preview
			? { resumeToken: null, urlParams: {}, externalReturn: null }
			: readUrl();
		if (preview) slug = preview.slug;
		if (!slug) {
			bootError = new BootError('not-found', 'This survey link is not valid.');
			return;
		}
		const apiBase = preview ? { base: '' } : resolveApiBase(apiBaseAttr(), location.origin);
		if ('error' in apiBase) {
			console.warn(`[osp-runtime] ${apiBase.error}`);
			bootError = new BootError('invalid', 'This survey page is set up wrongly.');
			return;
		}
		const store = preview ? null : ((await openIndexedDb()) ?? new MemoryStore());
		const log = (msg: string, detail?: unknown) => console.warn(`[osp-runtime] ${msg}`, detail ?? '');
		const env: Env = preview?.env ?? {
			api: httpApi(apiBase.base),
			store: store!,
			backup: localStorageBackup(),
			pointer: sessionPointer(),
			devicePointer: localStoragePointer(),
			hooks: browserHooks({ slug, log }),
			now: () => Date.now(),
			random: Math.random,
			setTimer: (fn, ms) => setTimeout(fn, ms),
			clearTimer: (h) => clearTimeout(h as number),
			navigate: (u: string) => location.assign(u),
			returnUrl: () => location.origin + location.pathname + location.search,
			log
		};
		const languages = navigator.languages?.length ? navigator.languages : [navigator.language];
		try {
			const s = await boot(env, {
				slug,
				resumeToken,
				urlParams,
				languages: preview?.language ? [preview.language] : languages,
				device: device()
			});
			preview?.onSession?.(s);
			useLanguage(s.view().language);
			const planTheme = (s.plan as unknown as { theme?: Theme }).theme;
			if (planTheme && typeof planTheme === 'object') applyTheme(planTheme);
			s.subscribe(() => version++);
			s.externalReturn = externalReturn; // EX2: consumed by the pending external effect
			session = s;
			(window as unknown as { __osp?: unknown }).__osp = s; // test and debugging hook
			void s.run();
		} catch (e) {
			bootError = e instanceof BootError ? e : new BootError('network', ui.problem);
			if (!(e instanceof BootError)) console.error(e);
		}
	}

	async function startAgain() {
		const store = (await openIndexedDb()) ?? null;
		await store?.delete(slug);
		sessionPointer().clear(slug);
		localStoragePointer()?.clear(slug);
		location.reload();
	}

	async function copyLink() {
		try {
			await navigator.clipboard.writeText(resumeLink);
			copied = true;
		} catch {
			copied = false;
		}
	}

	$effect(() => {
		if (title) document.title = view?.page ? `${title} – ${fill(ui.page, { n: view.trial })}` : title;
	});

	// The end redirect (end-of-survey plan §4.2): the ending's own, or one a hook chose.
	// The session gives it only after this tab's submit was acknowledged; EndRedirect runs
	// the countdown and never navigates from the builder preview (it shows the URL instead).
	const redirect = $derived.by(() => {
		void version;
		return phase === 'done' ? (session?.redirect ?? null) : null;
	});
	// The ending's list of answers (§4.4, EN5): the session gives it only for this tab's own
	// acknowledged submit, never after a decline or a withdrawal.
	const answerList = $derived.by(() => {
		void version;
		return phase === 'done' ? (session?.summary ?? null) : null;
	});

	onMount(() => {
		// The app's own strings before the plan is known: the browser's languages.
		useLanguage(negotiateLanguage(navigator.languages ?? [navigator.language], Object.keys(STRINGS), 'en'));
		(window as unknown as { __ospUi?: unknown }).__ospUi = ui; // Next/Back names for the harness
		applyTheme(DEFAULT_THEME);
		const stopKeyboard = keyboard.start();
		const hidden = () => {
			if (document.visibilityState === 'hidden') {
				session?.flushLocalSync();
				session?.flushKeepalive();
			}
			else {
				session?.wake();
				session?.saveNow();
			}
		};
		const pagehide = () => {
			session?.flushLocalSync();
			session?.flushKeepalive();
			session?.unloading();
		};
		const online = () => session?.wake();
		document.addEventListener('visibilitychange', hidden);
		window.addEventListener('pagehide', pagehide);
		window.addEventListener('online', online);
		void start();
		return () => {
			stopKeyboard();
			document.removeEventListener('visibilitychange', hidden);
			window.removeEventListener('pagehide', pagehide);
			window.removeEventListener('online', online);
		};
	});
</script>

<div class="osp-visually-hidden" aria-live="polite" aria-atomic="true">{announcer.polite}</div>

<div class="shell" style:--nav-h={`${navHeight}px`}>
	{#if bootError}
		<main class="page" id="main">
			<h1 tabindex="-1">{ui.problem}</h1>
			<p>{bootError.message}</p>
			{#if bootError.kind === 'expired'}
				<button type="button" class="btn primary" onclick={startAgain}>{ui.startAgain}</button>
			{:else if bootError.kind === 'network'}
				<button type="button" class="btn primary" onclick={() => location.reload()}>{ui.retry}</button>
			{/if}
		</main>
	{:else if !session || !view}
		<main class="page" id="main" aria-busy="true">
			<p class="muted">{ui.loading}</p>
		</main>
	{:else if view.status === 'consent' || declinedConsent(session.state)}
		<ConsentPage {session} {view} preview={!!preview} />
	{:else if phase === 'done'}
		<main class="page" id="main" lang={view.language}>
			<EndScreen end={view.end} testid="thanks" bind:heading />
			{#if redirect}
				<EndRedirect {redirect} preview={!!preview} />
			{/if}
			{#if answerList}
				<AnswerSummary entries={answerList} />
			{/if}
			<Withdraw {session} {version} />
		</main>
	{:else if phase === 'fatal'}
		<main class="page" id="main">
			<h1 tabindex="-1" bind:this={heading}>{ui.problem}</h1>
			<p>{session.fatal}</p>
		</main>
	{:else if phase === 'submitting'}
		<main class="page" id="main" aria-busy="true">
			<h1 tabindex="-1" bind:this={heading}>{title}</h1>
			<p role="status">{net === 'offline' ? ui.submittingOffline : ui.submitting}</p>
		</main>
	{:else if phase === 'external'}
		<main class="page" id="main" aria-busy="true" data-testid="external-handoff">
			<h1 tabindex="-1" bind:this={heading}>{title}</h1>
			<p role="status">{ui.external}</p>
		</main>
	{:else}
		<main class="page" id="main" lang={view.language} onfocusout={() => session?.blur()}>
			{#if notice}<p class="notice" data-testid="storage-notice">{notice}</p>{/if}
			{#if sessionNotice}
				<!-- R6-6 / R6-5: inserted while the page is shown, so role=alert announces it once. -->
				<p class="notice" role="alert" data-notice={sessionNotice.kind} data-testid="session-notice">{sessionNotice.text}</p>
			{/if}
			{#if hookRetry}
				<div class="notice" role="alert" data-testid="hook-retry">
					<p>{ui.hookRetry}</p>
					<button type="button" class="btn primary" onclick={onRetryHook} disabled={phase !== 'page'}>{ui.retry}</button>
				</div>
			{/if}
			<h1 tabindex="-1" bind:this={heading}>
				{title}
				<span class="pageno">{fill(ui.page, { n: view.trial })}</span>
			</h1>
			{#if errors.length}
				<ErrorSummary {errors} bind:el={summary} />
			{/if}
			{#key pageKey}
				<div class="items" data-page={view.page}>
					{#each view.items as item (item.id)}
						<Question
							{item}
							lang={view.language}
							revealed={revealed.has(item.id)}
							draft={drafts[item.id]}
							multiline={(session.plan.items[item.id] as { multiline?: boolean } | undefined)?.multiline === true}
							onanswer={onAnswer}
						/>
					{/each}
				</div>
			{/key}
			{#if resumeLink}
				<details class="later">
					<summary>{ui.continueLater}</summary>
					<p class="muted">{ui.continueHelp}</p>
					<div class="link-row">
						<input
							class="link"
							readonly
							value={resumeLink}
							aria-label={ui.continueLater}
							data-testid="resume-link"
							onfocus={(e) => e.currentTarget.select()}
						/>
						<button type="button" class="btn" onclick={copyLink}>{copied ? ui.copied : ui.copy}</button>
					</div>
				</details>
				<Withdraw {session} {version} />
			{/if}
		</main>
		<nav class="nav" class:docked={keyboard.open} aria-label="Survey" bind:offsetHeight={navHeight} data-print="hide">
			<div class="nav-inner">
				{#if view.nav?.back}
					<button type="button" class="btn" onclick={onBack} disabled={phase !== 'page'}>{ui.back}</button>
				{/if}
				<span class="status" data-testid="save-status" data-status={net}>{status}</span>
				<button
					type="button"
					class="btn primary"
					onclick={onNext}
					disabled={phase !== 'page'}
					aria-busy={phase === 'pending'}
				>
					{phase === 'pending' ? ui.checking : ui.next}
				</button>
			</div>
		</nav>
	{/if}
</div>

<style>
	:global(html) {
		scroll-padding-block-end: calc(var(--nav-h, 0px) + var(--space-4));
		-webkit-text-size-adjust: 100%;
		text-size-adjust: 100%;
	}
	:global(body) {
		margin: 0;
		background: var(--color-bg);
		color: var(--color-text);
		font-family: var(--font-sans);
		font-size: var(--text-md);
		line-height: var(--leading-normal);
	}
	.shell {
		display: flex;
		flex-direction: column;
		min-block-size: 100dvh;
		scroll-padding-block-end: var(--nav-h);
	}
	.page {
		flex: 1;
		box-sizing: border-box;
		inline-size: 100%;
		max-inline-size: 42rem;
		margin-inline: auto;
		padding-block: var(--space-5) var(--space-6);
		padding-inline: max(var(--space-4), env(safe-area-inset-left)) max(var(--space-4), env(safe-area-inset-right));
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		min-inline-size: 0;
		overflow-wrap: anywhere;
	}
	h1 {
		margin: 0;
		font-size: var(--text-xl);
		line-height: var(--leading-tight);
	}
	h1:focus {
		outline: none;
	}
	h1:focus-visible {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 4px;
	}
	.pageno {
		display: block;
		margin-block-start: var(--space-1);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		font-weight: var(--weight-normal);
	}
	.items {
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
	}
	.muted {
		color: var(--color-text-muted);
	}
	.notice {
		margin: 0;
		padding: var(--space-3);
		border-inline-start: 4px solid var(--color-accent);
		background: var(--color-accent-subtle);
		border-radius: var(--radius-sm);
	}
	.later summary {
		cursor: pointer;
		min-block-size: 2.75rem;
		display: flex;
		align-items: center;
		color: var(--color-accent);
	}
	.later summary:focus-visible {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 2px;
	}
	.link-row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.link {
		flex: 1 1 12rem;
		min-inline-size: 0;
		min-block-size: 2.75rem;
		padding-inline: var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font-size: max(16px, var(--text-md));
	}
	.nav {
		position: sticky;
		inset-block-end: 0;
		z-index: 10;
		background: var(--color-bg);
		border-block-start: 1px solid var(--color-border);
		padding-block: var(--space-3) max(var(--space-3), env(safe-area-inset-bottom));
		padding-inline: max(var(--space-4), env(safe-area-inset-left)) max(var(--space-4), env(safe-area-inset-right));
	}
	/* Keyboard open: the bar sits after the content instead of over it (§6). */
	.nav.docked {
		position: static;
	}
	.nav-inner {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		max-inline-size: 42rem;
		margin-inline: auto;
	}
	.status {
		flex: 1;
		min-inline-size: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		text-align: center;
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
	.btn.primary {
		margin-inline-start: auto;
		border-color: var(--color-accent);
		background: var(--color-accent);
		color: var(--color-on-accent);
	}
	:global([data-osp-button='outline']) .btn.primary {
		background: transparent;
		color: var(--color-accent);
	}
	.btn:hover:not(:disabled) {
		filter: brightness(0.95);
	}
	.btn:disabled {
		opacity: 0.6;
		cursor: progress;
	}
	.btn:focus-visible {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 2px;
	}
	/*
	 * Print (end-of-survey plan §4.4, EN5): the ending and the list of answers on plain paper,
	 * nothing interactive. Buttons, the nav bar, the redirect and Withdraw mark themselves
	 * with data-print="hide". No PDF library: the browser prints (or saves) the page.
	 */
	@media print {
		:global(html),
		:global(body) {
			background: #fff;
			color: #000;
		}
		.shell {
			min-block-size: auto;
		}
		.page {
			max-inline-size: none;
			padding: 0;
			gap: var(--space-4);
		}
		:global([data-print='hide']) {
			display: none !important;
		}
	}
</style>
