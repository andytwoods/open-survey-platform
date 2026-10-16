<script lang="ts" module>
	export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
	export type ButtonSize = 'sm' | 'md';
</script>

<script lang="ts">
	import { Button as BitsButton } from 'bits-ui';
	import type { ComponentProps } from 'svelte';

	type Props = ComponentProps<typeof BitsButton.Root> & {
		variant?: ButtonVariant;
		size?: ButtonSize;
	};

	let {
		variant = 'secondary',
		size = 'md',
		class: className = '',
		ref = $bindable(null),
		children,
		...rest
	}: Props = $props();
</script>

<BitsButton.Root
	bind:ref
	class="osp-button {className}"
	data-variant={variant}
	data-size={size}
	{...rest}
>
	{@render children?.()}
</BitsButton.Root>

<style>
	:global(.osp-button) {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		height: var(--control-height);
		padding: 0 var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
		line-height: 1;
		white-space: nowrap;
		cursor: pointer;
		text-decoration: none;
		transition: background var(--duration-fast);
	}
	:global(.osp-button[data-size='sm']) {
		height: 1.875rem;
		padding: 0 var(--space-2);
	}
	:global(.osp-button:hover) {
		background: var(--color-surface-sunken);
	}
	:global(.osp-button[data-variant='primary']) {
		background: var(--color-accent);
		border-color: var(--color-accent);
		color: var(--color-on-accent);
	}
	:global(.osp-button[data-variant='primary']:hover) {
		background: var(--color-accent-hover);
		border-color: var(--color-accent-hover);
	}
	:global(.osp-button[data-variant='ghost']) {
		background: transparent;
		border-color: transparent;
	}
	:global(.osp-button[data-variant='ghost']:hover) {
		background: var(--color-surface-sunken);
	}
	:global(.osp-button[data-variant='danger']) {
		color: var(--color-danger);
	}
	:global(.osp-button:disabled),
	:global(.osp-button[aria-disabled='true']) {
		opacity: 0.55;
		cursor: not-allowed;
	}
</style>
