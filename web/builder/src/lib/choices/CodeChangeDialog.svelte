<script lang="ts">
	import { Button, Dialog } from '@osp/ui-components';
	import { untrack } from 'svelte';

	/**
	 * Confirms a code change on a survey that has published versions: responses already
	 * collected store the old code, so old and new data stop lining up for this choice.
	 * Closing the dialog (Escape, ×, Keep) keeps the old code.
	 */
	let {
		change,
		publishedVersions,
		onresolve
	}: {
		change: { from: string; to: string } | null;
		publishedVersions: number;
		onresolve: (ok: boolean) => void;
	} = $props();

	// Follows `change`; closing the dialog sets it false until the next change.
	let open = $derived(!!change);
	$effect(() => {
		if (!open && untrack(() => change)) onresolve(false);
	});

	const versions = $derived(`${publishedVersions} published version${publishedVersions === 1 ? '' : 's'}`);
</script>

<Dialog bind:open title="Change a code with data behind it?" size="sm">
	{#if change}
		<div class="body" data-testid="code-change-warning">
			<p>
				This survey has {versions}. Responses already collected store code
				<code>{change.from}</code> for this choice; new responses will store
				<code>{change.to}</code>.
			</p>
			<p>Old and new data will not match for this choice. To keep them comparable, change the label instead.</p>
		</div>
	{/if}
	{#snippet footer()}
		<Button onclick={() => onresolve(false)}>Keep code {change?.from}</Button>
		<Button variant="danger" onclick={() => onresolve(true)}>Change to {change?.to}</Button>
	{/snippet}
</Dialog>

<style>
	.body p {
		margin: 0 0 var(--space-2);
	}
	code {
		font-family: var(--font-mono, ui-monospace, monospace);
		font-weight: var(--weight-bold);
	}
</style>
