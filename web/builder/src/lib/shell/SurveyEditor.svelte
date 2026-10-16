<script lang="ts">
	import { resolve } from '$app/paths';
	import type { BuilderView } from '../appearance/commands';
	import { storeFor } from '../sync/stores';
	import Shell from './Shell.svelte';

	/** Loads a real survey into the shell. */
	let { surveyId, view = 'editor' }: { surveyId: string; view?: BuilderView } = $props();

	const store = $derived(storeFor(surveyId));

	$effect(() => {
		const s = store;
		if (!s.survey && !s.loading && !s.error) void s.load(surveyId);
	});
</script>

{#if store.survey}
	<Shell {view} {store} />
{:else if store.error && !store.loading}
	<main class="state">
		<h1>Could not open this survey</h1>
		<p role="alert">{store.error}</p>
		<p><a href={resolve('/')}>Back to your surveys</a></p>
	</main>
{:else}
	<main class="state">
		<p role="status">Loading survey…</p>
	</main>
{/if}

<style>
	.state {
		max-width: 40rem;
		margin: 0 auto;
		padding: var(--space-6) var(--space-4);
		color: var(--color-text);
	}
	h1 {
		font-size: var(--text-lg);
	}
	a {
		color: var(--color-accent);
	}
</style>
