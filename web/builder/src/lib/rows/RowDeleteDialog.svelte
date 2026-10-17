<script lang="ts">
	import { Button, Dialog } from '@osp/ui-components';
	import { untrack } from 'svelte';

	/**
	 * Confirms deleting a grid row that conditions or piping still refer to (the server
	 * refused the plain delete with `op.dangling_ref`). Deleting anyway leaves those
	 * references broken: they show up as errors to fix. Closing the dialog (Escape, ×,
	 * Keep) keeps the row.
	 */
	let {
		request,
		onresolve
	}: {
		request: { name: string; variable: string; sites: readonly string[] } | null;
		onresolve: (ok: boolean) => void;
	} = $props();

	// Follows `request`; closing the dialog sets it false until the next request.
	let open = $derived(!!request);
	$effect(() => {
		if (!open && untrack(() => request)) onresolve(false);
	});

	const count = $derived(request?.sites.length ?? 0);
</script>

<Dialog bind:open title="Delete a row that is still used?" size="sm">
	{#if request}
		<div class="body" data-testid="row-delete-warning">
			<p>
				Row <strong>{request.name}</strong> (<code>{request.variable}</code>) is used in {count}
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
		<Button onclick={() => onresolve(false)}>Keep row</Button>
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
	}
	code {
		font-family: var(--font-mono, ui-monospace, monospace);
		overflow-wrap: anywhere;
	}
</style>
