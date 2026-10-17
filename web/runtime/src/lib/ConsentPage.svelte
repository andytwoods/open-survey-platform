<script lang="ts">
	/**
	 * The consent page (semantics.md §11, M5): shown before any question. Nothing about the
	 * participant is saved to the server until they agree (Session.agree). A decline shows a
	 * closing message; the server keeps no response.
	 */
	import { onMount } from 'svelte';
	import type { PageView } from '@osp/engine';
	import type { Session } from './session';
	import { plain } from './view-map';
	import { consentUi } from './consent-messages';
	import EndScreen from './EndScreen.svelte';

	let { session, view }: { session: Session; view: PageView } = $props();

	let heading = $state<HTMLElement | null>(null);
	let busy = $state(false);
	const declined = $derived(view.status === 'ended');
	const paragraphs = $derived(
		plain(view.consent?.text)
			.split(/\n\s*\n/)
			.map((p) => p.trim())
			.filter(Boolean)
	);

	onMount(() => heading?.focus());
	$effect(() => {
		if (declined) heading?.focus();
	});

	async function onAgree() {
		busy = true;
		try {
			await session.agree();
		} finally {
			busy = false;
		}
	}
	async function onDecline() {
		busy = true;
		try {
			await session.decline();
		} finally {
			busy = false;
		}
	}
</script>

<main class="page" id="main" lang={view.language}>
	{#if declined}
		<EndScreen end={view.end} testid="declined" fallbackBody={consentUi.declined} bind:heading />
	{:else}
		<h1 tabindex="-1" bind:this={heading}>{plain(view.title)}</h1>
		<div class="items consent" data-page={view.page} data-testid="consent">
			{#each paragraphs as p, i (i)}
				<p>{p}</p>
			{/each}
		</div>
		<div class="actions">
			<button type="button" class="btn primary" onclick={onAgree} disabled={busy} aria-busy={busy}>
				{plain(view.consent?.agree)}
			</button>
			<button type="button" class="btn" onclick={onDecline} disabled={busy}>
				{plain(view.consent?.decline)}
			</button>
		</div>
		<p class="muted">{consentUi.nothingSaved}</p>
	{/if}
</main>

<style>
	.page {
		flex: 1;
		box-sizing: border-box;
		inline-size: 100%;
		max-inline-size: 42rem;
		margin-inline: auto;
		padding-block: var(--space-5) var(--space-6);
		padding-inline: max(var(--space-4), env(safe-area-inset-left)) max(var(--space-4), env(safe-area-inset-right));
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		overflow-wrap: anywhere;
	}
	h1 {
		margin: 0;
		font-size: var(--text-xl);
		line-height: var(--leading-tight);
	}
	h1:focus {
		outline: none;
	}
	h1:focus-visible {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 4px;
	}
	.consent p {
		margin: 0 0 var(--space-3);
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
	}
	.muted {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.btn {
		min-block-size: 2.75rem;
		padding-inline: var(--space-4);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-weight: var(--weight-medium);
		cursor: pointer;
	}
	.btn.primary {
		border-color: var(--color-accent);
		background: var(--color-accent);
		color: var(--color-on-accent);
	}
	.btn:disabled {
		opacity: 0.6;
		cursor: progress;
	}
	.btn:focus-visible {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 2px;
	}
</style>
