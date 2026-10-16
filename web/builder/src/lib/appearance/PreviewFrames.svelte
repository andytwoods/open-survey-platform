<script lang="ts">
	import {
		themeDataAttributes,
		themeToCssVars,
		type Mode,
		type Theme
	} from '@osp/ui-components';
	import SamplePage from './SamplePage.svelte';

	/**
	 * The sample page at phone, tablet and desktop widths side by side, each drawn at its
	 * real width and scaled down to fit. Frames are aria-hidden and inert (a picture of the
	 * page); the caption above them says in words what they show.
	 */
	let { theme, mode, header }: { theme: Theme; mode: Mode; header: string } = $props();

	const FRAMES = [
		{ id: 'phone', label: 'Phone', px: 375 },
		{ id: 'tablet', label: 'Tablet', px: 768 },
		{ id: 'desktop', label: 'Desktop', px: 1280 }
	] as const;
	const GAP = 16;
	const TOTAL = FRAMES.reduce((s, f) => s + f.px, 0);

	let width = $state(0);
	const heights = $state<Record<string, number>>({});
	const scale = $derived(width ? Math.min(1, (width - GAP * (FRAMES.length - 1)) / TOTAL) : 0.4);
	const vars = $derived(themeToCssVars(theme, mode));
	const attrs = $derived(themeDataAttributes(theme));
	const style = $derived(Object.entries(vars).map(([k, v]) => `${k}: ${v}`).join('; '));
</script>

<div class="frames" bind:clientWidth={width} style:gap="{GAP}px">
	{#each FRAMES as f (f.id)}
		<figure class="frame-wrap" style:inline-size="{f.px * scale}px">
			<figcaption>{f.label} · {f.px} px</figcaption>
			<div class="viewport" style:block-size="{(heights[f.id] ?? 1600) * scale}px">
				<div
					class="frame"
					aria-hidden="true"
					inert
					data-frame={f.id}
					data-mode={mode}
					style="{style}; width: {f.px}px; transform: scale({scale})"
					{...attrs}
					bind:offsetHeight={heights[f.id]}
				>
					<SamplePage {header} uid={f.id} />
				</div>
			</div>
		</figure>
	{/each}
</div>

<style>
	.frames {
		display: flex;
		align-items: flex-start;
	}
	.frame-wrap {
		margin: 0;
		flex: none;
	}
	figcaption {
		margin-block-end: var(--space-1);
		font-size: var(--text-xs);
		color: var(--color-text-muted);
		white-space: nowrap;
	}
	.viewport {
		overflow: hidden;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-sm);
	}
	.frame {
		container-type: inline-size;
		transform-origin: top left;
		background: var(--color-bg);
		color: var(--color-text);
		font-family: var(--font-sans);
		font-size: var(--text-md);
		line-height: var(--leading-normal);
	}
</style>
