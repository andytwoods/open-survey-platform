<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import ListTree from '@lucide/svelte/icons/list-tree';
	import Trash from '@lucide/svelte/icons/trash';
	import { tick } from 'svelte';
	import RowEditor from './RowEditor.svelte';
	import { newGroup, newRow } from './tree';
	import type { GroupMode, GroupNode, QuestionInfo } from './types';
	import type { RowWarning } from './warnings';

	/**
	 * The tree view: the root group and, recursively (a snippet, so no self-import), its
	 * nested "All of / Any of / None of" groups and rows. Edits mutate the $state tree.
	 */
	let {
		root,
		questions,
		qmap,
		warnings,
		onfix
	}: {
		root: GroupNode;
		questions: readonly QuestionInfo[];
		qmap: ReadonlyMap<string, QuestionInfo>;
		warnings: ReadonlyMap<string, RowWarning[]>;
		onfix: (fixKey: string, question: string) => void;
	} = $props();

	const MODES: { value: GroupMode; label: string }[] = [
		{ value: 'all', label: 'All of the following' },
		{ value: 'any', label: 'Any of the following' },
		{ value: 'none', label: 'None of the following' }
	];

	const nameOf = (path: string) => (path === '' ? 'Condition' : `Group ${path}`);
	const modeLabel = (g: GroupNode) => MODES.find((m) => m.value === g.mode)?.label ?? '';
	const childPath = (path: string, i: number) => (path === '' ? String(i + 1) : `${path}.${i + 1}`);

	async function focusKey(key: string) {
		await tick();
		document.querySelector<HTMLElement>(`[data-key="${key}"] select, [data-key="${key}"] button`)?.focus();
	}

	function addRow(g: GroupNode) {
		const row = newRow();
		g.children.push(row);
		void focusKey(row.key);
	}

	function addGroup(g: GroupNode) {
		const first = newRow();
		g.children.push(newGroup('all', [first]));
		void focusKey(first.key);
	}

	async function remove(g: GroupNode, i: number) {
		g.children.splice(i, 1);
		await tick();
		const next = g.children[Math.min(i, g.children.length - 1)];
		if (next) void focusKey(next.key);
		else document.querySelector<HTMLElement>(`[data-key="${g.key}"] [data-role="add-row"]`)?.focus();
	}
</script>

{#snippet groupView(group: GroupNode, path: string, onremove: (() => void) | null)}
	{@const isRoot = path === ''}
	{@const name = nameOf(path)}
	<div
		class="group"
		class:root={isRoot}
		data-key={group.key}
		data-mode={group.mode}
		data-testid={isRoot ? 'condition-root' : 'condition-group'}
		role="group"
		aria-label="{name}: {modeLabel(group).toLowerCase()}"
	>
		<div class="head">
			<label class="mode">
				<span class="osp-visually-hidden">{name}: match</span>
				<select
					class="ctl"
					data-role="mode"
					value={group.mode}
					onchange={(e) => (group.mode = e.currentTarget.value as GroupMode)}
				>
					{#each MODES as m (m.value)}
						<option value={m.value}>{m.label}</option>
					{/each}
				</select>
			</label>
			{#if onremove}
				<button
					type="button"
					class="icon"
					aria-label="Remove {name.toLowerCase()}"
					title="Remove group"
					onclick={onremove}
				>
					<Trash size={16} aria-hidden="true" />
				</button>
			{/if}
		</div>

		{#if group.children.length}
			<ul class="children">
				{#each group.children as child, i (child.key)}
					{#if child.kind === 'row'}
						<RowEditor
							row={child}
							label="Condition {childPath(path, i)}"
							{questions}
							{qmap}
							warnings={warnings.get(child.key) ?? []}
							onremove={() => remove(group, i)}
							{onfix}
						/>
					{:else}
						<li class="nested">
							{@render groupView(child, childPath(path, i), () => remove(group, i))}
						</li>
					{/if}
				{/each}
			</ul>
		{:else}
			<p class="empty">{isRoot ? 'No conditions yet: the question is always shown.' : 'This group is empty.'}</p>
		{/if}

		<div class="actions">
			<button type="button" class="add" data-role="add-row" onclick={() => addRow(group)}>
				<Plus size={14} aria-hidden="true" /> Add condition<span class="osp-visually-hidden">
					to {name.toLowerCase()}</span
				>
			</button>
			<button type="button" class="add" data-role="add-group" onclick={() => addGroup(group)}>
				<ListTree size={14} aria-hidden="true" /> Add group<span class="osp-visually-hidden">
					to {name.toLowerCase()}</span
				>
			</button>
		</div>
	</div>
{/snippet}

{@render groupView(root, '', null)}

<style>
	.group {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-3);
		border: 1px solid var(--color-border);
		border-inline-start: 3px solid var(--color-accent);
		border-radius: var(--radius-md);
		background: var(--color-surface-sunken);
	}
	.group[data-mode='any'] {
		border-inline-start-color: var(--color-success);
	}
	.group[data-mode='none'] {
		border-inline-start-color: var(--color-danger);
	}
	.group.root {
		background: var(--color-surface);
	}
	.head {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.ctl {
		height: var(--control-height);
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}
	.children {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.empty {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.actions {
		display: flex;
		gap: var(--space-2);
	}
	.add,
	.icon {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		height: 1.875rem;
		padding: 0 var(--space-2);
		border: 1px dashed var(--color-border-strong);
		border-radius: var(--radius-md);
		background: transparent;
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
		cursor: pointer;
	}
	.icon {
		margin-inline-start: auto;
		border-style: solid;
		border-color: transparent;
		color: var(--color-text-muted);
	}
	.add:hover,
	.icon:hover {
		background: var(--color-surface-raised);
		color: var(--color-text);
	}
	.ctl:focus-visible,
	.add:focus-visible,
	.icon:focus-visible {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 1px;
	}
</style>
