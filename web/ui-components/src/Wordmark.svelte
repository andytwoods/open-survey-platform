<script lang="ts">
	import ClipboardList from '@lucide/svelte/icons/clipboard-list';

	let { label = 'Open Survey Platform' }: { label?: string } = $props();
</script>

<h1 class="wordmark">
	<ClipboardList aria-hidden="true" />
	<span>{label}</span>
</h1>

<style>
	.wordmark {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
</style>
