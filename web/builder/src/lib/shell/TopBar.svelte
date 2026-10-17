<script lang="ts">
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import CloudAlert from '@lucide/svelte/icons/cloud-alert';
	import CloudCheck from '@lucide/svelte/icons/cloud-check';
	import CloudOff from '@lucide/svelte/icons/cloud-off';
	import CloudUpload from '@lucide/svelte/icons/cloud-upload';
	import Eye from '@lucide/svelte/icons/eye';
	import Moon from '@lucide/svelte/icons/moon';
	import Palette from '@lucide/svelte/icons/palette';
	import PanelLeft from '@lucide/svelte/icons/panel-left';
	import PanelRight from '@lucide/svelte/icons/panel-right';
	import Redo2 from '@lucide/svelte/icons/redo-2';
	import Search from '@lucide/svelte/icons/search';
	import Sun from '@lucide/svelte/icons/sun';
	import Undo2 from '@lucide/svelte/icons/undo-2';
	import { Button, IconButton, theme } from '@osp/ui-components';
	import { shortcutsOf, type CommandRegistry } from '../commands/registry';
	import { ariaShortcut, formatShortcut } from '../commands/shortcut';
	import type { BuilderView } from '../appearance/commands';
	import type { HealthState } from '../health.svelte';
	import type { SaveState } from '../sync/survey-store.svelte';

	let {
		title,
		saveState = 'saved',
		view = 'editor',
		viewTabs = false,
		registry,
		health,
		outlineCollapsible,
		propertiesCollapsible,
		outlineOpen,
		propertiesOpen
	}: {
		title: string;
		saveState?: SaveState;
		view?: BuilderView;
		/** Show the Questions / Flow switch (a real survey is open). */
		viewTabs?: boolean;
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

	const SAVE = {
		loading: { icon: CloudUpload, text: 'Loading…' },
		saved: { icon: CloudCheck, text: 'All changes saved' },
		saving: { icon: CloudUpload, text: 'Saving…' },
		offline: { icon: CloudOff, text: 'Offline: changes will be sent when you reconnect' },
		conflict: { icon: CloudAlert, text: 'Conflict: changed elsewhere' },
		error: { icon: CloudAlert, text: 'Not saved' }
	} as const;
	const save = $derived(SAVE[saveState]);
</script>

<header class="topbar" data-pane="topbar">
	<div class="left">
		{#if outlineCollapsible}
			<IconButton
				icon={PanelLeft}
				label="Outline pane"
				aria-expanded={outlineOpen}
				aria-controls="pane-outline"
				onclick={() => registry.run('view.toggleOutline')}
			/>
		{/if}
		<h1 class="title">{title}</h1>
		{#if viewTabs && view !== 'appearance'}
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
			</nav>
		{/if}
		<span class="save-state" role="status" data-state={saveState}>
			<save.icon size={16} aria-hidden="true" />
			<span>{save.text}</span>
		</span>
	</div>

	<div class="right">
		<span class="health" data-state={health} title={healthText}>
			<span class="dot" aria-hidden="true"></span>
			<span class="health-text">{healthText}</span>
		</span>
		<IconButton
			icon={Search}
			label="Command palette"
			{...sc('palette.open')}
			onclick={() => registry.run('palette.open')}
		/>
		<IconButton icon={Undo2} label="Undo" {...sc('edit.undo')} onclick={() => registry.run('edit.undo')} />
		<IconButton icon={Redo2} label="Redo" {...sc('edit.redo')} onclick={() => registry.run('edit.redo')} />
		{#if view === 'appearance'}
			<Button onclick={() => registry.run('view.editor')}>
				<ArrowLeft size={16} aria-hidden="true" />
				Back to editor
			</Button>
		{:else}
			<IconButton icon={Palette} label="Appearance" onclick={() => registry.run('view.appearance')} />
		{/if}
		<IconButton
			icon={isDark ? Sun : Moon}
			label={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
			onclick={() => registry.run('view.toggleTheme')}
		/>
		<Button variant="primary" onclick={() => registry.run('survey.preview')}>
			<Eye size={16} aria-hidden="true" />
			Preview
		</Button>
		{#if propertiesCollapsible}
			<IconButton
				icon={PanelRight}
				label="Properties pane"
				aria-expanded={propertiesOpen}
				aria-controls="pane-properties"
				onclick={() => registry.run('view.toggleProperties')}
			/>
		{/if}
	</div>
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
	.right {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-width: 0;
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
	@media (max-width: 720px) {
		.health-text,
		.save-state span {
			position: absolute;
			width: 1px;
			height: 1px;
			overflow: hidden;
			clip: rect(0 0 0 0);
			white-space: nowrap;
		}
	}
</style>
