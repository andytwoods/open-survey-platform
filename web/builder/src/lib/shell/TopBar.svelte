<script lang="ts">
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import ChartColumn from '@lucide/svelte/icons/chart-column';
	import SlidersHorizontal from '@lucide/svelte/icons/sliders-horizontal';
	import CloudAlert from '@lucide/svelte/icons/cloud-alert';
	import CloudCheck from '@lucide/svelte/icons/cloud-check';
	import CloudOff from '@lucide/svelte/icons/cloud-off';
	import CloudUpload from '@lucide/svelte/icons/cloud-upload';
	import Ellipsis from '@lucide/svelte/icons/ellipsis';
	import Eye from '@lucide/svelte/icons/eye';
	import Library from '@lucide/svelte/icons/library';
	import Moon from '@lucide/svelte/icons/moon';
	import Palette from '@lucide/svelte/icons/palette';
	import PanelLeft from '@lucide/svelte/icons/panel-left';
	import PanelRight from '@lucide/svelte/icons/panel-right';
	import Redo2 from '@lucide/svelte/icons/redo-2';
	import Search from '@lucide/svelte/icons/search';
	import Send from '@lucide/svelte/icons/send';
	import Sun from '@lucide/svelte/icons/sun';
	import Undo2 from '@lucide/svelte/icons/undo-2';
	import { Button, IconButton, theme } from '@osp/ui-components';
	import { DropdownMenu } from 'bits-ui';
	import { shortcutsOf, type CommandRegistry } from '../commands/registry';
	import { ariaShortcut, formatShortcut } from '../commands/shortcut';
	import type { BuilderView } from '../appearance/commands';
	import type { HealthState } from '../health.svelte';
	import type { SaveState } from '../sync/survey-store.svelte';

	let {
		title,
		saveState = 'saved',
		edits = 0,
		view = 'editor',
		viewTabs = false,
		results = false,
		profile = false,
		bank = false,
		registry,
		health,
		outlineCollapsible,
		propertiesCollapsible,
		outlineOpen,
		propertiesOpen
	}: {
		title: string;
		saveState?: SaveState;
		/** The store's `edits` (items queued since load), on the status for tests to wait on. */
		edits?: number;
		view?: BuilderView;
		/** Show the Questions / Flow switch (a real survey is open). */
		viewTabs?: boolean;
		/** Show the way to the Results page (the host serves it). */
		results?: boolean;
		/** Show the way to the lab's panel profile page (the host serves it). */
		profile?: boolean;
		/** Show the way to the lab's question bank page (the host serves it). */
		bank?: boolean;
		registry: CommandRegistry;
		health: HealthState;
		outlineCollapsible: boolean;
		propertiesCollapsible: boolean;
		outlineOpen: boolean;
		propertiesOpen: boolean;
	} = $props();

	function sc(id: string) {
		const first = shortcutsOf(registry.get(id) ?? { id, label: '', run() {} });
		return {
			shortcut: first[0] ? formatShortcut(first[0], registry.isMac) : undefined,
			keyshortcuts: first.map((s) => ariaShortcut(s, registry.isMac)).join(' ') || undefined
		};
	}

	const healthText = $derived(
		{ checking: 'Checking connection…', online: 'API connected', offline: 'API offline' }[health]
	);
	const isDark = $derived(theme.resolved === 'dark');
	const themeLabel = $derived(isDark ? 'Switch to light theme' : 'Switch to dark theme');

	/**
	 * Below 1024 px every top-bar target is at least 44 x 44 px and the less-used actions move
	 * into the "More actions" menu (B17); below 768 px the bar takes two rows; below 480 px
	 * Preview and Publish show their icon only (their names stay).
	 */
	let innerWidth = $state(1280);
	const layout = $derived(innerWidth >= 1024 ? 'wide' : innerWidth >= 768 ? 'compact' : 'stacked');
	const iconOnly = $derived(innerWidth < 480);

	// Results sits next to Preview; in the two-row phone layout it moves into the menu.
	const resultsInBar = $derived(results && layout !== 'stacked');
	const overflow = $derived([
		{ id: 'palette.open', label: 'Command palette', icon: Search },
		{ id: 'edit.undo', label: 'Undo', icon: Undo2 },
		{ id: 'edit.redo', label: 'Redo', icon: Redo2 },
		...(view === 'appearance' ? [] : [{ id: 'view.appearance', label: 'Appearance', icon: Palette }]),
		...(profile && view !== 'profile' ? [{ id: 'view.profile', label: 'Panel profile', icon: SlidersHorizontal }] : []),
		...(bank && view !== 'bank' ? [{ id: 'view.bank', label: 'Question bank', icon: Library }] : []),
		...(results && !resultsInBar && view !== 'results'
			? [{ id: 'view.results', label: 'Results', icon: ChartColumn }]
			: []),
		{ id: 'view.toggleTheme', label: themeLabel, icon: isDark ? Sun : Moon }
	]);

	// A chosen menu item runs once the menu has handed focus back to its trigger, so a
	// command that opens a dialog (the palette) returns focus there when it closes.
	let pending: string | null = null;
	function afterMenuClose() {
		const id = pending;
		pending = null;
		if (id) setTimeout(() => registry.run(id), 0);
	}

	const SAVE = {
		loading: { icon: CloudUpload, text: 'Loading…' },
		saved: { icon: CloudCheck, text: 'All changes saved' },
		saving: { icon: CloudUpload, text: 'Saving…' },
		offline: { icon: CloudOff, text: 'Offline: changes will be sent when you reconnect' },
		conflict: { icon: CloudAlert, text: 'Conflict: changed elsewhere' },
		error: { icon: CloudAlert, text: 'Not saved' },
		'signed-out': { icon: CloudOff, text: 'Not saved: your session ended' }
	} as const;
	const save = $derived(SAVE[saveState]);
