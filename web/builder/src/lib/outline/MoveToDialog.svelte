<script lang="ts">
	import { Button, Dialog } from '@osp/ui-components';
	import { untrack } from 'svelte';
	import type { OutlineNode } from '../model/outline';
	import { destinations, indexTree, movableIds, type DropTarget, type MovableType } from './moves';

	/**
	 * "Move to…" (command palette): the keyboard-friendly way to send the selected items to
	 * any page or block, at a chosen position. One `onMove` call, so one transaction.
	 */
	let {
		open = $bindable(false),
		roots,
		ids,
		onMove
	}: {
		open?: boolean;
		roots: OutlineNode[];
		/** The selected items (only those of the first one's type move). */
		ids: readonly string[];
		onMove: (ids: string[], target: DropTarget) => void;
	} = $props();

	const uid = $props.id();
	const moving = $derived(movableIds(roots, ids));
	const info = $derived(indexTree(roots));
	const type = $derived((moving[0] ? info.get(moving[0])?.type : undefined) as MovableType | undefined);
	const dests = $derived(type ? destinations(roots, type) : []);
	const noun = $derived(type === 'question' ? 'page' : type === 'page' ? 'block' : 'survey');
	const what = $derived(
		moving.length === 1 ? (info.get(moving[0])?.label ?? moving[0]) : `${moving.length} ${type ?? 'item'}s`
	);

	let destIndex = $state(0);
	let slot = $state('end');
	const dest = $derived(dests[destIndex]);
	// Positions in the destination: the start, after each item not being moved, the end.
	const positions = $derived.by(() => {
		if (!dest) return [];
		const out = [{ value: '0', label: 'At the start' }];
		dest.children.forEach((c, i) => {
			if (!moving.includes(c.id)) out.push({ value: String(i + 1), label: `After ${c.label}` });
		});
		out[out.length - 1] = { value: 'end', label: 'At the end' };
		return out;
	});

	// Opening starts from where the first item is now.
	$effect(() => {
		if (!open) return;
		untrack(() => {
			const parent = moving[0] ? info.get(moving[0])?.parent : undefined;
			const i = dests.findIndex((d) => d.parent === (parent ?? null));
			destIndex = i >= 0 ? i : 0;
			slot = 'end';
		});
	});

	function submit(e: SubmitEvent) {
		e.preventDefault();
		if (!dest) return;
		const s = slot === 'end' ? dest.size : Number(slot);
		open = false;
		onMove([...moving], { parent: dest.parent, slot: s });
	}
</script>

<Dialog bind:open title="Move to…" description={`Move ${what} to another ${noun} or position.`} size="sm">
	<form id="move-to-{uid}" class="move-to" onsubmit={submit}>
		{#if type !== 'block'}
			<label>
				<span>Destination {noun}</span>
				<select bind:value={destIndex} onchange={() => (slot = 'end')}>
					{#each dests as d, i (d.parent)}
						<option value={i}>{d.label}</option>
					{/each}
				</select>
			</label>
		{/if}
		<label>
			<span>Position</span>
			<select bind:value={slot}>
				{#each positions as p (p.value)}
					<option value={p.value}>{p.label}</option>
				{/each}
			</select>
		</label>
	</form>
	{#snippet footer()}
		<Button variant="secondary" onclick={() => (open = false)}>Cancel</Button>
		<Button variant="primary" type="submit" form="move-to-{uid}">Move</Button>
	{/snippet}
</Dialog>

<style>
	.move-to {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	label {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		font-size: var(--text-sm);
	}
	select {
		min-height: 2.25rem;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: var(--color-text);
		font: inherit;
	}
</style>
