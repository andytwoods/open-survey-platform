<script lang="ts">
	import CloudCheck from '@lucide/svelte/icons/cloud-check';
	import Eye from '@lucide/svelte/icons/eye';
	import Moon from '@lucide/svelte/icons/moon';
	import PanelLeft from '@lucide/svelte/icons/panel-left';
	import PanelRight from '@lucide/svelte/icons/panel-right';
	import Redo2 from '@lucide/svelte/icons/redo-2';
	import Search from '@lucide/svelte/icons/search';
	import Sun from '@lucide/svelte/icons/sun';
	import Undo2 from '@lucide/svelte/icons/undo-2';
	import { Button, IconButton, theme } from '@osp/ui-components';
	import { shortcutsOf, type CommandRegistry } from '../commands/registry';
	import { ariaShortcut, formatShortcut } from '../commands/shortcut';
	import type { HealthState } from '../health.svelte';

	let {
		title,
		registry,
		health,
		outlineCollapsible,
		propertiesCollapsible,
		outlineOpen,
		propertiesOpen
	}: {
		title: string;
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
		<!-- MOCK: save state is static until the op client exists (B2). -->
		<span class="save-state" role="status">
			<CloudCheck size={16} aria-hidden="true" />
			<span>All changes saved</span>
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
