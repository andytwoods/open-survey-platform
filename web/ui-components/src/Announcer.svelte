<script lang="ts">
	import X from '@lucide/svelte/icons/x';
	import { announcer } from './live-region.svelte';
</script>

<div class="osp-visually-hidden" aria-live="polite" aria-atomic="true" data-testid="announcer">
	{announcer.polite}
</div>
<div class="osp-visually-hidden" aria-live="assertive" aria-atomic="true">
	{announcer.assertive}
</div>

<section class="toasts" aria-label="Notifications">
	<ol aria-live="polite" aria-relevant="additions">
		{#each announcer.toasts as t (t.id)}
			<li class="toast" data-kind={t.kind}>
				<span>{t.message}</span>
				<button
					type="button"
					class="dismiss"
					aria-label="Dismiss notification"
					onclick={() => announcer.dismiss(t.id)}
				>
					<X size={16} aria-hidden="true" />
				</button>
			</li>
		{/each}
	</ol>
</section>

<style>
	.toasts {
		position: fixed;
		inset-block-end: var(--space-4);
		inset-inline-end: var(--space-4);
		z-index: 60;
		pointer-events: none;
	}
	ol {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.toast {
		pointer-events: auto;
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-width: 16rem;
		max-width: 24rem;
		padding: var(--space-2) var(--space-2) var(--space-2) var(--space-4);
		background: var(--color-surface-raised);
		color: var(--color-text);
		border: 1px solid var(--color-border);
		border-inline-start: 4px solid var(--color-accent);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-lg);
		font-size: var(--text-sm);
	}
	.toast[data-kind='success'] {
		border-inline-start-color: var(--color-success);
	}
	.toast[data-kind='error'] {
		border-inline-start-color: var(--color-danger);
	}
	.toast span {
		flex: 1;
	}
	.dismiss {
		display: inline-grid;
		place-items: center;
		width: 1.75rem;
		height: 1.75rem;
		border: 0;
		border-radius: var(--radius-sm);
		background: transparent;
		color: var(--color-text-muted);
		cursor: pointer;
	}
	.dismiss:hover {
		background: var(--color-surface-sunken);
		color: var(--color-text);
	}
</style>
