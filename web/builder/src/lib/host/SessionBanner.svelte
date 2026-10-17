<script lang="ts">
	import LockKeyhole from '@lucide/svelte/icons/lock-keyhole';
	import ShieldAlert from '@lucide/svelte/icons/shield-alert';
	import { Button } from '@osp/ui-components';
	import type { Session } from './session.svelte';

	/**
	 * The host session ended (401) or this account may not do that (403), D9. Edits not yet
	 * saved stay queued on this page; nothing is sent until the session is back.
	 */
	let { session }: { session: Session } = $props();
</script>

{#if session.status === 'ended' && !session.reloading}
	<div class="banner" role="alert" data-testid="session-ended">
		<LockKeyhole size={18} aria-hidden="true" />
		<p>Your session ended. Sign in again to keep working; changes not yet saved are kept on this page.</p>
		{#if session.signInUrl}
			<a class="action" href={session.signInUrl}>Sign in again</a>
		{:else}
			<Button size="sm" onclick={() => session.reloadNow()}>Reload to sign in</Button>
		{/if}
	</div>
{:else if session.status === 'forbidden'}
	<div class="banner" role="alert" data-testid="no-access">
		<ShieldAlert size={18} aria-hidden="true" />
		<p>You don't have access to this lab, or to that action. Ask a lab owner if you need it.</p>
		<Button size="sm" variant="ghost" onclick={() => session.dismissForbidden()}>Dismiss</Button>
	</div>
{/if}

<style>
	.banner {
		position: fixed;
		inset-block-start: 0;
		inset-inline: 0;
		z-index: 1000;
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-4);
		border-bottom: 2px solid var(--color-danger);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font-size: var(--text-sm);
		box-shadow: var(--shadow-sm);
	}
	.banner :global(svg) {
		flex: none;
		color: var(--color-danger);
	}
	p {
		flex: 1;
		margin: 0;
	}
	.action {
		color: var(--color-accent);
		font-weight: var(--weight-medium);
	}
</style>
