<script lang="ts">
	/**
	 * Withdrawal (semantics.md §11, M5): on the end screen and on a resumed session, the
	 * participant can delete their response. Two steps, so a stray tap deletes nothing.
	 */
	import { tick } from 'svelte';
	import type { Session } from './session';
	import { consentUi } from './consent-messages';

	let { session, version }: { session: Session; version: number } = $props();

	let confirming = $state(false);
	let failed = $state(false);
	let busy = $state(false);
	let done = $state<HTMLElement | null>(null);
	const withdrawn = $derived.by(() => {
		void version;
		return session.withdrawn;
	});

	async function onConfirm() {
		busy = true;
		failed = false;
		const ok = await session.withdraw();
		busy = false;
		failed = !ok;
		if (ok) {
			await tick();
			done?.focus();
		}
	}
</script>

{#if withdrawn}
	<section class="withdraw" data-testid="withdrawn">
		<h2 tabindex="-1" bind:this={done}>{consentUi.withdrawn}</h2>
		<p>{consentUi.withdrawnHelp}</p>
	</section>
{:else}
	<section class="withdraw">
		{#if !confirming}
			<button type="button" class="link" onclick={() => (confirming = true)}>{consentUi.withdraw}</button>
		{:else}
			<p>{consentUi.withdrawHelp}</p>
			<div class="row">
				<button type="button" class="btn danger" onclick={onConfirm} disabled={busy} aria-busy={busy}>
					{busy ? consentUi.withdrawing : consentUi.withdrawConfirm}
				</button>
				<button type="button" class="btn" onclick={() => (confirming = false)} disabled={busy}>
					{consentUi.withdrawCancel}
				</button>
			</div>
			{#if failed}<p role="alert">{consentUi.withdrawFailed}</p>{/if}
		{/if}
	</section>
{/if}

<style>
	.withdraw {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	h2 {
		margin: 0;
		font-size: var(--text-lg);
	}
	h2:focus {
		outline: none;
	}
	p {
		margin: 0;
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
	}
	.link {
		align-self: flex-start;
		min-block-size: 2.75rem;
		padding: 0;
		border: 0;
		background: none;
		color: var(--color-accent);
		font: inherit;
		text-decoration: underline;
		cursor: pointer;
	}
	.btn {
		min-block-size: 2.75rem;
		padding-inline: var(--space-4);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		cursor: pointer;
	}
	.btn.danger {
		border-color: var(--color-danger, var(--color-accent));
	}
	.link:focus-visible,
	.btn:focus-visible {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 2px;
	}
</style>