</script>

<svelte:window bind:innerWidth />

{#snippet outlineToggle()}
	{#if outlineCollapsible}
		<IconButton
			icon={PanelLeft}
			label="Outline pane"
			aria-expanded={outlineOpen}
			aria-controls="pane-outline"
			onclick={() => registry.run('view.toggleOutline')}
		/>
	{/if}
{/snippet}

{#snippet views()}
	{#if viewTabs && view !== 'appearance' && view !== 'profile' && view !== 'bank'}
		<nav class="views" aria-label="Builder views">
			<button
				type="button"
				aria-current={view === 'editor' ? 'page' : undefined}
				onclick={() => view !== 'editor' && registry.run('view.editor')}>Questions</button
			>
			<button
				type="button"
				aria-current={view === 'flow' ? 'page' : undefined}
				onclick={() => view !== 'flow' && registry.run('view.flow')}>Flow</button
			>
			<button
				type="button"
				aria-current={view === 'settings' ? 'page' : undefined}
				onclick={() => view !== 'settings' && registry.run('view.settings')}>Settings</button
			>
		</nav>
	{/if}
{/snippet}

{#snippet saveStatus()}
	<span class="save-state" role="status" data-state={saveState} data-edits={edits}>
		<save.icon size={16} aria-hidden="true" />
		<span>{save.text}</span>
	</span>
{/snippet}

{#snippet healthDot()}
	<span class="health" data-state={health} title={healthText}>
		<span class="dot" aria-hidden="true"></span>
		<span class="health-text">{healthText}</span>
	</span>
{/snippet}

{#snippet back()}
	{#if view === 'appearance' || view === 'profile' || view === 'bank'}
		<Button onclick={() => registry.run('view.editor')}>
			<ArrowLeft size={16} aria-hidden="true" />
			Back to editor
		</Button>
	{/if}
{/snippet}

{#snippet primary()}
	{#if resultsInBar}
		<Button
			class="labelled"
			variant="secondary"
			aria-current={view === 'results' ? 'page' : undefined}
			onclick={() => view !== 'results' && registry.run('view.results')}
		>
			<ChartColumn size={16} aria-hidden="true" />
			<span class="label">Results</span>
		</Button>
	{/if}
	<Button
		class="labelled"
		variant={viewTabs ? 'secondary' : 'primary'}
		onclick={() => registry.run('survey.preview')}
	>
		<Eye size={16} aria-hidden="true" />
		<span class="label">Preview</span>
	</Button>
	{#if viewTabs}
		<Button class="labelled" variant="primary" onclick={() => registry.run('survey.publish')}>
			<Send size={16} aria-hidden="true" />
			<span class="label">Publish</span>
		</Button>
	{/if}
{/snippet}

{#snippet propertiesToggle()}
	{#if propertiesCollapsible}
		<IconButton
			icon={PanelRight}
			label="Properties pane"
			aria-expanded={propertiesOpen}
			aria-controls="pane-properties"
			onclick={() => registry.run('view.toggleProperties')}
		/>
	{/if}
{/snippet}

{#snippet more()}
	<DropdownMenu.Root>
		<DropdownMenu.Trigger class="osp-icon-button more-trigger" aria-label="More actions">
			<Ellipsis size={18} aria-hidden="true" />
		</DropdownMenu.Trigger>
		<!-- Rendered in place (inside the banner landmark), positioned `fixed`. -->
		<DropdownMenu.Portal disabled>
			<DropdownMenu.Content
				class="more-menu"
				align="end"
				sideOffset={4}
				strategy="fixed"
				onCloseAutoFocus={afterMenuClose}
			>
				{#each overflow as item (item.id)}
					{@const s = sc(item.id)}
					<DropdownMenu.Item
						class="more-item"
						aria-keyshortcuts={s.keyshortcuts}
						onSelect={() => (pending = item.id)}
					>
						<item.icon size={18} aria-hidden="true" />
						<span class="more-label">{item.label}</span>
						{#if s.shortcut}<kbd aria-hidden="true">{s.shortcut}</kbd>{/if}
					</DropdownMenu.Item>
				{/each}
			</DropdownMenu.Content>
		</DropdownMenu.Portal>
	</DropdownMenu.Root>
{/snippet}

<header class="topbar" data-pane="topbar" data-layout={layout} class:icon-only={iconOnly}>
	{#if layout === 'stacked'}
		<div class="left">
			{@render outlineToggle()}
			<h1 class="title">{title}</h1>
			{@render saveStatus()}
		</div>
		<div class="right">
			{@render healthDot()}
			{@render more()}
			{@render propertiesToggle()}
		</div>
		<div class="row2">
			{@render views()}
			{@render back()}
			<span class="row2-end">{@render primary()}</span>
		</div>
	{:else}
		<div class="left">
			{@render outlineToggle()}
			<h1 class="title">{title}</h1>
			{@render views()}
			{@render saveStatus()}
		</div>
		<div class="right">
			{@render healthDot()}
			{#if layout === 'wide'}
				<IconButton
					icon={Search}
					label="Command palette"
					{...sc('palette.open')}
					onclick={() => registry.run('palette.open')}
				/>
				<IconButton icon={Undo2} label="Undo" {...sc('edit.undo')} onclick={() => registry.run('edit.undo')} />
				<IconButton icon={Redo2} label="Redo" {...sc('edit.redo')} onclick={() => registry.run('edit.redo')} />
				{#if view === 'appearance' || view === 'profile' || view === 'bank'}
					{@render back()}
				{:else}
					<IconButton icon={Palette} label="Appearance" onclick={() => registry.run('view.appearance')} />
				{/if}
				<IconButton
					icon={isDark ? Sun : Moon}
					label={themeLabel}
					onclick={() => registry.run('view.toggleTheme')}
				/>
			{:else}
				{@render back()}
			{/if}
			{@render primary()}
			{#if layout === 'compact'}{@render more()}{/if}
			{@render propertiesToggle()}
		</div>
	{/if}
</header>

<style>
	.topbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
		min-height: 3.25rem;
		padding: var(--space-2) var(--space-3);
		border-bottom: 1px solid var(--color-border);
		background: var(--color-surface);
	}
	.left,
	.right,
	.row2 {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-width: 0;
	}
	.right > :global(*),
	.row2 > :global(*),
	.left > :global(:not(.title)) {
		flex-shrink: 0;
	}
	/* Only the title gives way when space runs out. */
	.left {
		flex: 0 1 auto;
	}
	.right {
		flex: none;
	}
	/* Touch-sized targets below 1024 px. */
	.topbar:not([data-layout='wide']) :global(.osp-icon-button),
	.topbar:not([data-layout='wide']) :global(.osp-button) {
		min-width: 2.75rem;
		height: 2.75rem;
	}
	.topbar:not([data-layout='wide']) .views button {
		min-width: 2.75rem;
		min-height: 2.75rem;
	}
	.topbar[data-layout='stacked'] {
		flex-wrap: wrap;
		row-gap: var(--space-2);
	}
	.topbar[data-layout='stacked'] .left {
		flex: 1 1 0;
	}
	.row2 {
		flex: 1 0 100%;
		gap: var(--space-1);
	}
	.row2-end {
		display: flex;
		gap: var(--space-1);
		margin-inline-start: auto;
	}
	.row2 .views {
		flex: 1 1 auto;
		min-width: 0;
	}
	.row2 .views button {
		flex: 1 1 auto;
		padding-inline: var(--space-1);
	}
	.icon-only :global(.labelled) {
		padding: 0;
	}
	.icon-only :global(.labelled .label) {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}
	:global(.more-menu) {
		z-index: 70;
		min-width: 14rem;
		padding: var(--space-1);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		box-shadow: var(--shadow-lg);
	}
	:global(.more-item) {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-height: 2.75rem;
		padding: 0 var(--space-3);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
		cursor: pointer;
	}
	:global(.more-item[data-highlighted]) {
		background: var(--color-selected);
		outline: 2px solid var(--color-focus);
		outline-offset: -2px;
	}
	.more-label {
		flex: 1;
	}
	kbd {
		color: var(--color-text-muted);
		font: inherit;
		font-size: var(--text-xs);
	}
	.title {
		margin: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: var(--text-md);
		font-weight: var(--weight-bold);
	}
	.views {
		display: inline-flex;
		padding: 2px;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-sunken);
	}
	.views button {
		padding: var(--space-1) var(--space-3);
		border: 0;
		border-radius: var(--radius-sm);
		background: transparent;
		color: var(--color-text-muted);
		font: inherit;
		font-size: var(--text-sm);
		cursor: pointer;
	}
	.views button[aria-current='page'] {
		background: var(--color-surface-raised);
		color: var(--color-text);
		font-weight: var(--weight-bold);
		box-shadow: var(--shadow-sm, none);
	}
	.views button:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}
	.save-state,
	.health {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		white-space: nowrap;
	}
	.health {
		margin-inline-end: var(--space-2);
	}
	.save-state[data-state='offline'],
	.save-state[data-state='conflict'],
	.save-state[data-state='error'] {
		color: var(--color-warning);
	}
	.dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: var(--radius-full);
		background: var(--color-text-muted);
	}
	.health[data-state='online'] .dot {
		background: var(--color-success);
	}
	.health[data-state='offline'] .dot {
		background: var(--color-warning);
	}
	/* Below 1024 px the save and connection states show as icons; their text stays readable. */
	.topbar:not([data-layout='wide']) .health-text,
	.topbar:not([data-layout='wide']) .save-state span {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}
</style>
