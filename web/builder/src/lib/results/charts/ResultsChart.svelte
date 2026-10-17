<script lang="ts">
	// One Vega-Lite chart (planning/results-viewer.md V-D1). The spec comes from `buildSpec`;
	// this only draws it: SVG renderer, no actions menu, the theme's config applied (the app
	// theme re-read from the tokens whenever light/dark changes), and the old view finalized
	// on every re-embed. vega-embed is imported on first use, so the chart library is its own
	// lazy chunk. Expressions run through Vega's interpreter (`ast`), so the page CSP needs no
	// 'unsafe-eval'. The figure is labelled by `title` and described by `description`; the
	// card's Table view (V2) is the full accessible alternative.
	import type { View } from 'vega';
	import type { TopLevelSpec } from 'vega-lite';
	import { defaultTokens, readTokens, themeConfig } from './theme';
	import type { ChartTheme, ThemeTokens } from './types';

	interface Props {
		spec: TopLevelSpec;
		theme?: ChartTheme;
		/**
		 * The colours to draw with (task V6: a results theme). Without them the app theme
		 * reads the page's tokens and the export theme uses the publication look.
		 */
		tokens?: ThemeTokens;
		title: string;
		description?: string;
		/** Called with each new view (e.g. for SVG / PNG export). */
		onview?: (view: View) => void;
	}

	let { spec, theme = 'app', tokens, title, description = '', onview }: Props = $props();

	const uid = $props.id();
	let host: HTMLDivElement | undefined = $state();
	let error = $state<string | null>(null);
	let status = $state<'loading' | 'ready' | 'error'>('loading');
	/** Bumped when the app's light/dark tokens change, to re-embed with the new colours. */
	let tokenTick = $state(0);
	/** A chart wider than its card scrolls sideways; the scroller is then focusable (keyboard). */
	let scrollable = $state(false);
	const measure = () => {
		if (host) scrollable = host.scrollWidth > host.clientWidth + 1;
	};

	$effect(() => {
		const el = host;
		if (!el || typeof ResizeObserver !== 'function') return;
		const ro = new ResizeObserver(measure);
		ro.observe(el);
		return () => ro.disconnect();
	});

	$effect(() => {
		if (theme !== 'app' || tokens) return;
		const bump = () => tokenTick++;
		const mq = globalThis.matchMedia?.('(prefers-color-scheme: dark)');
		mq?.addEventListener('change', bump);
		const mo = new MutationObserver(bump);
		mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class', 'style'] });
		return () => {
			mq?.removeEventListener('change', bump);
			mo.disconnect();
		};
	});

	$effect(() => {
		const el = host;
		const t = theme;
		const given = tokens;
		void tokenTick;
		if (!el) return;
		const final = {
			...spec,
			description: description || (spec as { description?: string }).description || title,
			config: themeConfig(t, given ?? (t === 'app' ? readTokens(el) : undefined))
		} as TopLevelSpec;
		// Each embed draws into its own child, so a slow old embed can never overwrite a new one.
		const target = document.createElement('div');
		target.className = 'osp-chart-view';
		el.append(target);
		let cancelled = false;
		let finalize: (() => void) | null = null;
		status = 'loading';
		import('vega-embed')
			.then(({ default: embed }) =>
				embed(target, final, { renderer: 'svg', actions: false, ast: true, defaultStyle: false, downloadFileName: 'chart' })
			)
			.then((result) => {
				if (cancelled) return result.finalize();
				finalize = result.finalize;
				error = null;
				status = 'ready';
				el.style.minHeight = '';
				measure();
				onview?.(result.view);
			})
			.catch((e: unknown) => {
				if (cancelled) return;
				error = e instanceof Error ? e.message : String(e);
				status = 'error';
				el.style.minHeight = '';
			});
		return () => {
			cancelled = true;
			finalize?.();
			// A re-embed (new numbers from a live refresh, a theme change) keeps the figure's
			// height until the new SVG is drawn, so the page never jumps or scrolls (LV3).
			const h = el.offsetHeight;
			if (h > 0) el.style.minHeight = `${h}px`;
			target.remove();
		};
	});
</script>

<figure
	class="osp-chart"
	class:export={theme === 'export'}
	style:background={theme === 'export' ? (tokens ?? defaultTokens('export')).bg : undefined}
	style:color={theme === 'export' ? (tokens ?? defaultTokens('export')).text : undefined}
	aria-labelledby="{uid}-t"
	aria-describedby={description ? `${uid}-d` : undefined}
	data-status={status}
>
	<figcaption class="osp-visually-hidden" id="{uid}-t">{title}</figcaption>
	{#if description}<p class="osp-visually-hidden" id="{uid}-d">{description}</p>{/if}
	<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
	<div class="host" bind:this={host} tabindex={scrollable ? 0 : undefined}></div>
	{#if error}<p class="error" role="alert">The chart could not be drawn: {error}</p>{/if}
</figure>

<style>
	.osp-chart {
		margin: 0;
		min-width: 0;
		max-width: 100%;
	}
	.host {
		width: 100%;
		overflow-x: auto;
	}
	.host :global(.osp-chart-view) {
		width: 100%;
	}
	.host :global(svg) {
		display: block;
		max-width: none;
	}
	.error {
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
</style>
