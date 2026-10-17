<script lang="ts">
	import { DPI_CHOICES, MAX_MM, MIN_MM, pixelWidth, WIDTH_PRESETS } from './model';
	import type { ExportSettings } from './settings.svelte';

	/**
	 * The export settings both dialogs share (task V4): final width (85 mm, 180 mm or
	 * custom), PNG resolution, and "Hide counts below k" (off by default, V-D4).
	 */
	let {
		settings,
		size = true,
		dpi = true,
		heightPx = null
	}: {
		settings: ExportSettings;
		/** Show the width choice (figures). */
		size?: boolean;
		/** Show the DPI choice (PNG). */
		dpi?: boolean;
		/** The PNG's pixel height at the current settings, when known. */
		heightPx?: number | null;
	} = $props();

	const uid = $props.id();
	const px = $derived(pixelWidth(settings.widthMm, settings.dpi));
</script>

{#if size}
	<fieldset class="group">
		<legend>Final width</legend>
		{#each WIDTH_PRESETS as p (p.id)}
			<label class="check"><input type="radio" value={p.id} bind:group={settings.widthPreset} /> {p.label}</label>
		{/each}
		<label class="check"><input type="radio" value="custom" bind:group={settings.widthPreset} /> Custom</label>
		{#if settings.widthPreset === 'custom'}
			<label class="inline" for="{uid}-mm">
				Width in mm
				<input
					id="{uid}-mm"
					type="number"
					min={MIN_MM}
					max={MAX_MM}
					step="1"
					bind:value={settings.customMm}
					aria-describedby="{uid}-mm-hint"
				/>
			</label>
			<span class="hint" id="{uid}-mm-hint">{MIN_MM} to {MAX_MM} mm</span>
		{/if}
	</fieldset>
{/if}

{#if dpi}
	<fieldset class="group">
		<legend>PNG resolution</legend>
		{#each DPI_CHOICES as d (d)}
			<label class="check"><input type="radio" value={d} bind:group={settings.dpi} /> {d} DPI</label>
		{/each}
		<p class="hint" data-testid="png-size">
			{settings.widthMm} mm at {settings.dpi} DPI = {px}{heightPx ? ` × ${heightPx}` : ''} pixels
		</p>
	</fieldset>
{/if}

<fieldset class="group">
	<legend>Small counts</legend>
	<label class="check"><input type="checkbox" bind:checked={settings.hide} /> Hide counts below k</label>
	{#if settings.hide}
		<label class="inline" for="{uid}-k">
			k
			<input id="{uid}-k" type="number" min="2" max="1000" step="1" bind:value={settings.kValue} />
		</label>
	{/if}
</fieldset>

<style>
	.group {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
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
	.check,
	.inline {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		min-height: 2.75rem;
		font-size: var(--text-sm);
	}
	input[type='number'] {
		width: 5.5rem;
		min-height: 2.5rem;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
	}
	input:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}
	.hint {
		flex-basis: 100%;
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
</style>
