<script lang="ts">
	import { page } from '$app/state';
	import {
		THEME_DEFAULTS,
		THEME_PRESETS,
		themeDataAttributes,
		themeToCssVars,
		type Mode,
		type ThemePreset
	} from '@osp/ui-components';

	// Developer gallery of the theme presets on sample question widgets, at phone and
	// desktop widths (axe-checked per preset in e2e/themes.spec.ts).
	// ?preset=<id> shows one preset; ?mode=light|dark one mode.
	const WIDTHS = [
		{ id: 'phone', label: 'Phone, 360 px', px: 360 },
		{ id: 'desktop', label: 'Desktop, 880 px', px: 880 }
	] as const;

	const presetFilter = $derived(page.url.searchParams.get('preset'));
	const modeFilter = $derived(page.url.searchParams.get('mode'));
	const presets = $derived(
		THEME_PRESETS.filter((p) => !presetFilter || p.id === presetFilter)
	);

	function modesOf(preset: ThemePreset): Mode[] {
		const mode = preset.theme.mode ?? THEME_DEFAULTS.mode;
		const all: Mode[] = mode === 'auto' ? ['light', 'dark'] : [mode];
		return all.filter((m) => !modeFilter || m === modeFilter);
	}

	function frameStyle(preset: ThemePreset, mode: Mode, px: number): string {
		const vars = themeToCssVars(preset.theme, mode);
		return [...Object.entries(vars), ['width', `${px}px`]].map(([k, v]) => `${k}: ${v}`).join('; ');
	}

	const OPTIONS = ['Not at all', 'A little', 'Quite a lot', 'Very much'];
	// One pre-selected answer per frame, so the selected style is visible.
	const answers = $state<Record<string, string>>(
		Object.fromEntries(
			THEME_PRESETS.flatMap((p) =>
				(['light', 'dark'] as const).flatMap((m) =>
					WIDTHS.map((w) => [`${p.id}-${m}-${w.id}`, OPTIONS[2]])
				)
			)
		)
	);
</script>

<svelte:head>
	<title>Themes · Open Survey Platform</title>
</svelte:head>

