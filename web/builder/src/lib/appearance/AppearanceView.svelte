<script lang="ts">
	import Download from '@lucide/svelte/icons/download';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Upload from '@lucide/svelte/icons/upload';
	import {
		Button,
		FONT_STACKS,
		THEME_PRESETS,
		announce,
		toast,
		type ButtonStyle,
		type ChoiceStyle,
		type Density,
		type FontId,
		type Mode,
		type PaletteField,
		type PresetId,
		type ThemeMode
	} from '@osp/ui-components';
	import { onMount, tick } from 'svelte';
	import ChoiceGroup from './ChoiceGroup.svelte';
	import ColourField from './ColourField.svelte';
	import { MIN_INPUT_FONT_PX, byPointer, type ThemeDiagnostic } from './guard';
	import PreviewFrames from './PreviewFrames.svelte';
	import RangeField from './RangeField.svelte';
	import { themeEditor as ed } from './theme-editor.svelte';
	import type { ImportProblem } from './validate';

	/**
	 * Appearance: edit the survey theme (runtime-design §6a). Controls on the left, a live
	 * preview at three widths on the right. Every change goes through the theme editor store
	 * (undo/redo via the shell's commands); the guard runs on every change.
	 */

	const MAIN_COLOURS: { field: PaletteField; label: string }[] = [
		{ field: 'accent', label: 'Accent' },
		{ field: 'background', label: 'Background' }
	];
	const MORE_COLOURS: { field: PaletteField; label: string }[] = [
		{ field: 'surface', label: 'Cards and panels' },
		{ field: 'text', label: 'Text' },
		{ field: 'muted', label: 'Hints and borders' },
		{ field: 'error', label: 'Error messages' },
		{ field: 'focus', label: 'Focus ring' }
	];
	const LABELS: Record<PaletteField, string> = Object.fromEntries(
		[...MAIN_COLOURS, ...MORE_COLOURS].map((c) => [c.field, c.label])
	) as Record<PaletteField, string>;
	const FONT_LABELS: Record<FontId, string> = {
		'system-sans': 'Sans',
		'system-serif': 'Serif',
		'system-rounded': 'Rounded'
	};

	let editMode = $state<Mode>('light');
	let moreOpen = $state(false);
	let importProblems = $state<ImportProblem[]>([]);
	let fileInput: HTMLInputElement | null = $state(null);

	const t = $derived(ed.theme);
	const shownMode = $derived<Mode>(t.mode === 'auto' ? editMode : t.mode);
	const problems = $derived(byPointer(ed.diagnostics));
	const contrastPointers = $derived([...new Set(ed.contrastProblems.map((d) => d.pointer))]);
	const fontProblem = $derived(problems.get('/baseSize')?.[0]);
	const headerText = $derived(
		typeof t.headerText === 'string'
			? t.headerText
			: t.headerText
				? (Object.values(t.headerText)[0] ?? '')
				: ''
	);
	const previewHeader = $derived(headerText || 'Sleep and wellbeing study');
	const presetName = $derived(THEME_PRESETS.find((p) => p.id === t.preset)?.name ?? 'Custom');
	const summary = $derived(
		`Preview of a sample survey page in the ${presetName} theme, ${shownMode} colours, ` +
			`${FONT_LABELS[t.font].toLowerCase()} type at ${t.baseSize} px with line spacing ${t.lineSpacing}, ` +
			`${t.radius} px corners, ${t.density} spacing, ${t.buttonStyle} buttons and ${t.choiceStyle} ` +
			`choices, shown at phone, tablet and desktop widths.`
	);

	// Open "More colours" whenever one of its colours fails, so the fix is visible.
	$effect(() => {
		if (MORE_COLOURS.some((c) => problems.has(`/colours/${shownMode}/${c.field}`))) moreOpen = true;
	});

	onMount(() => ed.openOnce());

	const problemsFor = (mode: Mode, field: PaletteField) =>
		problems.get(`/colours/${mode}/${field}`) ?? [];

	function describePointer(ptr: string) {
		const [, , mode, field] = ptr.split('/');
		return `${mode === 'dark' ? 'Dark' : 'Light'} colours · ${LABELS[field as PaletteField] ?? field}`;
	}

	async function goTo(ptr: string) {
		const [, , mode, field] = ptr.split('/');
		if (t.mode === 'auto') editMode = mode as Mode;
		if (MORE_COLOURS.some((c) => c.field === field)) moreOpen = true;
		await tick();
		document.getElementById(`colour-${mode}-${field}`)?.focus();
	}

	function fix(d: ThemeDiagnostic) {
		ed.applySuggestion(d);
		announce(`Applied ${d.suggestion}.`);
	}

	function exportJson() {
		const blob = new Blob([ed.toJson()], { type: 'application/json' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `theme-${t.preset ?? 'custom'}.json`;
		a.click();
		setTimeout(() => URL.revokeObjectURL(url), 0);
	}

	async function importFile(file: File | undefined) {
		if (!file) return;
		let text: string;
		try {
			text = await file.text();
		} catch {
			importProblems = [{ pointer: '/', message: 'Could not read the file.' }];
			return;
		}
		const res = ed.importJson(text);
		importProblems = res.problems;
		if (res.ok) toast(`Imported theme from ${file.name}.`);
		if (fileInput) fileInput.value = '';
	}
</script>

<div class="appearance">
	<section class="controls" aria-labelledby="appearance-heading" data-pane="appearance-controls">
		<div class="controls-head">
			<h2 id="appearance-heading">Appearance</h2>
			<p class="lead">How the survey looks to participants.</p>
		</div>

		<div class="banner" role="status" data-state={ed.canPublish ? 'ok' : 'blocked'} data-testid="guard-banner">
			{#if ed.canPublish}
				<p><strong>Ready to publish.</strong> Every colour pair meets WCAG AA contrast.</p>
			{:else}
				<p>
					<strong>
						Can't publish:
						{#if contrastPointers.length}
							{contrastPointers.length} contrast {contrastPointers.length === 1 ? 'problem' : 'problems'}
						{/if}
						{#if contrastPointers.length && fontProblem}and{/if}
						{#if fontProblem}text below {MIN_INPUT_FONT_PX} px{/if}
					</strong>
				</p>
				<ul>
					{#each contrastPointers as ptr (ptr)}
						<li>
							<button type="button" class="link" onclick={() => goTo(ptr)}>{describePointer(ptr)}</button>
						</li>
					{/each}
				</ul>
			{/if}
		</div>

		<section class="group" aria-labelledby="h-preset">
			<h3 id="h-preset">Start from a preset</h3>
			<div class="presets" role="radiogroup" aria-labelledby="h-preset">
				{#each THEME_PRESETS as p (p.id)}
					{@const pal = p.theme.colours[p.theme.mode === 'dark' ? 'dark' : 'light']}
					<label class="preset">
						<input
							type="radio"
							name="preset"
							value={p.id}
							checked={t.preset === p.id}
							onchange={() => ed.applyPreset(p.id as PresetId)}
						/>
						<span class="preset-card">
							<span class="swatches" aria-hidden="true">
								<span style:background={pal.background}></span>
								<span style:background={pal.surface}></span>
								<span style:background={pal.accent}></span>
								<span style:background={pal.text}></span>
							</span>
							<span>{p.name}</span>
						</span>
					</label>
				{/each}
			</div>
		</section>

		<section class="group" aria-labelledby="h-brand">
			<h3 id="h-brand">Brand</h3>
			{#if t.mode === 'auto'}
				<ChoiceGroup
					legend="Colours for"
					name="edit-mode"
					description="The survey follows each participant's device, so it needs light and dark colours."
					options={[
						{ value: 'light', label: 'Light' },
						{ value: 'dark', label: 'Dark' }
					]}
					value={editMode}
					onchange={(v) => (editMode = v)}
				/>
			{/if}
			{#each MAIN_COLOURS as c (c.field)}
				<ColourField
					id="colour-{shownMode}-{c.field}"
					label={c.label}
					value={t.colours[shownMode][c.field]}
					problems={problemsFor(shownMode, c.field)}
					onchange={(hex) => ed.setColour(shownMode, c.field, hex)}
					onfix={fix}
				/>
			{/each}
			<details bind:open={moreOpen}>
				<summary>More colours</summary>
				<div class="stack">
					{#each MORE_COLOURS as c (c.field)}
						<ColourField
							id="colour-{shownMode}-{c.field}"
							label={c.label}
							value={t.colours[shownMode][c.field]}
							problems={problemsFor(shownMode, c.field)}
							onchange={(hex) => ed.setColour(shownMode, c.field, hex)}
							onfix={fix}
						/>
					{/each}
				</div>
			</details>

			<div class="field">
				<label for="header-text">Header text</label>
				<input
					id="header-text"
					class="text"
					type="text"
					value={headerText}
					placeholder="e.g. Sleep and wellbeing study"
					oninput={(e) => ed.set('headerText', e.currentTarget.value || null)}
				/>
			</div>

			<div class="field">
				<span class="label" id="logo-label">Logo</span>
				<div class="logo-row">
					<span class="logo-placeholder" aria-hidden="true"></span>
					<Button size="sm" disabled aria-labelledby="logo-label logo-btn" aria-describedby="logo-note">
						<Upload size={14} aria-hidden="true" /><span id="logo-btn">Upload logo</span>
					</Button>
				</div>
				<p class="note" id="logo-note">
					Coming soon: logos are uploaded to and served from our own server. The preview shows a placeholder.
				</p>
			</div>
		</section>

		<section class="group" aria-labelledby="h-type">
			<h3 id="h-type">Type</h3>
			<ChoiceGroup
				legend="Font"
				name="font"
				description="System fonts: nothing is downloaded from other sites."
				options={(Object.keys(FONT_LABELS) as FontId[]).map((f) => ({ value: f, label: FONT_LABELS[f] }))}
				value={t.font}
				onchange={(v) => ed.set('font', v)}
			>
				{#snippet option(opt)}<span style:font-family={FONT_STACKS[opt.value]}>{opt.label}</span>{/snippet}
			</ChoiceGroup>
			<RangeField
				label="Base size"
				value={Math.max(MIN_INPUT_FONT_PX, t.baseSize)}
				min={MIN_INPUT_FONT_PX}
				max={32}
				unit=" px"
				description="Text inputs never go below 16 px."
				onchange={(v) => ed.set('baseSize', Math.max(MIN_INPUT_FONT_PX, v))}
			/>
			{#if fontProblem}
				<div class="inline-problem" role="group" aria-label="Base size problem">
					<p>{fontProblem.message}</p>
					<Button size="sm" onclick={() => fix(fontProblem)}>Use {MIN_INPUT_FONT_PX} px</Button>
				</div>
			{/if}
			<RangeField
				label="Line spacing"
				value={t.lineSpacing}
				min={1}
				max={2.5}
				step={0.05}
				onchange={(v) => ed.set('lineSpacing', Math.round(v * 100) / 100)}
			/>
		</section>

		<section class="group" aria-labelledby="h-shape">
			<h3 id="h-shape">Shape and density</h3>
			<RangeField
				label="Corner radius"
				value={t.radius}
				min={0}
				max={32}
				unit=" px"
				onchange={(v) => ed.set('radius', v)}
			/>
			<ChoiceGroup
				legend="Spacing"
				name="density"
				options={[
					{ value: 'comfortable', label: 'Comfortable' },
					{ value: 'compact', label: 'Compact' }
				] as { value: Density; label: string }[]}
				value={t.density}
				onchange={(v) => ed.set('density', v)}
			/>
			<ChoiceGroup
				legend="Buttons"
				name="button"
				options={[
					{ value: 'filled', label: 'Filled' },
					{ value: 'outline', label: 'Outline' }
				] as { value: ButtonStyle; label: string }[]}
				value={t.buttonStyle}
				onchange={(v) => ed.set('buttonStyle', v)}
			/>
			<ChoiceGroup
				legend="Choices"
				name="choice"
				options={[
					{ value: 'list', label: 'List' },
					{ value: 'cards', label: 'Cards' },
					{ value: 'buttons', label: 'Buttons' }
				] as { value: ChoiceStyle; label: string }[]}
				value={t.choiceStyle}
				onchange={(v) => ed.set('choiceStyle', v)}
			/>
		</section>

		<section class="group" aria-labelledby="h-mode">
			<h3 id="h-mode">Mode</h3>
			<ChoiceGroup
				legend="Light or dark"
				name="mode"
				options={[
					{ value: 'light', label: 'Light' },
					{ value: 'dark', label: 'Dark' },
					{ value: 'auto', label: 'Follow device' }
				] as { value: ThemeMode; label: string }[]}
				value={t.mode}
				onchange={(v) => ed.set('mode', v)}
			/>
		</section>

		<section class="group" aria-labelledby="h-file">
			<h3 id="h-file">Save and share</h3>
			<p class="note">Your changes are kept as a draft in this browser. Saving to the lab theme library comes later.</p>
			<div class="actions">
				<Button size="sm" onclick={exportJson}><Download size={14} aria-hidden="true" />Export JSON</Button>
				<Button size="sm" onclick={() => fileInput?.click()}><Upload size={14} aria-hidden="true" />Import JSON</Button>
				<Button size="sm" variant="ghost" onclick={() => ed.reset()}><RotateCcw size={14} aria-hidden="true" />Reset</Button>
			</div>
			<input
				bind:this={fileInput}
				type="file"
				accept="application/json,.json"
				hidden
				data-testid="theme-import"
				onchange={(e) => importFile(e.currentTarget.files?.[0])}
			/>
			{#if importProblems.length}
				<div class="import-problems" role="alert">
					<p><strong>That file isn't a valid theme.</strong> Nothing was changed.</p>
					<ul>
						{#each importProblems.slice(0, 8) as p, i (i)}
							<li><code>{p.pointer}</code>: {p.message}</li>
						{/each}
					</ul>
					{#if importProblems.length > 8}<p>…and {importProblems.length - 8} more.</p>{/if}
				</div>
			{/if}
		</section>
	</section>

	<section class="preview" aria-labelledby="h-preview" data-pane="appearance-preview">
		<h2 id="h-preview">Preview</h2>
		<p class="summary" data-testid="preview-summary">{summary}</p>
		<PreviewFrames theme={t} mode={shownMode} header={previewHeader} />
	</section>
</div>

<style>
	.appearance {
		display: grid;
		grid-template-columns: minmax(18rem, 24rem) 1fr;
		height: 100%;
		min-height: 0;
	}
	.controls {
		overflow: auto;
		padding: var(--space-4);
		border-inline-end: 1px solid var(--color-border);
		background: var(--color-surface);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}
	.controls > :global(*) {
		flex-shrink: 0;
	}
	.preview {
		overflow: auto;
		padding: var(--space-4) var(--space-5);
		background: var(--color-bg);
		min-width: 0;
	}
	h2 {
		margin: 0;
		font-size: var(--text-lg);
	}
	.lead,
	.summary,
	.note {
		margin: var(--space-1) 0 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.summary {
		margin-block-end: var(--space-4);
		max-width: 60rem;
	}
	.note {
		font-size: var(--text-xs);
	}
	.group {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding-block-start: var(--space-3);
		border-block-start: 1px solid var(--color-border);
	}
	h3 {
		margin: 0;
		font-size: var(--text-sm);
		font-weight: var(--weight-bold);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-muted);
	}
	.stack {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding-block-start: var(--space-3);
	}
	summary {
		cursor: pointer;
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
		min-block-size: 1.5rem;
	}
	summary:focus-visible,
	.link:focus-visible,
	.text:focus-visible,
	.preset input:focus-visible + .preset-card {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 2px;
	}

	.banner {
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-md);
		border: 1px solid var(--color-border-strong);
		border-inline-start-width: 4px;
		background: var(--color-surface-raised);
		font-size: var(--text-sm);
	}
	.banner[data-state='ok'] {
		border-color: var(--color-success);
	}
	.banner[data-state='blocked'] {
		border-color: var(--color-danger);
	}
	.banner p {
		margin: 0;
	}
	.banner ul {
		margin: var(--space-1) 0 0;
		padding-inline-start: var(--space-4);
	}
	.link {
		padding: 0;
		border: 0;
		background: none;
		color: var(--color-accent);
		font: inherit;
		text-decoration: underline;
		cursor: pointer;
		min-block-size: 1.5rem;
	}

	.presets {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(6.5rem, 1fr));
		gap: var(--space-2);
	}
	.preset {
		position: relative;
		display: flex;
	}
	.preset input {
		position: absolute;
		inset: 0;
		opacity: 0;
		margin: 0;
		cursor: pointer;
	}
	.preset-card {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		padding: var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		font-size: var(--text-sm);
	}
	.preset input:checked + .preset-card {
		border-color: var(--color-accent);
		box-shadow: inset 0 0 0 1px var(--color-accent);
		background: var(--color-selected);
		font-weight: var(--weight-medium);
	}
	.swatches {
		display: flex;
		block-size: 1rem;
		border-radius: var(--radius-sm);
		overflow: hidden;
		border: 1px solid var(--color-border);
	}
	.swatches span {
		flex: 1;
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.field label,
	.label {
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}
	.text {
		min-block-size: 2.25rem;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-md);
	}
	.logo-row {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.logo-placeholder {
		inline-size: 2.25rem;
		block-size: 2.25rem;
		border: 1px dashed var(--color-border-strong);
		border-radius: var(--radius-md);
	}
	.inline-problem,
	.import-problems {
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-danger);
		border-inline-start-width: 4px;
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		font-size: var(--text-xs);
	}
	.inline-problem p,
	.import-problems p {
		margin: 0 0 var(--space-2);
	}
	.import-problems ul {
		margin: 0;
		padding-inline-start: var(--space-4);
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	@media (max-width: 900px) {
		.appearance {
			grid-template-columns: 1fr;
			grid-template-rows: auto auto;
			overflow: auto;
		}
		.controls,
		.preview {
			overflow: visible;
		}
	}
</style>
