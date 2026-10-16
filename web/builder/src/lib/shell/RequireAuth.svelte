<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import type { Snippet } from 'svelte';
	import { onMount } from 'svelte';
	import { auth } from '../auth.svelte';

	/** Auth guard: renders `children` only when signed in, else sends you to /login. */
	let { children }: { children: Snippet } = $props();

	function toLogin() {
		const next = page.url.pathname + page.url.search;
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- resolved path plus a query
		void goto(`${resolve('/login')}?next=${encodeURIComponent(next)}`, { replaceState: true });
	}

	onMount(() => {
		if (!auth.checked) void auth.refresh();
	});

	// Signed out elsewhere (logout, or a 401 mid-edit).
	$effect(() => {
		if (auth.checked && !auth.me) toLogin();
	});
</script>

{#if auth.me}
	{@render children()}
{:else}
	<p class="checking" role="status">Checking sign-in…</p>
{/if}

<style>
	.checking {
		margin: 0;
		padding: var(--space-6);
		color: var(--color-text-muted);
	}
</style>
