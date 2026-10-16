<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { announce, Announcer, Button, Dialog, PaneResizer, Tabs, theme, toast } from '@osp/ui-components';
	import { api } from '../api';
	import DiagnosticsStrip from '../diagnostics/DiagnosticsStrip.svelte';
	import { ExportCheckState, type CheckResult } from '../diagnostics/export-check.svelte';
	import { propertyFocus } from '../diagnostics/focus.svelte';
	import { exportBadges, ownerOf, SURVEY_ID, type ExportBadge, type Owner } from '../diagnostics/model';
	import { JsonDraft } from '../json/json-draft.svelte';
	import JsonView from '../json/JsonView.svelte';
	import AppearanceView from '../appearance/AppearanceView.svelte';
	import { appearanceCommands, type BuilderView } from '../appearance/commands';
	import { themeEditor } from '../appearance/theme-editor.svelte';
	import { onDestroy, onMount, tick, untrack } from 'svelte';
	import { CommandRegistry } from '../commands/registry';
	import { detectMac } from '../commands/shortcut';
	import { health } from '../health.svelte';
	import { MOCK_SURVEY } from '../mock/survey';
	import { addedQuestionId, allIds, outlineFromSurvey, surveyTitle, targetPage } from '../model/outline';
	import { selection } from '../selection.svelte';
	import type { SurveyStore } from '../sync/survey-store.svelte';
	import ConflictBanner from './ConflictBanner.svelte';
	import CanvasPane from './CanvasPane.svelte';
	import CommandPalette from './CommandPalette.svelte';
	import { shellCommands } from './commands';
	import OutlineTree from './OutlineTree.svelte';
	import { cyclePane } from './panes';
	import PropertiesPane from './PropertiesPane.svelte';
	import TopBar from './TopBar.svelte';

	/**
	 * Which view fills the area under the top bar (each has its own route), and the survey
	 * being edited. Without a store the shell shows the static mock tree (`?mock`).
	 */
	let { view = 'editor', store = null }: { view?: BuilderView; store?: SurveyStore | null } = $props();
	const editing = $derived(view === 'editor');

	// Below these widths a pane collapses and opens as an overlay from the top bar.
	const PROPERTIES_BREAKPOINT = 1024;
	const OUTLINE_BREAKPOINT = 720;

	const registry = new CommandRegistry({
		isMac: detectMac(),
		isModalOpen: () => paletteOpen || previewOpen
	});
	const mockPages = MOCK_SURVEY.children ?? [];
	const pages = $derived(store ? outlineFromSurvey(store.survey) : mockPages);
	const title = $derived(store ? surveyTitle(store.survey) || store.title : MOCK_SURVEY.label);

	// Selection survives patches; it is cleared only when its object is gone (deleted, undone).
	$effect(() => {
		if (store && selection.id && selection.id !== SURVEY_ID && !allIds(pages).has(selection.id)) selection.clear();
	});

	// A rejected edit (422): say so, visibly and to screen readers.
	$effect(() => {
		const r = store?.rejection;
		if (!r) return;
		const n = r.diagnostics.length;
		const text = n ? `${r.message} ${n === 1 ? r.diagnostics[0].message : `${n} problems.`}` : r.message;
		// untrack: toast() reads the toast list it writes.
		untrack(() => toast(text, { kind: 'error' }));
	});

	// JSON view (B9) and diagnostics strip + export badges (B10).
	let canvasTab = $state('canvas');
	let diagnosticsOpen = $state(false);
	const jsonDraft = $derived(store ? new JsonDraft(store) : null);
	const exportCheck = new ExportCheckState(async (surveyId, target) => {
		try {
			const { data, error } = await api.GET('/api/surveys/{survey_id}/export-check', {
				params: { path: { survey_id: surveyId }, query: { target } }
			});
			if (data) return { ok: true, data: data as CheckResult };
			const m = (error as { message?: unknown } | undefined)?.message;
			return { ok: false, message: typeof m === 'string' ? m : 'Request failed.' };
		} catch (e) {
			return { ok: false, message: (e as Error)?.message || 'Network error' };
		}
	});
	onDestroy(() => exportCheck.dispose());
	const badges = $derived(
		store ? exportBadges(store.survey, exportCheck.diagnostics, exportCheck.target) : new Map<string, ExportBadge[]>()
	);

	/** Go to what a diagnostic or badge is about: its property if it has one, else its card. */
	async function goTo(owner: Owner) {
		canvasTab = 'canvas';
		if (propertiesCollapsible) {
			propertiesOpen = true;
			outlineOpen = false;
		}
		selection.select(owner.id);
		if (owner.properties.length || owner.id === SURVEY_ID) {
			propertyFocus.ask(owner.id, owner.properties);
			return;
		}
		await tick();
		document.getElementById(`card-${owner.id}`)?.focus();
	}

	async function addQuestion(pageId?: string) {
		if (!store) return;
		const page = pageId ?? targetPage(pages, selection.id);
		if (!page) return toast('Add a page first.');
		const out = await store.submit([{ op: 'add_question', params: { page, type: 'text' } }]);
		if (out.status !== 'applied') return;
		const id = addedQuestionId(out.result.patch);
		if (id) {
			selection.select(id);
			announce('Question added.');
		}
	}

	async function undoRedo(which: 'undo' | 'redo') {
		if (!store) return;
		const out = await (which === 'undo' ? store.undo() : store.redo());
		if (out.status === 'dropped') toast(out.message);
		else if (out.status === 'applied') announce(which === 'undo' ? 'Undone.' : 'Redone.');
	}

	const routeOf = (v: BuilderView) => {
		if (store) {
			const id = store.surveyId;
			return v === 'appearance'
				? resolve('/surveys/[id]/appearance', { id })
				: resolve('/surveys/[id]', { id });
		}
		return v === 'appearance' ? resolve('/appearance') : `${resolve('/')}?mock`;
	};

	let innerWidth = $state(1280);
	let outlineWidth = $state(280);
	let propertiesWidth = $state(320);
	let outlineOpen = $state(false);
	let propertiesOpen = $state(false);
	let paletteOpen = $state(false);
	let previewOpen = $state(false);

	const outlineCollapsible = $derived(editing && innerWidth < OUTLINE_BREAKPOINT);
	const propertiesCollapsible = $derived(editing && innerWidth < PROPERTIES_BREAKPOINT);
	const showOutline = $derived(!outlineCollapsible || outlineOpen);
	const showProperties = $derived(!propertiesCollapsible || propertiesOpen);

	// Registered during init (not onMount) so child components see the shortcuts on first render.
	const offCommands = registry.registerAll(
		shellCommands({
				togglePalette: () => (paletteOpen = !paletteOpen),
			undo: () => {
				if (view === 'appearance') {
					if (!themeEditor.undo()) toast('Nothing to undo.');
				} else if (store) void undoRedo('undo');
				else toast('Undo: nothing to undo yet (editing is not connected).');
			},
			redo: () => {
				if (view === 'appearance') {
					if (!themeEditor.redo()) toast('Nothing to redo.');
				} else if (store) void undoRedo('redo');
				else toast('Redo: nothing to redo yet (editing is not connected).');
			},
			cyclePane: (dir) => cyclePane(dir),
			toggleTheme: () => theme.toggle(),
			systemTheme: () => theme.set('system'),
			toggleOutline: () => {
				outlineOpen = !outlineOpen;
				if (outlineOpen) propertiesOpen = false;
			},
			toggleProperties: () => {
				propertiesOpen = !propertiesOpen;
				if (propertiesOpen) outlineOpen = false;
			},
			outlineCollapsible: () => outlineCollapsible,
			propertiesCollapsible: () => propertiesCollapsible,
			preview: () => (previewOpen = true),
			clearSelection: () => selection.clear(),
			addQuestion: () => void addQuestion(),
			canEdit: () => editing && !!store
		})
	);
	const offAppearance = registry.registerAll(
		appearanceCommands({
			view: () => view,
			// eslint-disable-next-line svelte/no-navigation-without-resolve -- routeOf resolves
			open: (v) => goto(routeOf(v))
		})
	);
	onDestroy(() => {
		offCommands();
		offAppearance();
	});

	onMount(() => {
		const offTheme = theme.init();
		void health.check();
		return offTheme;
	});

	function closeOverlayOnEscape(e: KeyboardEvent, which: 'outline' | 'properties') {
		if (e.key !== 'Escape') return;
		if (which === 'outline' && outlineCollapsible && outlineOpen) outlineOpen = false;
		if (which === 'properties' && propertiesCollapsible && propertiesOpen) propertiesOpen = false;
	}
