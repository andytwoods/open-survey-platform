<script lang="ts">
	import { Button, Dialog } from '@osp/ui-components';
	import { untrack } from 'svelte';
	import type { DeleteRequest } from './actions.svelte';

	/**
	 * Confirms deleting a block, page or question that conditions or piping elsewhere still
	 * refer to (the server refused the plain delete with `op.dangling_ref`). Deleting anyway
	 * leaves those references broken: they show up as errors to fix. Closing the dialog
	 * (Escape, ×, Keep) keeps it.
	 */
	let { request, onresolve }: { request: DeleteRequest | null; onresolve: (ok: boolean) => void } = $props();

	let open = $derived(!!request);
	$effect(() => {
		if (!open && untrack(() => request)) onresolve(false);
	});

	const count = $derived(request?.sites.length ?? 0);
	const what = $derived(request?.type ?? 'item');
	const inside = $derived(request?.type === 'question' ? 'is' : 'or a question in it is');
</script>

<Dialog bind:open title="Delete a {what} that is still used?" size="sm">
	{#if request}
		<div class="body" data-testid="structure-delete-warning">
			<p>
				<strong>{request.name}</strong>
				{inside} used in {count}
				{count === 1 ? 'place' : 'places'}:
			</p>
			<ul>
				{#each request.sites as s, i (i)}
					<li>{s}</li>
				{/each}
			</ul>
			<p>Deleting it breaks those conditions and piped texts. You can undo the delete.</p>
		</div>
	{/if}
	{#snippet footer()}
		<Button onclick={() => onresolve(false)}>Keep {what}</Button>
		<Button variant="danger" onclick={() => onresolve(true)}>Delete anyway</Button>
	{/snippet}
</Dialog>

<style>
	.body p {
		margin: 0 0 var(--space-2);
	}
	.body ul {
		margin: 0 0 var(--space-2);
		padding-left: var(--space-4);
		overflow-wrap: anywhere;
	}
</style>
