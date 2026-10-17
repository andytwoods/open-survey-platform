<script lang="ts">
	import type { Component } from 'svelte';
	import { onMount } from 'svelte';
	import { api } from '../api';
	import { session } from './session.svelte';
	import SessionBanner from './SessionBanner.svelte';

	/** Every builder page: the session banner, then the page itself. */
	let {
		page: Page,
		pageProps,
		identity
	}: {
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		page: Component<any>;
		pageProps: Record<string, unknown>;
		/** Ask GET /api/me who the host says this is (header name, lab choice). */
		identity: boolean;
	} = $props();

	onMount(() => {
		if (!identity) return;
		void api
			.GET('/api/me')
			.then(({ data }) => {
				if (data) session.identity = data;
			})
			.catch(() => {
				// Offline: the page shows its own connection state.
			});
	});
</script>

<SessionBanner {session} />
<Page {...pageProps} />
