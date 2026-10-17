<script lang="ts">
	import { page } from '$app/state';
	import { appTitle } from '#lib';
	import RequireAuth from '#lib/shell/RequireAuth.svelte';
	import SurveyEditor from '#lib/shell/SurveyEditor.svelte';
</script>

<svelte:head>
	<title>Settings · {appTitle}</title>
</svelte:head>

<RequireAuth>
	{#key page.params.id}
		<SurveyEditor surveyId={page.params.id ?? ''} view="settings" />
	{/key}
</RequireAuth>
