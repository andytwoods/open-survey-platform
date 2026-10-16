<script lang="ts">
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import { Button } from '@osp/ui-components';

	/** Shown when a 409 replay no longer validates: someone else's edit won. */
	let {
		message,
		onreload,
		ondismiss
	}: { message: string; onreload: () => void; ondismiss: () => void } = $props();
</script>

<div class="banner" role="alert" data-testid="conflict-banner">
	<TriangleAlert size={18} aria-hidden="true" />
	<p>{message}</p>
	<div class="actions">
		<Button size="sm" onclick={onreload}>Reload</Button>
		<Button size="sm" variant="ghost" onclick={ondismiss}>Dismiss</Button>
	</div>
</div>

<style>
	.banner {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-4);
		border-bottom: 1px solid var(--color-warning);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font-size: var(--text-sm);
	}
	.banner :global(svg) {
		flex: none;
		color: var(--color-warning);
	}
	p {
		flex: 1;
		margin: 0;
	}
	.actions {
		display: flex;
		gap: var(--space-2);
	}
</style>