<main class="gallery">
	<h1>Theme gallery</h1>
	<p class="intro">
		Each preset applied to sample question widgets through <code>themeToCssVars</code>. Every
		preset passes the WCAG AA contrast guard in both modes.
	</p>

	{#each presets as preset (preset.id)}
		<section class="preset" aria-labelledby="h-{preset.id}" data-preset={preset.id}>
			<h2 id="h-{preset.id}">{preset.name}</h2>
			{#each modesOf(preset) as mode (mode)}
				<div class="frames">
					{#each WIDTHS as width (width.id)}
						{@const key = `${preset.id}-${mode}-${width.id}`}
						<section
							class="frame"
							aria-labelledby="h-{key}"
							style={frameStyle(preset, mode, width.px)}
							{...themeDataAttributes(preset.theme)}
							data-frame={key}
						>
							<h3 id="h-{key}" class="frame-label">
								{mode === 'dark' ? 'Dark' : 'Light'} · {width.label}
							</h3>
							<header class="survey-header">
								<span class="logo" aria-hidden="true"></span>
								<span>Sleep and wellbeing study</span>
							</header>

							<div class="survey-page">
								<p class="page-title">Page 2 of 5</p>

								<fieldset class="question">
									<legend>How rested do you feel today?</legend>
									<p class="hint" id="hint-{key}">Choose one answer.</p>
									<div class="choices">
										{#each OPTIONS as option (option)}
											<label class="choice">
												<input
													type="radio"
													name="rested-{key}"
													value={option}
													aria-describedby="hint-{key}"
													bind:group={answers[key]}
												/>
												<span>{option}</span>
											</label>
										{/each}
									</div>
								</fieldset>

								<div class="question">
									<label for="hours-{key}" class="q-label">How many hours did you sleep?</label>
									<p class="hint" id="hours-hint-{key}">A whole number, e.g. 7.</p>
									<input
										id="hours-{key}"
										class="text-input"
										inputmode="numeric"
										enterkeyhint="next"
										aria-describedby="hours-hint-{key} hours-err-{key}"
										aria-invalid="true"
										value="seven-ish"
									/>
									<p class="error" id="hours-err-{key}">Enter a number of hours, like 7.</p>
								</div>

								<p class="hint">
									Questions? Read the <a href="#h-{key}">study information</a>.
								</p>

								<nav class="survey-nav" aria-label="Survey navigation, {key}">
									<button type="button" class="nav-button secondary">Back</button>
									<button type="button" class="nav-button primary">Next</button>
								</nav>
							</div>
						</section>
					{/each}
				</div>
			{/each}
		</section>
	{/each}
</main>

<style>
	.gallery {
		padding: var(--space-6) var(--space-4);
	}
	h1 {
		font-size: var(--text-xl);
		margin: 0 0 var(--space-2);
	}
	.intro {
		color: var(--color-text-muted);
		margin: 0 0 var(--space-6);
	}
	.preset h2 {
		font-size: var(--text-lg);
		margin: var(--space-6) 0 var(--space-3);
	}
	.frames {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-start;
		gap: var(--space-5);
		margin-block-end: var(--space-5);
	}

	/* --- Inside a frame: drawn only from the theme's tokens ---------------------------- */
	.frame {
		container-type: inline-size;
		max-width: 100%;
		background: var(--color-bg);
		color: var(--color-text);
		font-family: var(--font-sans);
		font-size: var(--text-md);
		line-height: var(--leading-normal);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		overflow: hidden;
	}
	.frame-label {
		margin: 0;
		padding: var(--space-1) var(--space-3);
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
		color: var(--color-text-muted);
		background: var(--color-surface);
		border-block-end: 1px solid var(--color-border);
	}
	.survey-header {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
		font-weight: var(--weight-bold);
		border-block-end: 1px solid var(--color-border);
	}
	.logo {
		inline-size: 1.75rem;
		block-size: 1.75rem;
		border-radius: var(--radius-sm);
		background: var(--color-accent);
	}
	.survey-page {
		max-width: 42rem;
		margin-inline: auto;
		padding: var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}
	@container (min-width: 600px) {
		.survey-page {
			padding: var(--space-6);
		}
	}
	.page-title {
		margin: 0;
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}
	.question {
		margin: 0;
		padding: var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		min-inline-size: 0;
	}
	legend,
	.q-label {
		display: block;
		font-size: var(--text-lg);
		font-weight: var(--weight-medium);
		line-height: var(--leading-tight);
		padding: 0;
	}
	.hint {
		margin: var(--space-1) 0 var(--space-3);
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}
	.hint a {
		color: var(--color-accent);
	}
	.error {
		margin: var(--space-2) 0 0;
		font-size: var(--text-sm);
		color: var(--color-danger);
	}

	/* Choices: list (default) */
	.choices {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.choice {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-block-size: var(--osp-touch-target);
		padding-inline: var(--space-2);
		border-radius: var(--radius-sm);
		cursor: pointer;
	}
	.choice:hover {
		background: var(--color-surface-sunken);
	}
	.choice input {
		inline-size: 1.25rem;
		block-size: 1.25rem;
		margin: 0;
		accent-color: var(--color-accent);
	}
	/* Cards */
	[data-osp-choice='cards'] .choices {
		gap: var(--space-2);
	}
	[data-osp-choice='cards'] .choice {
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
	}
	[data-osp-choice='cards'] .choice:has(input:checked) {
		background: var(--color-selected);
		border-color: var(--color-accent);
		box-shadow: inset 0 0 0 1px var(--color-accent);
	}
	/* Buttons: a wrapping row; the radio stays focusable, the label shows the state */
	[data-osp-choice='buttons'] .choices {
		flex-flow: row wrap;
		gap: var(--space-2);
	}
	[data-osp-choice='buttons'] .choice {
		justify-content: center;
		padding: 0 var(--space-4);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		font-weight: var(--weight-medium);
	}
	[data-osp-choice='buttons'] .choice input {
		position: absolute;
		opacity: 0;
		inline-size: 1px;
		block-size: 1px;
	}
	[data-osp-choice='buttons'] .choice:has(input:checked) {
		background: var(--color-accent);
		border-color: var(--color-accent);
		color: var(--color-on-accent);
	}
	[data-osp-choice='buttons'] .choice:has(input:focus-visible) {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 2px;
	}

	.text-input {
		display: block;
		inline-size: 100%;
		max-inline-size: 16rem;
		min-block-size: var(--control-height);
		padding: 0 var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-size: var(--osp-input-font-size);
	}
	.text-input[aria-invalid='true'] {
		border-color: var(--color-danger);
		border-width: 2px;
	}

	.survey-nav {
		display: flex;
		justify-content: space-between;
		gap: var(--space-3);
		padding-block-start: var(--space-2);
	}
	.nav-button {
		min-block-size: var(--control-height);
		min-inline-size: 6rem;
		padding: 0 var(--space-5);
		border-radius: var(--radius-md);
		font: inherit;
		font-weight: var(--weight-medium);
		cursor: pointer;
	}
	.nav-button.secondary {
		background: var(--color-surface-raised);
		color: var(--color-text);
		border: 1px solid var(--color-border-strong);
	}
	.nav-button.primary {
		background: var(--color-accent);
		color: var(--color-on-accent);
		border: 2px solid var(--color-accent);
	}
	.nav-button.primary:hover {
		background: var(--color-accent-hover);
		border-color: var(--color-accent-hover);
	}
	[data-osp-button='outline'] .nav-button.primary {
		background: transparent;
		color: var(--color-accent);
	}
	[data-osp-button='outline'] .nav-button.primary:hover {
		background: var(--color-accent-subtle);
	}
	.frame :focus-visible {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 2px;
	}
</style>
