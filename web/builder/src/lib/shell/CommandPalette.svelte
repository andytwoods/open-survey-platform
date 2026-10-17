<script lang="ts">
	import { Dialog } from '@osp/ui-components';
	import { Command } from 'bits-ui';
	import type { CommandRegistry, Command as Cmd } from '../commands/registry';
	import { shortcutsOf } from '../commands/registry';
	import { formatShortcut } from '../commands/shortcut';

	/** Ctrl/Cmd+K palette: lists the registry, runs the chosen command after closing. */
	let { open = $bindable(false), registry }: { open?: boolean; registry: CommandRegistry } =
		$props();

	let pending: string | null = null;
	let search = $state('');

	const groups = $derived.by(() => {
		if (!open) return [];
		// Built fresh inside $derived, never mutated afterwards.
		// eslint-disable-next-line svelte/prefer-svelte-reactivity
		const byGroup = new Map<string, Cmd[]>();
		for (const c of registry.list()) {
			if (c.inPalette === false) continue;
			const g = c.group ?? 'General';
			byGroup.set(g, [...(byGroup.get(g) ?? []), c]);
		}
		return [...byGroup.entries()];
	});

	function choose(id: string) {
		pending = id;
		open = false;
	}

	function onCloseAutoFocus() {
		search = '';
		const id = pending;
		pending = null;
		// Let the dialog hand focus back first, then run (the command may move focus itself).
		if (id) setTimeout(() => registry.run(id), 0);
	}
</script>

<Dialog bind:open title="Command palette" hideTitle showClose={false} placement="top" {onCloseAutoFocus}>
	<!-- No vim bindings: Bits UI would take Ctrl+K (and Ctrl+J/N/P) as "move selection" and
	     prevent its default, so the registry's Mod+K toggle never saw it on Windows/Linux. -->
	<Command.Root class="palette" label="Commands" loop vimBindings={false}>
		<Command.Input
			class="palette-input"
			placeholder="Type a command…"
			bind:value={search}
		/>
		<Command.List class="palette-list">
			<Command.Viewport>
				<Command.Empty class="palette-empty">No matching commands.</Command.Empty>
				{#each groups as [group, cmds] (group)}
					<Command.Group value={group}>
						<Command.GroupHeading class="palette-heading">{group}</Command.GroupHeading>
						<Command.GroupItems>
							{#each cmds as cmd (cmd.id)}
								{@const sc = shortcutsOf(cmd)[0]}
								<Command.Item
									class="palette-item"
									value={cmd.id}
									keywords={[cmd.label, ...(cmd.keywords ?? [])]}
									disabled={!registry.isEnabled(cmd.id)}
									onSelect={() => choose(cmd.id)}
								>
									<span>{cmd.label}</span>
									{#if sc}<kbd>{formatShortcut(sc, registry.isMac)}</kbd>{/if}
								</Command.Item>
							{/each}
						</Command.GroupItems>
					</Command.Group>
				{/each}
			</Command.Viewport>
		</Command.List>
	</Command.Root>
</Dialog>

<style>
	:global(.palette) {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	:global(.palette-input) {
		height: 2.75rem;
		padding: 0 var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: var(--color-text);
		font: inherit;
	}
	/* No inner scroller: the dialog scrolls (it contains the focusable input, so axe's
	   scrollable-region-focusable rule holds). */
	:global(.palette-heading) {
		padding: var(--space-2) var(--space-2) var(--space-1);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-bold);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	:global(.palette-item) {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
		cursor: pointer;
	}
	:global(.palette-item[data-selected]) {
		background: var(--color-selected);
	}
	:global(.palette-item[data-disabled]) {
		opacity: 0.55;
		cursor: not-allowed;
	}
	:global(.palette-item kbd) {
		color: var(--color-text-muted);
		font-family: var(--font-sans);
		font-size: var(--text-xs);
	}
	:global(.palette-empty) {
		padding: var(--space-3);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
</style>
