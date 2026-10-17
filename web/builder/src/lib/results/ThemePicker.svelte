<script lang="ts">
	import { THEME_PRESETS, type Mode } from '@osp/ui-components';
	import { parseThemeKey, themeKey } from './results-theme';
	import type { ResultsTheme } from './results-theme.svelte';

	/**
	 * The Results page's theme (task V6): the app's colours, this survey's theme, a built-in
	 * preset or a lab library theme. Says what is showing and warns when the theme's colours
	 * fail the chart contrast checks (text 4.5:1, bars and axes 3:1 on the background).
	 */
	let { theme, mode }: { theme: ResultsTheme; mode: Mode } = $props();

	const uid = $props.id();
	const resolved = $derived(theme.resolved);
	const problems = $derived(theme.problems(mode));
	const value = $derived(themeKey(theme.choice));
	/** A library theme the layout names but the library no longer has: keep it listed so the select shows it. */
	const missing = $derived(theme.choice.kind === 'library' && !theme.library.some((t) => t.id === (theme.choice as { id: string }).id) ? theme.choice.id : null);
</script>

<div class="theme-picker" data-testid="theme-picker">
	<label for="{uid}-theme">Theme</label>
	<select id="{uid}-theme" {value} onchange={(e) => theme.choose(parseThemeKey((e.currentTarget as HTMLSelectElement).value))} aria-describedby="{uid}-note">
		<option value="app">App colours (default)</option>
		<option value="survey">This survey’s theme</option>
		<optgroup label="Presets">
			{#each THEME_PRESETS as p (p.id)}<option value="preset:{p.id}">{p.name}</option>{/each}
		</optgroup>
		{#if theme.library.length || missing}
			<optgroup label="Lab theme library">
				{#each theme.library as t (t.id)}
					<option value="library:{t.id}">{t.name}{t.id === theme.labDefaultId ? ' (lab default)' : ''}</option>
				{/each}
				{#if missing}<option value="library:{missing}">(deleted theme)</option>{/if}
			</optgroup>
		{/if}
	</select>
	<p class="note" id="{uid}-note" data-testid="theme-note">
		{resolved.name}{resolved.theme ? `, ${theme.mode(mode)} colours` : ''}. Used for the cards and every export.
		{#if theme.error}
			The lab theme library could not be listed: {theme.error}
		{/if}
	</p>
	{#if resolved.notice}
		<p class="warning" role="status" data-testid="theme-notice">{resolved.notice}</p>
	{/if}
	{#if problems.length}
		<p class="warning" role="status" data-testid="theme-contrast">
			{`This theme fails ${problems.length === 1 ? 'a contrast check' : `${problems.length} contrast checks`} for charts: ${problems
				.map((p) => `${p.what} (${p.ratio}:1, needs ${p.required}:1)`)
				.join('; ')}. Figures may be hard to read.`}
		</p>
	{/if}
</div>

<style>
	.theme-picker {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1) var(--space-2);
		min-width: 0;
		max-width: 100%;
	}
	label {
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}
	select {
		max-width: 100%;
		min-width: 0;
		min-height: 2.75rem;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
	}
	select:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}
	.note,
	.warning {
		flex-basis: 100%;
		margin: 0;
		font-size: var(--text-xs);
	}
	.note {
		color: var(--color-text-muted);
	}
	.warning {
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-inline-start: 4px solid var(--color-warning);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font-size: var(--text-sm);
	}
</style>
