<script lang="ts" module>
	export interface SelectOption {
		value: string;
		label: string;
		disabled?: boolean;
	}
</script>

<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import { Label, Select } from 'bits-ui';

	/** Single-choice select with a visible label (Bits UI listbox underneath). */
	let {
		label,
		options,
		value = $bindable(''),
		placeholder = 'Choose…',
		hideLabel = false,
		disabled = false,
		onValueChange
	}: {
		label: string;
		options: SelectOption[];
		value?: string;
		placeholder?: string;
		hideLabel?: boolean;
		disabled?: boolean;
		onValueChange?: (value: string) => void;
	} = $props();

	const uid = $props.id();
	const labelId = `osp-select-${uid}-label`;
	// The trigger's name is "<label> <current value>", so it contains its visible text.
	const valueId = `osp-select-${uid}-value`;
	const listboxId = `osp-select-${uid}-listbox`;
	const selectedLabel = $derived(options.find((o) => o.value === value)?.label);
</script>

<div class="osp-field">
	<Label.Root id={labelId} class={hideLabel ? 'osp-visually-hidden' : 'osp-label'}>{label}</Label.Root>
	<Select.Root type="single" bind:value items={options} {disabled} {onValueChange}>
		<!-- role=combobox: Bits puts aria-activedescendant on the trigger, which a plain button may not carry. -->
		<Select.Trigger
			class="osp-select-trigger"
			role="combobox"
			aria-controls={listboxId}
			aria-labelledby="{labelId} {valueId}"
		>
			<span id={valueId} class:placeholder={!selectedLabel}>{selectedLabel ?? placeholder}</span>
			<ChevronDown size={16} aria-hidden="true" />
		</Select.Trigger>
		<!-- Rendered in place (inside the page's landmarks) and positioned `fixed`, so pane
		     overflow does not clip it. -->
		<Select.Portal disabled>
			<Select.Content
				id={listboxId}
				class="osp-select-content"
				sideOffset={4}
				strategy="fixed"
				aria-labelledby={labelId}
			>
				<Select.Viewport>
					{#each options as option (option.value)}
						<Select.Item
							class="osp-select-item"
							value={option.value}
							label={option.label}
							disabled={option.disabled}
						>
							{#snippet children({ selected })}
								<span>{option.label}</span>
								{#if selected}<Check size={16} aria-hidden="true" />{/if}
							{/snippet}
						</Select.Item>
					{/each}
				</Select.Viewport>
			</Select.Content>
		</Select.Portal>
	</Select.Root>
</div>

<style>
	.osp-field {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	:global(.osp-label) {
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}
	:global(.osp-select-trigger) {
		display: inline-flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		min-width: 10rem;
		height: var(--control-height);
		padding: 0 var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
		cursor: pointer;
	}
	.placeholder {
		color: var(--color-text-muted);
	}
	:global(.osp-select-content) {
		z-index: 70;
		min-width: var(--bits-select-anchor-width);
		padding: var(--space-1);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		box-shadow: var(--shadow-lg);
	}
	:global(.osp-select-item) {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
		cursor: pointer;
	}
	:global(.osp-select-item[data-highlighted]) {
		background: var(--color-selected);
	}
	:global(.osp-select-item[data-disabled]) {
		color: var(--color-text-muted);
		text-decoration: line-through;
		cursor: not-allowed;
	}
</style>
