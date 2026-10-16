<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Announcer, Button, Dialog, PaneResizer, theme, toast } from '@osp/ui-components';
	import AppearanceView from '../appearance/AppearanceView.svelte';
	import { appearanceCommands, type BuilderView } from '../appearance/commands';
	import { themeEditor } from '../appearance/theme-editor.svelte';
	import { onDestroy, onMount } from 'svelte';
	import { CommandRegistry } from '../commands/registry';
	import { detectMac } from '../commands/shortcut';
	import { health } from '../health.svelte';
	import { MOCK_SURVEY } from '../mock/survey';
	import { selection } from '../selection.svelte';
	import CanvasPane from './CanvasPane.svelte';
	import CommandPalette from './CommandPalette.svelte';
	import { shellCommands } from './commands';
	import OutlineTree from './OutlineTree.svelte';
	import { cyclePane } from './panes';
	import PropertiesPane from './PropertiesPane.svelte';
	import TopBar from './TopBar.svelte';

	/** Which view fills the area under the top bar (each has its own route). */
	let { view = 'editor' }: { view?: BuilderView } = $props();
	const editing = $derived(view === 'editor');

	// Below these widths a pane collapses and opens as an overlay from the top bar.
	const PROPERTIES_BREAKPOINT = 1024;
	const OUTLINE_BREAKPOINT = 720;

	const registry = new CommandRegistry({
		isMac: detectMac(),
		isModalOpen: () => paletteOpen || previewOpen
	});
	const pages = MOCK_SURVEY.children ?? [];

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
				} else toast('Undo: nothing to undo yet (editing is not connected).');
			},
			redo: () => {
				if (view === 'appearance') {
					if (!themeEditor.redo()) toast('Nothing to redo.');
				} else toast('Redo: nothing to redo yet (editing is not connected).');
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
			clearSelection: () => selection.clear()
		})
		);
	const offAppearance = registry.registerAll(
		appearanceCommands({
			view: () => view,
			open: (v) => goto(resolve(v === 'appearance' ? '/appearance' : '/'))
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
		title={MOCK_SURVEY.label}
		{view}
		{registry}
		health={health.state}
		{outlineCollapsible}
		{propertiesCollapsible}
		{outlineOpen}
		{propertiesOpen}
	/>

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
					<OutlineTree roots={pages} {selection} />
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
			<CanvasPane {pages} {selection} />
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
					<PropertiesPane roots={pages} {selection} />
				</div>
			</aside>
		{/if}
	</div>
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
		display: grid;
		grid-template-rows: auto 1fr;
		height: 100dvh;
		overflow: hidden;
	}
	.appearance {
		min-height: 0;
		overflow: hidden;
	}
	.panes {
		position: relative;
		display: flex;
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
