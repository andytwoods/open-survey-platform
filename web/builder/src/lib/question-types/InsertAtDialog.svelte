<script lang="ts">
	import { Button, Dialog } from '@osp/ui-components';
	import { untrack } from 'svelte';
	import { targetPage, type OutlineNode } from '../model/outline';
	import { destinations, type DropTarget } from '../outline/moves';
	import { questionTypeInfo, type QuestionTypeId } from './catalogue';

	/**
	 * "Add … question at…": the keyboard way to do what dragging a toolbox type does. Pick
	 * a page and a position (the selected question's page, just after it, to start with).
	 * `oninsert` runs after the dialog has closed; cancelling returns focus to the opener.
	 */
	let {
		open = $bindable(false),
		type,
		roots,
		selectedId,
		returnFocusId = null,
		oninsert
	}: {
		open?: boolean;
		type: QuestionTypeId | null;
		roots: OutlineNode[];
		selectedId: string | null;
		returnFocusId?: string | null;
		oninsert: (type: QuestionTypeId, target: DropTarget) => void;
	} = $props();

	const uid = $props.id();
	const name = $derived(questionTypeInfo(type ?? undefined)?.name ?? 'question');
	const dests = $derived(destinations(roots, 'question'));

	let destIndex = $state(0);
	let slot = $state('end');
	const dest = $derived(dests[destIndex]);
	const positions = $derived.by(() => {
		if (!dest) return [];
		const out = [{ value: '0', label: 'At the start' }];
		dest.children.forEach((c, i) => out.push({ value: String(i + 1), label: `After ${c.label}` }));
		out[out.length - 1] = { value: 'end', label: 'At the end' };
		return out;
	});

	$effect(() => {
		if (!open) return;
		untrack(() => {
			const page = targetPage(roots, selectedId);
			const i = dests.findIndex((d) => d.parent === page);
			destIndex = i >= 0 ? i : 0;
			const d = dests[destIndex];
			const q = d ? d.children.findIndex((c) => c.id === selectedId) : -1;
			slot = q >= 0 && q < d.children.length - 1 ? String(q + 1) : 'end';
		});
	});

	let chosen: DropTarget | null = null;

	function submit(e: SubmitEvent) {
		e.preventDefault();
		if (!dest || !type) return;
		chosen = { parent: dest.parent, slot: slot === 'end' ? dest.size : Number(slot) };
		open = false;
	}

	function onCloseAutoFocus(e: Event) {
		const target = chosen;
		chosen = null;
		const t = type;
		if (target && t) {
			// Adding moves focus to the new question's text.
			e.preventDefault();
			setTimeout(() => oninsert(t, target), 0);
			return;
		}
		if (!returnFocusId) return;
		e.preventDefault();
		const id = returnFocusId;
		setTimeout(() => document.getElementById(id)?.focus(), 0);
	}
</script>

<Dialog
	bind:open
	title="Add {name} question at…"
	description="Choose the page and the position for the new question."
	size="sm"
	{onCloseAutoFocus}
>
	{#if dests.length}
		<form id="insert-at-{uid}" class="insert-at" onsubmit={submit}>
			<label>
				<span>Page</span>
				<select bind:value={destIndex} onchange={() => (slot = 'end')}>
					{#each dests as d, i (d.parent)}
						<option value={i}>{d.label}</option>
					{/each}
				</select>
			</label>
			<label>
				<span>Position</span>
				<select bind:value={slot}>
					{#each positions as p (p.value)}
						<option value={p.value}>{p.label}</option>
					{/each}
				</select>
			</label>
		</form>
	{:else}
		<p>Add a page first.</p>
	{/if}
	{#snippet footer()}
		<Button variant="secondary" onclick={() => (open = false)}>Cancel</Button>
		<Button variant="primary" type="submit" form="insert-at-{uid}" disabled={!dests.length}>Add</Button>
	{/snippet}
</Dialog>

<style>
	.insert-at {
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
		min-height: 2.75rem;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: var(--color-text);
		font: inherit;
	}
</style>
