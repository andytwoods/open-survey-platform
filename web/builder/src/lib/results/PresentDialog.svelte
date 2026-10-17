<script lang="ts">
	import { Button, Dialog } from '@osp/ui-components';
	import { BATCH_K, BATCH_MAX_WAIT_MS, type PresentRefresh } from './live';
	import { presentation } from './presentation.svelte';

	/**
	 * The Present dialog (task LV4, planning/live-results.md LV-D5, lead decision 1): before
	 * the screen goes up, the presenter chooses whether it is live and how it refreshes (in
	 * batches by default: k new responses or the time cap; or every change), whether small
	 * cells are hidden on screen (on by default; switching it off shows a warning, and the
	 * URL can never do it), and fullscreen. Each opening starts from the safe defaults.
	 */
	let {
		open = $bindable(false),
		hasLive,
		liveOn,
		onstart
	}: {
		open?: boolean;
		/** The page can poll (a Live toggle exists). */
		hasLive: boolean;
		/** Live is on now (the dialog's default). */
		liveOn: boolean;
		/** Start presenting with these choices. */
		onstart: (choice: { live: boolean; refresh: PresentRefresh; exact: boolean; fullscreen: boolean }) => void;
	} = $props();

	const uid = $props.id();
	let live = $state(false);
	let refresh = $state<PresentRefresh>('batched');
	let exact = $state(false);
	let fullscreen = $state(false);
	let starting = false;

	$effect(() => {
		// Each opening: live as it is now, the cadence the URL or last run chose, suppressed, windowed.
		if (!open) return;
		live = hasLive && liveOn;
		refresh = presentation.refresh;
		exact = false;
		fullscreen = false;
	});

	const minutes = Math.round(BATCH_MAX_WAIT_MS / 60_000);

	function start() {
		starting = true;
		open = false;
		onstart({ live: hasLive && live, refresh, exact, fullscreen });
	}

	/** Starting: the opener is gone (only the cards show), so the page puts focus on Exit presentation. */
	function onClose(e: Event) {
		if (!starting) return;
		starting = false;
		e.preventDefault();
	}
</script>

<Dialog bind:open title="Present results" description="Only the cards, on the theme’s background. Escape or the floating button brings everything back." onCloseAutoFocus={onClose}>
	<div class="body">
		{#if hasLive}
			<fieldset class="group">
				<legend>Live</legend>
				<label class="check"><input type="checkbox" bind:checked={live} data-testid="present-live" /> Refresh as responses arrive</label>
				{#if live}
					<div class="choices" role="radiogroup" aria-label="Refresh">
						<label class="check">
							<input type="radio" name="{uid}-refresh" value="batched" bind:group={refresh} data-testid="present-batched" />
							<span>In batches: when {BATCH_K} new responses have arrived, or {minutes} minutes have passed <span class="muted">(recommended)</span></span>
						</label>
						<label class="check">
							<input type="radio" name="{uid}-refresh" value="every" bind:group={refresh} data-testid="present-every" />
							<span>On every change</span>
						</label>
					</div>
				{/if}
			</fieldset>
		{/if}

		<fieldset class="group">
			<legend>Small counts</legend>
			<label class="check">
				<input type="checkbox" checked={!exact} onchange={(e) => (exact = !(e.currentTarget as HTMLInputElement).checked)} data-testid="present-hide" />
				<span>Hide counts below {BATCH_K} on screen <span class="muted">(recommended)</span></span>
			</label>
			{#if exact}
				<p class="warning" role="alert" data-testid="present-exact-warning">
					The screen will show exact counts{live ? ', redrawn as responses arrive' : ''}. In a room, the person who
					just pressed Submit can be told from the card that moved. Show exact counts only to people who may see
					individual answers.
				</p>
			{/if}
		</fieldset>

		<fieldset class="group">
			<legend>Screen</legend>
			<label class="check"><input type="checkbox" bind:checked={fullscreen} data-testid="present-fullscreen" /> Fullscreen</label>
			{#if hasLive && live}
				<span class="hint">While live, the screen is kept awake where the browser allows it.</span>
			{/if}
		</fieldset>
	</div>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (open = false)}>Cancel</Button>
		<Button variant="primary" onclick={start} data-testid="present-start">Start presenting</Button>
	{/snippet}
</Dialog>

<style>
	.body {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		min-width: 0;
	}
	.group {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1) var(--space-3);
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		min-width: 0;
	}
	legend {
		padding: 0 var(--space-1);
		font-size: var(--text-sm);
		font-weight: var(--weight-bold);
	}
	.check {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-height: 2.75rem;
		font-size: var(--text-sm);
	}
	.choices {
		display: flex;
		flex-direction: column;
		flex-basis: 100%;
		padding-inline-start: var(--space-4);
	}
	.muted {
		color: var(--color-text-muted);
	}
	.hint {
		flex-basis: 100%;
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.warning {
		flex-basis: 100%;
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-inline-start: 4px solid var(--color-warning);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		font-size: var(--text-sm);
	}
	input:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}
</style>
