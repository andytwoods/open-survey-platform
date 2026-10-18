<script lang="ts">
	import { Button, Dialog, Input } from '@osp/ui-components';

	/**
	 * The link dialog (planning/rich-text.md §9): an https URL (RT-D7), the link text when
	 * the caret is not on a selection or an existing link, and Remove link.
	 */
	let {
		open = $bindable(false),
		href = '',
		text = '',
		needsText = false,
		hasLink = false,
		onApply,
		onRemove
	}: {
		open?: boolean;
		href?: string;
		text?: string;
		/** The caret is collapsed outside a link: ask for the text too. */
		needsText?: boolean;
		hasLink?: boolean;
		onApply: (href: string, text: string) => void;
		onRemove: () => void;
	} = $props();

	let url = $state('');
	let linkText = $state('');
	let error = $state('');

	$effect(() => {
		if (open) {
			url = href;
			linkText = text;
			error = '';
		}
	});

	/** The validator's rule (`link.scheme`): an absolute https URL, at most 2 000 characters. */
	export function checkUrl(value: string): string {
		const v = value.trim();
		if (v === '') return 'Enter a web address.';
		if (!/^https:\/\/\S+$/i.test(v)) return 'The address must start with https://';
		if (v.length > 2000) return 'The address is too long (2 000 characters at most).';
		return '';
	}

	function apply() {
		error = checkUrl(url);
		if (!error && needsText && linkText.trim() === '') error = 'Enter the text of the link.';
		if (error) return;
		onApply(url.trim(), linkText.trim());
		open = false;
	}

	function remove() {
		onRemove();
		open = false;
	}
</script>

<Dialog bind:open title={hasLink ? 'Edit link' : 'Add link'} description="Links open in a new tab. Only https:// addresses are allowed." size="sm">
	<form
		class="link-form"
		onsubmit={(e) => {
			e.preventDefault();
			apply();
		}}
	>
		<Input label="Web address" bind:value={url} placeholder="https://example.org/information-sheet" {error} inputmode="url" autocomplete="off" spellcheck={false} />
		{#if needsText}
			<Input label="Link text" bind:value={linkText} />
		{/if}
		<div class="actions">
			<!-- type="button": inside the form these must not submit (submit = Add link). -->
			{#if hasLink}<Button type="button" variant="ghost" onclick={remove}>Remove link</Button>{/if}
			<span class="spacer"></span>
			<Button type="button" variant="ghost" onclick={() => (open = false)}>Cancel</Button>
			<Button variant="primary" type="submit">{hasLink ? 'Save' : 'Add link'}</Button>
		</div>
	</form>
</Dialog>

<style>
	.link-form {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin-block-start: var(--space-2);
	}
	.spacer {
		flex: 1;
	}
</style>
