<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { api } from '../api';
	import { defaultLanguage } from '../model/outline';
	import PropertyPanel from '../properties/PropertyPanel.svelte';
	import { fetchPropertySchemas, propertySchemas, schemaFor } from '../properties/schemas.svelte';
	import type { SurveyStore } from '../sync/survey-store.svelte';
	import ConsentEditor from './ConsentEditor.svelte';
	import { LOCAL_COPIES, SAVE_MODES, localCopyOf, saveModeOf } from './explanations';
	import HooksEditor from './HooksEditor.svelte';
	import LanguagesField from './LanguagesField.svelte';
	import { retentionOp, subsetSchema, type RetentionKind } from './model';
	import RetentionField from './RetentionField.svelte';

	/**
	 * Survey settings (task B12): saving, navigation and resume, retention, languages and
	 * consent, researcher hooks. Fields the property schema describes are drawn by the
	 * schema-driven property panel (B4); retention, languages, consent and hooks need their
	 * own controls. Every change is an op through the survey store.
	 */
	let { store, onpreview }: { store: SurveyStore; onpreview?: () => void } = $props();

	const lang = $derived(defaultLanguage(store.survey));
	const surveySchema = $derived(schemaFor(propertySchemas.doc, 'survey', store.survey));
	const savingSchema = $derived(
		surveySchema &&
			subsetSchema(surveySchema, ['settings.saveMode', 'settings.localCopy'], 'Save options', 'How answers are saved')
	);
	const navSchema = $derived(
		surveySchema &&
			subsetSchema(
				surveySchema,
				['settings.backNavigation', 'settings.resumeExpiryDays'],
				'Navigation and resume',
				'What participants can do part-way through'
			)
	);
	const diagnostics = $derived([...store.diagnostics, ...(store.rejection?.diagnostics ?? [])]);

	const mode = $derived(saveModeOf(store.survey));
	const copy = $derived(localCopyOf(store.survey));
	const explanation = $derived(SAVE_MODES[mode]);

	let kinds = $state<RetentionKind[]>([]);
	let retentionError = $state<string | null>(null);

	onMount(() => {
		void propertySchemas.load(fetchPropertySchemas);
		void (async () => {
			try {
				const { data } = await api.GET('/api/meta/retention');
				if (data) kinds = data.kinds as RetentionKind[];
				else retentionError = 'Retention options could not be loaded.';
			} catch {
				retentionError = 'Retention options could not be loaded.';
			}
		})();
		// A publish problem links here with #retention (or #consent, #languages).
		const target = location.hash.slice(1);
		if (target)
			void tick().then(() => {
				const el = document.getElementById(`settings-${target}`);
				el?.scrollIntoView?.({ block: 'start' });
				el?.focus();
			});
	});

	let panels = $state<(PropertyPanel | null)[]>([null, null]);
	$effect(() => store.registerBuffer({ flush: () => panels.forEach((p) => p?.flush()) }));
</script>

<div class="settings">
	<header>
		<h2 id="settings-heading">Survey settings</h2>
		<p class="lead">
			How the survey saves, what participants can do, how long data is kept, consent, and researcher hooks.
		</p>
	</header>

	<section class="card" aria-labelledby="h-saving">
		<h3 id="h-saving">Saving responses</h3>
		{#if savingSchema && propertySchemas.doc}
			<PropertyPanel
				bind:this={panels[0]}
				schema={savingSchema}
				target={store.survey}
				language={lang}
				{diagnostics}
				groups={['Save options']}
				onOp={(op) => void store.submit([op])}
				onDirty={(d) => store.markDirty(d)}
			/>
		{:else}
			<p class="muted">Loading…</p>
		{/if}
		<div class="explain" data-mode={mode} data-testid="save-mode-explanation" role="status" aria-live="polite">
			<p class="explain-title"><strong>{explanation.title}.</strong> {explanation.summary}</p>
			<ul>
				{#each explanation.tradeOffs as t (t)}<li>{t}</li>{/each}
			</ul>
			{#if mode === 'end-only'}
				<p class="copy"><strong>Copy on the device:</strong> {LOCAL_COPIES[copy]}</p>
			{/if}
		</div>
	</section>

	<section class="card" aria-labelledby="h-nav">
		<h3 id="h-nav">Moving through the survey</h3>
		{#if navSchema && propertySchemas.doc}
			<PropertyPanel
				bind:this={panels[1]}
				schema={navSchema}
				target={store.survey}
				language={lang}
				{diagnostics}
				groups={['Navigation and resume']}
				onOp={(op) => void store.submit([op])}
				onDirty={(d) => store.markDirty(d)}
			/>
		{/if}
	</section>

	<section class="card" aria-labelledby="h-retention">
		<h3 id="h-retention">Data retention</h3>
		<RetentionField
			survey={store.survey}
			{kinds}
			loadError={retentionError}
			onsave={(v) => void store.submit([retentionOp(v)])}
		/>
	</section>

	<section class="card" aria-labelledby="h-languages" id="settings-languages" tabindex="-1">
		<h3 id="h-languages">Languages</h3>
		<LanguagesField survey={store.survey} submit={(ops) => store.submit(ops)} />
	</section>

	<section class="card" aria-labelledby="h-consent" id="settings-consent" tabindex="-1">
		<h3 id="h-consent">Consent</h3>
		<ConsentEditor survey={store.survey} defaultLanguage={lang} submit={(ops) => store.submit(ops)} />
	</section>

	<section class="card" aria-labelledby="h-hooks" id="settings-hooks" tabindex="-1">
		<h3 id="h-hooks">Researcher hooks</h3>
		<HooksEditor survey={store.survey} {diagnostics} submit={(ops) => store.submit(ops)} {onpreview} />
	</section>
</div>

<style>
	.settings {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		max-width: 52rem;
		margin: 0 auto;
		padding: var(--space-5) var(--space-4) var(--space-6);
	}
	h2 {
		margin: 0;
		font-size: var(--text-lg);
	}
	.lead,
	.muted {
		margin: var(--space-1) 0 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.card {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding: var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}
	.card:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}
	h3 {
		margin: 0;
		font-size: var(--text-md);
	}
	.explain {
		padding: var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-inline-start-width: 4px;
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		font-size: var(--text-sm);
	}
	.explain[data-mode='end-only'] {
		border-inline-start-color: var(--color-warning);
	}
	.explain p {
		margin: 0;
	}
	.explain ul {
		margin: var(--space-2) 0 0;
		padding-inline-start: var(--space-4);
	}
	.copy {
		margin-top: var(--space-2) !important;
	}
</style>
