<script lang="ts">
	import { Button, Dialog, Input } from '@osp/ui-components';
	import { nameProblem, type LayoutsController } from './layouts.svelte';

	/**
	 * The saved-layout bar (task V5b): pick a layout (or the default view), see whether the
	 * page has unsaved changes, and Save / Save as… / Rename… / Open by default / Delete….
	 * Failures (a duplicate name: 409; a refused layout: 422) show as an alert here.
	 */
	let { layouts }: { layouts: LayoutsController } = $props();

	const uid = $props.id();
	const id = (s: string) => `${uid}-${s}`;
	const current = $derived(layouts.current);
	const dirty = $derived(layouts.dirty);
	const isDefault = $derived(!!current && current.id === layouts.defaultId);

	let saveAsOpen = $state(false);
	let renameOpen = $state(false);
	let deleteOpen = $state(false);
	let name = $state('');
	let makeDefault = $state(false);
	let tried = $state(false);
	const problem = $derived(tried ? nameProblem(name) : null);

	function openSaveAs() {
		name = current ? `${current.name} (copy)` : '';
		makeDefault = false;
		tried = false;
		saveAsOpen = true;
	}

	function openRename() {
		name = current?.name ?? '';
		tried = false;
		renameOpen = true;
	}

	/** The failure of the dialog's last submit (shown inside the dialog, which stays open). */
	let dialogError = $state<string | null>(null);
	$effect(() => {
		if (!saveAsOpen && !renameOpen) dialogError = null;
	});

	async function submitSaveAs(e: SubmitEvent) {
		e.preventDefault();
		tried = true;
		if (nameProblem(name)) return;
		if (await layouts.saveAs(name, makeDefault)) saveAsOpen = false;
		else dialogError = layouts.error;
	}

	async function submitRename(e: SubmitEvent) {
		e.preventDefault();
		tried = true;
		if (nameProblem(name)) return;
		if (await layouts.rename(name)) renameOpen = false;
		else dialogError = layouts.error;
	}

	async function confirmDelete() {
		await layouts.remove();
		deleteOpen = false;
	}
</script>

<section class="layout-bar" aria-labelledby={id('h')} data-testid="layout-bar">
	<h3 id={id('h')} class="visually-hidden">Saved layouts</h3>
	<div class="pick">
		<label for={id('pick')}>Layout</label>
		<select
			id={id('pick')}
			value={layouts.currentId ?? ''}
			disabled={layouts.busy}
			onchange={(e) => void layouts.open((e.currentTarget as HTMLSelectElement).value || null)}
		>
			<option value="">Default view (no saved layout)</option>
			{#each layouts.layouts as l (l.id)}
				<option value={l.id}>{l.name}{l.id === layouts.defaultId ? ' (opens by default)' : ''}</option>
			{/each}
		</select>
		<span class="unsaved" data-testid="layout-unsaved" hidden={!dirty}>
			<span class="dot" aria-hidden="true"></span>Unsaved changes
		</span>
	</div>
	<div class="actions">
		{#if current}
			<Button variant="primary" disabled={layouts.busy || !dirty} onclick={() => void layouts.save()}>Save layout</Button>
		{/if}
		<Button disabled={layouts.busy} onclick={openSaveAs}>Save as…</Button>
		{#if current}
			<Button disabled={layouts.busy} onclick={openRename}>Rename…</Button>
			{#if isDefault}
				<Button disabled={layouts.busy} onclick={() => void layouts.setDefault(true)}>Don’t open by default</Button>
			{:else}
				<Button disabled={layouts.busy} onclick={() => void layouts.setDefault()}>Open by default</Button>
			{/if}
			<Button variant="danger" disabled={layouts.busy} onclick={() => (deleteOpen = true)}>Delete…</Button>
		{/if}
	</div>
	<p class="status" role="status" data-testid="layout-status">{layouts.error ? '' : layouts.status}</p>
	{#if layouts.error}
		<p class="error" role="alert" data-testid="layout-error">{layouts.error}</p>
	{/if}
</section>

<Dialog bind:open={saveAsOpen} title="Save layout as" description="Saves the filters, charts, order, hidden cards and captions. Never any responses." size="sm">
	<form class="form" onsubmit={submitSaveAs} novalidate>
		<Input label="Name" bind:value={name} maxlength={200} error={problem ?? undefined} autocomplete="off" />
		{#if dialogError}<p class="error" role="alert" data-testid="layout-dialog-error">{dialogError}</p>{/if}
		<label class="check"><input type="checkbox" bind:checked={makeDefault} /> Open this layout by default</label>
		<div class="buttons">
			<Button type="button" variant="ghost" onclick={() => (saveAsOpen = false)}>Cancel</Button>
			<Button type="submit" variant="primary" disabled={layouts.busy}>Save</Button>
		</div>
	</form>
</Dialog>

<Dialog bind:open={renameOpen} title="Rename layout" size="sm">
	<form class="form" onsubmit={submitRename} novalidate>
		<Input label="Name" bind:value={name} maxlength={200} error={problem ?? undefined} autocomplete="off" />
		{#if dialogError}<p class="error" role="alert" data-testid="layout-dialog-error">{dialogError}</p>{/if}
		<div class="buttons">
			<Button type="button" variant="ghost" onclick={() => (renameOpen = false)}>Cancel</Button>
			<Button type="submit" variant="primary" disabled={layouts.busy}>Rename</Button>
		</div>
	</form>
</Dialog>

<Dialog
	bind:open={deleteOpen}
	title="Delete layout?"
	description={current ? `“${current.name}” is deleted for everyone in the lab. The page keeps showing it until you change it.` : undefined}
	size="sm"
>
	<div class="buttons">
		<Button type="button" variant="ghost" onclick={() => (deleteOpen = false)}>Cancel</Button>
		<Button type="button" variant="danger" disabled={layouts.busy} onclick={confirmDelete}>Delete layout</Button>
	</div>
</Dialog>

<style>
	.layout-bar {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: var(--space-2) var(--space-4);
		padding: var(--space-3) var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}
	.pick {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1) var(--space-2);
		min-width: 0;
		max-width: 100%;
	}
	.pick label {
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}
	select {
		max-width: 100%;
		min-width: 0;
		min-height: 2.75rem;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
	}
	select:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}
	.unsaved {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}
	.unsaved[hidden] {
		display: none;
	}
	.dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: var(--radius-full);
		background: var(--color-warning);
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.status,
	.error {
		flex-basis: 100%;
		margin: 0;
		font-size: var(--text-sm);
	}
	.status {
		color: var(--color-text-muted);
	}
	.status:empty {
		display: none;
	}
	.error {
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-danger);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
	}
	.form {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.check {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-height: 2.75rem;
		font-size: var(--text-sm);
	}
	.check input {
		width: 1.125rem;
		height: 1.125rem;
		margin: 0;
		accent-color: var(--color-accent);
	}
	.buttons {
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: var(--space-2);
	}
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}
</style>
