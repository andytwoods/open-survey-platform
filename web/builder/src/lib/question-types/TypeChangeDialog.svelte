<script lang="ts" module>
	export interface TypeChangeRequest {
		/** Type names as the picker shows them, e.g. "Single choice". */
		from: string;
		to: string;
		/** Conditions or piped texts elsewhere that the change would break (0: none). */
		conflicts: number;
		publishedVersions: number;
	}
</script>

<script lang="ts">
	import { Button, Dialog } from '@osp/ui-components';
	import { untrack } from 'svelte';

	/**
	 * Confirms a type change that needs it: other conditions or piping use this answer in
	 * a way the new type does not support (the op said `op.type_conflict`), or the survey
	 * has published versions whose responses keep the old type. Closing keeps the old type.
	 */
	let {
		request,
		onresolve
	}: {
		request: TypeChangeRequest | null;
		onresolve: (ok: boolean) => void;
	} = $props();

	let open = $derived(!!request);
	$effect(() => {
		if (!open && untrack(() => request)) onresolve(false);
	});

	const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
</script>

<Dialog bind:open title="Change the question type?" size="sm">
	{#if request}
		<div class="body" data-testid="type-change-warning">
			{#if request.conflicts > 0}
				<p>
					This changes {plural(request.conflicts, 'condition or piped text', 'conditions or piped texts')}
					that use this answer: they will not work with a {request.to} question. They stay in the survey,
					marked as problems to fix.
				</p>
			{/if}
			{#if request.publishedVersions > 0}
				<p>
					This survey has {plural(request.publishedVersions, 'published version', 'published versions')}.
					Responses already collected keep the old type ({request.from}); exports show old and new answers in
					separate columns.
				</p>
			{/if}
		</div>
	{/if}
	{#snippet footer()}
		<Button onclick={() => onresolve(false)}>Keep {request?.from}</Button>
		<Button variant={request && request.conflicts > 0 ? 'danger' : 'primary'} onclick={() => onresolve(true)}>
			Change to {request?.to}
		</Button>
	{/snippet}
</Dialog>

<style>
	.body p {
		margin: 0 0 var(--space-2);
	}
</style>
