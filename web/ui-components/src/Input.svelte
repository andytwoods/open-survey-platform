<script lang="ts">
	import type { HTMLInputAttributes } from 'svelte/elements';

	/** Labelled text input. The label is always rendered (visually hidden if `hideLabel`). */
	type Props = Omit<HTMLInputAttributes, 'value'> & {
		label: string;
		value?: string;
		description?: string;
		error?: string;
		hideLabel?: boolean;
		ref?: HTMLInputElement | null;
	};

	let {
		label,
		value = $bindable(''),
		description,
		error,
		hideLabel = false,
		ref = $bindable(null),
		id: givenId,
		class: className = '',
		...rest
	}: Props = $props();

	const uid = $props.id();
	const id = $derived(givenId ?? `osp-input-${uid}`);
	const describedBy = $derived(
		[description && `${id}-desc`, error && `${id}-err`].filter(Boolean).join(' ') || undefined
	);
</script>

<div class="osp-field {className}">
	<label for={id} class:osp-visually-hidden={hideLabel}>{label}</label>
	<input
		bind:this={ref}
		bind:value
		{id}
		class="osp-input"
		aria-describedby={describedBy}
		aria-invalid={error ? 'true' : undefined}
		{...rest}
	/>
	{#if description}<p id="{id}-desc" class="hint">{description}</p>{/if}
	{#if error}<p id="{id}-err" class="error">{error}</p>{/if}
</div>

<style>
	.osp-field {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	label {
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}
	.osp-input {
		height: var(--control-height);
		padding: 0 var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
	}
	.osp-input[aria-invalid='true'] {
		border-color: var(--color-danger);
	}
	.hint,
	.error {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.error {
		color: var(--color-danger);
	}
</style>
