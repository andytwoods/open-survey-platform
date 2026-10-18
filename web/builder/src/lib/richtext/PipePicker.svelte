<script lang="ts">
	import { Dialog } from '@osp/ui-components';
	import { Command } from 'bits-ui';
	import type { PipeCandidate, PipeGroup } from './pipes';

	/**
	 * The "Insert answer" picker (planning/rich-text.md §4): a combobox over the candidates
	 * the client lists (earlier questions, variables, built-ins), with typeahead. The server's
	 * `ref.*` diagnostics are the truth about what may be piped: a pick here is a convenience.
	 */
	let {
		open = $bindable(false),
		candidates,
		onPick,
		onClose
	}: {
		open?: boolean;
		candidates: readonly PipeCandidate[];
		onPick: (id: string) => void;
		/** Closed without a pick (Escape or Cancel). */
		onClose?: () => void;
	} = $props();

	let picked: string | null = null;
	let search = $state('');

	const GROUPS: readonly PipeGroup[] = ['Earlier questions', 'Variables', 'Built-ins'];
	const grouped = $derived(GROUPS.map((g) => [g, candidates.filter((c) => c.group === g)] as const).filter(([, list]) => list.length > 0));

	function choose(id: string) {
		picked = id;
		open = false;
	}

	function onCloseAutoFocus() {
		search = '';
		const id = picked;
		picked = null;
		if (id) onPick(id);
		else onClose?.();
	}
</script>

<Dialog bind:open title="Insert answer" description="Pipe an earlier answer, a variable or a built-in value into the text." size="sm" placement="top" {onCloseAutoFocus}>
	<Command.Root class="osp-pipes" label="Answers and variables" loop vimBindings={false}>
		<Command.Input class="osp-pipes-input" placeholder="Search by id or question…" bind:value={search} />
		<Command.List class="osp-pipes-list">
			<Command.Viewport>
				<Command.Empty class="osp-pipes-empty">No matching question or variable.</Command.Empty>
				{#each grouped as [group, list] (group)}
					<Command.Group value={group}>
						<Command.GroupHeading class="osp-pipes-heading">{group}</Command.GroupHeading>
						<Command.GroupItems>
							{#each list as c (c.id)}
								<Command.Item class="osp-pipes-item" value={c.id} keywords={[c.label]} onSelect={() => choose(c.id)}>
									<code>{c.id}</code>
									<span class="pick-label">{c.label}</span>
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
	:global(.osp-pipes) {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	:global(.osp-pipes-input) {
		height: 2.75rem;
		width: 100%;
		box-sizing: border-box;
		padding: 0 var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: var(--color-text);
		font: inherit;
	}
	:global(.osp-pipes-heading) {
		padding: var(--space-2) var(--space-2) var(--space-1);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-bold);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	:global(.osp-pipes-item) {
		display: flex;
		align-items: baseline;
		gap: var(--space-3);
		min-height: 2.75rem;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
		cursor: pointer;
	}
	:global(.osp-pipes-item[data-selected]) {
		background: var(--color-selected);
	}
	:global(.osp-pipes-item code) {
		flex: none;
		font-family: var(--font-mono);
	}
	.pick-label {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--color-text-muted);
	}
	:global(.osp-pipes-empty) {
		padding: var(--space-3);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
</style>