</script>

<svelte:window bind:innerWidth onkeydown={(e) => registry.handleKeydown(e)} />

<div class="shell">
	<TopBar
		{title}
		saveState={store?.saveState ?? 'saved'}
		{view}
		{registry}
		health={health.state}
		{outlineCollapsible}
		{propertiesCollapsible}
		{outlineOpen}
		{propertiesOpen}
	/>
	{#if store?.conflict}
		<ConflictBanner
			message={store.conflict.message}
			onreload={() => void store?.reload()}
			ondismiss={() => store?.dismissConflict()}
		/>
	{/if}

	{#if view === 'appearance'}
		<main id="pane-appearance" class="appearance" aria-label="Appearance">
			<AppearanceView />
		</main>
	{:else}
	<div class="panes">
		{#if showOutline}
			<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
			<aside
				id="pane-outline"
				class="pane outline"
				class:overlay={outlineCollapsible}
				style:width={outlineCollapsible ? undefined : `${outlineWidth}px`}
				aria-labelledby="outline-heading"
				data-pane="outline"
				onkeydown={(e) => closeOverlayOnEscape(e, 'outline')}
			>
				<div class="pane-scroll">
					<h2 id="outline-heading" class="pane-heading">Outline</h2>
					{#key store?.surveyId}
						<OutlineTree roots={pages} {selection} />
					{/key}
				</div>
				{#if !outlineCollapsible}
					<PaneResizer
						bind:size={outlineWidth}
						min={200}
						max={480}
						edge="left"
						label="Resize outline pane"
						controls="pane-outline"
					/>
				{/if}
			</aside>
		{/if}

		<main id="pane-canvas" class="pane canvas" aria-label="Canvas" data-pane="canvas">
			{#snippet canvasView()}
				<CanvasPane
					{pages}
					{selection}
					mock={!store}
					onAddQuestion={store ? (id) => void addQuestion(id) : undefined}
					exportBadges={badges}
					onBadge={store ? (b) => void goTo(ownerOf(store.survey, b.pointer)) : undefined}
				/>
			{/snippet}
			{#snippet jsonView()}
				{#if jsonDraft}<JsonView draft={jsonDraft} />{/if}
			{/snippet}
			{#if store}
				<div class="canvas-tabs">
					<Tabs
						label="Editor view"
						bind:value={canvasTab}
						tabs={[
							{ value: 'canvas', label: 'Canvas', content: canvasView },
							{ value: 'json', label: 'JSON', content: jsonView }
						]}
					/>
				</div>
			{:else}
				{@render canvasView()}
			{/if}
		</main>

		{#if showProperties}
			<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
			<aside
				id="pane-properties"
				class="pane properties"
				class:overlay={propertiesCollapsible}
				style:width={propertiesCollapsible ? undefined : `${propertiesWidth}px`}
				aria-labelledby="properties-heading"
				data-pane="properties"
				onkeydown={(e) => closeOverlayOnEscape(e, 'properties')}
			>
				{#if !propertiesCollapsible}
					<PaneResizer
						bind:size={propertiesWidth}
						min={240}
						max={520}
						edge="right"
						label="Resize properties pane"
						controls="pane-properties"
					/>
				{/if}
				<div class="pane-scroll">
					<PropertiesPane roots={pages} {selection} {store} />
				</div>
			</aside>
		{/if}
	</div>
	{#if store}
		<DiagnosticsStrip
			{store}
			check={exportCheck}
			bind:open={diagnosticsOpen}
			ongo={(item) => void goTo(item.owner)}
		/>
	{/if}
	{/if}
</div>

<CommandPalette bind:open={paletteOpen} {registry} />

<Dialog
	bind:open={previewOpen}
	title="Preview"
	description="Preview will render this survey in Enketo, exactly as participants see it. It is not connected yet."
	size="sm"
>
	{#snippet footer()}
		<Button variant="primary" onclick={() => (previewOpen = false)}>OK</Button>
	{/snippet}
</Dialog>

<Announcer />

<style>
	.shell {
		display: flex;
		flex-direction: column;
		height: 100dvh;
		overflow: hidden;
	}
	.appearance {
		flex: 1;
		min-height: 0;
		overflow: hidden;
	}
	.panes {
		position: relative;
		display: flex;
		flex: 1;
		min-height: 0;
	}
	.pane {
		min-height: 0;
		overflow: auto;
	}
	.outline,
	.properties {
		display: flex;
		flex: none;
		overflow: visible;
		background: var(--color-surface);
	}
	.pane-scroll {
		flex: 1;
		min-width: 0;
		overflow: auto;
	}
	.outline {
		border-inline-end: 1px solid var(--color-border);
	}
	.properties {
		border-inline-start: 1px solid var(--color-border);
	}
	.canvas {
		flex: 1;
		min-width: 0;
		background: var(--color-bg);
	}
	.canvas-tabs :global(.osp-tabs-list) {
		position: sticky;
		top: 0;
		z-index: 5;
		padding-inline: var(--space-4);
		background: var(--color-bg);
	}
	.canvas-tabs :global(.osp-tabs-content) {
		padding-block: 0;
	}
	.overlay {
		position: absolute;
		inset-block: 0;
		z-index: 20;
		width: min(20rem, 85vw);
		box-shadow: var(--shadow-lg);
	}
	.outline.overlay {
		inset-inline-start: 0;
	}
	.properties.overlay {
		inset-inline-end: 0;
	}
	.pane-heading {
		margin: 0;
		padding: var(--space-3) var(--space-4) var(--space-1);
		font-size: var(--text-sm);
		font-weight: var(--weight-bold);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-muted);
	}
</style>
