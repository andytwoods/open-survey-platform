<script lang="ts">
	import X from '@lucide/svelte/icons/x';
	import { Dialog } from 'bits-ui';
	import type { Snippet } from 'svelte';

	/**
	 * Modal dialog: focus is trapped inside, Escape closes, focus returns to the opener.
	 * `title` is required (it names the dialog); hide it visually with `hideTitle`.
	 */
	let {
		open = $bindable(false),
		title,
		description,
		hideTitle = false,
		size = 'md',
		placement = 'center',
		showClose = true,
		onCloseAutoFocus,
		children,
		footer
	}: {
		open?: boolean;
		title: string;
		description?: string;
		hideTitle?: boolean;
		size?: 'sm' | 'md' | 'lg';
		placement?: 'center' | 'top';
		showClose?: boolean;
		onCloseAutoFocus?: (e: Event) => void;
		children?: Snippet;
		footer?: Snippet;
	} = $props();
</script>

<Dialog.Root bind:open>
	<Dialog.Portal>
		<Dialog.Overlay class="osp-dialog-overlay" />
		<Dialog.Content
			class="osp-dialog"
			data-size={size}
			data-placement={placement}
			{onCloseAutoFocus}
		>
			<div class="osp-dialog-header" class:osp-visually-hidden={hideTitle}>
				<Dialog.Title class="osp-dialog-title">{title}</Dialog.Title>
				{#if description}
					<Dialog.Description class="osp-dialog-description">{description}</Dialog.Description>
				{/if}
			</div>
			{@render children?.()}
			{#if footer}<div class="osp-dialog-footer">{@render footer()}</div>{/if}
			{#if showClose}
				<Dialog.Close class="osp-dialog-close" aria-label="Close dialog">
					<X size={18} aria-hidden="true" />
				</Dialog.Close>
			{/if}
		</Dialog.Content>
	</Dialog.Portal>
</Dialog.Root>

<style>
	:global(.osp-dialog-overlay) {
		position: fixed;
		inset: 0;
		z-index: 50;
		background: var(--color-overlay);
	}
	:global(.osp-dialog) {
		position: fixed;
		z-index: 51;
		left: 50%;
		top: 50%;
		transform: translate(-50%, -50%);
		width: min(32rem, calc(100vw - 2 * var(--space-4)));
		max-height: calc(100dvh - 2 * var(--space-6));
		overflow: auto;
		padding: var(--space-5);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		background: var(--color-surface-raised);
		color: var(--color-text);
		box-shadow: var(--shadow-lg);
	}
	:global(.osp-dialog[data-size='sm']) {
		width: min(24rem, calc(100vw - 2 * var(--space-4)));
	}
	:global(.osp-dialog[data-size='lg']) {
		width: min(44rem, calc(100vw - 2 * var(--space-4)));
	}
	:global(.osp-dialog[data-placement='top']) {
		top: 12vh;
		transform: translateX(-50%);
	}
	.osp-dialog-header {
		margin-block-end: var(--space-4);
		padding-inline-end: var(--space-6);
	}
	:global(.osp-dialog-title) {
		margin: 0;
		font-size: var(--text-lg);
		font-weight: var(--weight-bold);
		line-height: var(--leading-tight);
	}
	:global(.osp-dialog-description) {
		margin: var(--space-2) 0 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.osp-dialog-footer {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-2);
		margin-block-start: var(--space-5);
	}
	:global(.osp-dialog-close) {
		position: absolute;
		top: var(--space-3);
		right: var(--space-3);
		display: inline-grid;
		place-items: center;
		width: 2rem;
		height: 2rem;
		border: 0;
		border-radius: var(--radius-sm);
		background: transparent;
		color: var(--color-text-muted);
		cursor: pointer;
	}
	:global(.osp-dialog-close:hover) {
		background: var(--color-surface-sunken);
		color: var(--color-text);
	}
</style>
