<script lang="ts">
	/**
	 * The end redirect (end-of-survey plan §4.2, task EN2), shown under the ending once the
	 * server acknowledged the submit (or the decline). The ending's heading, text and status
	 * line are already on screen and the heading has focus when this mounts, so a screen
	 * reader hears them before the timer ends.
	 *
	 * - `auto`: one polite announcement ("You will be taken to {host} in {n} seconds. Use the
	 *   button to go now, or 'Stay on this page' to cancel."), a visible countdown that is
	 *   `aria-hidden` (so it is not read every second), a "Continue to {host}" link (go now)
	 *   and a "Stay on this page" button that cancels the navigation (WCAG 2.2.1, 3.2.5).
	 *   After cancelling, the link stays. The countdown is a number, never an animation, so
	 *   `prefers-reduced-motion` needs nothing special. Other keys and clicks do not pause it.
	 * - `auto` with delay 0: navigates as soon as it mounts (no screen in between).
	 * - `link`: the link only; nothing navigates by itself.
	 * - In the builder preview nothing navigates: the resolved URL is shown instead.
	 *
	 * The URL comes from the engine, which filled a declared https template with
	 * pattern-checked, encoded values and re-checked the origin; it is used as is.
	 */
	import { announcer } from '@osp/ui-components';
	import type { ResolvedRedirect } from '@osp/engine';
	import { onMount } from 'svelte';
	import { fill, ui } from './messages';
	import { plain } from './view-map';

	let {
		redirect,
		preview = false,
		navigate = (url: string) => location.assign(url)
	}: {
		redirect: ResolvedRedirect;
		/** The builder preview: show the URL, never go there. */
		preview?: boolean;
		navigate?: (url: string) => void;
	} = $props();

	const label = $derived(plain(redirect.label) || fill(ui.redirectTo, { host: redirect.host }));
	const automatic = $derived(redirect.url !== null && redirect.mode === 'auto' && !preview);
	let remaining = $state(0);
	let cancelled = $state(false);
	let timer: ReturnType<typeof setInterval> | null = null;
	const counting = $derived(automatic && !cancelled && remaining > 0);

	function stop() {
		if (timer !== null) clearInterval(timer);
		timer = null;
	}

	function stay() {
		stop();
		cancelled = true;
		announcer.announce(fill(ui.redirectStayed, { host: redirect.host }));
	}

	onMount(() => {
		const url = redirect.url;
		if (!url || !automatic) return;
		if (redirect.delay <= 0) {
			navigate(url);
			return;
		}
		remaining = redirect.delay;
		announcer.announce(fill(ui.redirectAnnounce, { host: redirect.host, n: redirect.delay }));
		timer = setInterval(() => {
			remaining -= 1;
			if (remaining <= 0) {
				stop();
				navigate(url);
			}
		}, 1000);
		return stop;
	});
</script>

{#if redirect.url}
	<section
		class="redirect"
		data-testid="redirect"
		data-mode={redirect.mode}
		data-state={preview ? 'preview' : counting ? 'counting' : cancelled ? 'cancelled' : 'link'}
	>
		{#if preview}
			<p class="muted">{ui.redirectPreview}</p>
			<p class="url"><code data-testid="redirect-url">{redirect.url}</code></p>
		{:else if counting}
			<p class="countdown" aria-hidden="true" data-testid="redirect-countdown">
				{fill(ui.redirectIn, { host: redirect.host, n: remaining })}
			</p>
		{:else if cancelled}
			<p class="muted">{fill(ui.redirectStayed, { host: redirect.host })}</p>
		{/if}
		<div class="actions">
			{#if preview}
				<span class="btn primary" aria-disabled="true" data-testid="redirect-go">{label}</span>
			{:else}
				<a class="btn primary" href={redirect.url} data-testid="redirect-go">{label}</a>
			{/if}
			{#if counting}
				<button type="button" class="btn" onclick={stay} data-testid="redirect-stay">{ui.redirectStay}</button>
			{/if}
		</div>
	</section>
{/if}

<style>
	.redirect {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.redirect p {
		margin: 0;
	}
	.muted {
		color: var(--color-text-muted);
	}
	.countdown {
		font-variant-numeric: tabular-nums;
	}
	.url {
		overflow-wrap: anywhere;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
	}
	.btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		box-sizing: border-box;
		min-block-size: 2.75rem;
		min-inline-size: 5.5rem;
		padding-inline: var(--space-4);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-weight: var(--weight-medium);
		text-decoration: none;
		cursor: pointer;
	}
	.btn.primary {
		border-color: var(--color-accent);
		background: var(--color-accent);
		color: var(--color-on-accent);
	}
	:global([data-osp-button='outline']) .btn.primary {
		background: transparent;
		color: var(--color-accent);
	}
	.btn[aria-disabled='true'] {
		opacity: 0.6;
		cursor: default;
	}
	.btn:hover:not([aria-disabled='true']) {
		filter: brightness(0.95);
	}
	.btn:focus-visible {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 2px;
	}
</style>
