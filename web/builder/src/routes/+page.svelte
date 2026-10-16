<script lang="ts">
	import { page } from '$app/state';
	import { appTitle } from '#lib';
	import RequireAuth from '#lib/shell/RequireAuth.svelte';
	import Shell from '#lib/shell/Shell.svelte';
	import SurveyList from '#lib/shell/SurveyList.svelte';

	// `/?mock` is the W1 shell over static mock data (component and e2e tests, no backend).
	const mock = page.url.searchParams.has('mock');
</script>

<svelte:head>
	<title>{appTitle}</title>
</svelte:head>

{#if mock}
	<Shell />
{:else}
	<RequireAuth>
		<SurveyList />
	</RequireAuth>
{/if}
