<script lang="ts">
	import { getContext, onDestroy, onMount, tick, untrack } from 'svelte';
	import type { HTMLInputAttributes } from 'svelte/elements';
	import { BUFFERS, type BufferRegistry } from './context';
	import { TEXT_DEBOUNCE_MS } from './logic';

	/**
	 * A text input (or textarea) over a local buffer (builder-design §4): typing never
	 * round-trips; the buffer is committed after a pause, on blur, on Enter (single line)
	 * or when the field goes away. Values arriving from the server never clobber text the
	 * user is still typing, and when they do replace the text the caret stays put (§7).
	 */
	let {
		id,
		value,
		multiline = false,
		placeholder = '',
		describedBy,
		required = false,
		invalid = false,
		readonly = false,
		inputmode,
		delay = TEXT_DEBOUNCE_MS,
		onCommit,
		onDirty
	}: {
		id: string;
		value: string;
		multiline?: boolean;
		placeholder?: string;
		describedBy?: string;
		required?: boolean;
		invalid?: boolean;
		readonly?: boolean;
		inputmode?: HTMLInputAttributes['inputmode'];
		delay?: number;
		onCommit: (text: string) => void;
		onDirty?: (dirty: boolean) => void;
	} = $props();

	let el = $state<HTMLInputElement | HTMLTextAreaElement | null>(null);
	let draft = $state(untrack(() => value));
	/** The last text we know the server holds (received, or sent by us). Not reactive. */
	let sent = untrack(() => value);
	let timer: ReturnType<typeof setTimeout> | null = null;

	const focused = () => !!el && el.ownerDocument.activeElement === el;

	$effect.pre(() => {
		const v = value;
		untrack(() => receive(v));
	});

	function receive(v: string) {
		if (v === draft) {
			sent = v;
			return;
		}
		// The user is mid-edit: their text wins until it is committed.
		if (timer !== null || (focused() && draft !== sent)) return;
		sent = v;
		if (el && focused()) {
			const { selectionStart: s, selectionEnd: e, selectionDirection: d } = el;
			draft = v;
			const input = el;
			void tick().then(() => {
				if (s === null || e === null) return;
				input.setSelectionRange(Math.min(s, v.length), Math.min(e, v.length), d ?? undefined);
			});
		} else {
			draft = v;
		}
	}

	function oninput() {
		if (timer === null) onDirty?.(true);
		else clearTimeout(timer);
		timer = setTimeout(flush, delay);
	}

	/** Commit the buffer now, if it holds unsent text. */
	export function flush() {
		if (timer !== null) {
			clearTimeout(timer);
			timer = null;
			onDirty?.(false);
		}
		if (draft === sent) return;
		sent = draft;
		onCommit(draft);
	}

	function onkeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !multiline) {
			e.preventDefault();
			flush();
		} else if (e.key === 'Escape' && draft !== sent) {
			// Throw away the unsent text and stop the Escape from closing anything else.
			e.stopPropagation();
			if (timer !== null) {
				clearTimeout(timer);
				timer = null;
				onDirty?.(false);
			}
			draft = sent;
		}
	}

	const registry = getContext<BufferRegistry | undefined>(BUFFERS);
	const handle = { flush };
	onMount(() => {
		registry?.add(handle);
	});
	onDestroy(() => {
		registry?.delete(handle);
		flush();
	});
</script>

{#if multiline}
	<textarea
		bind:this={el}
		bind:value={draft}
		{id}
		class="osp-prop-input"
		rows="3"
		{placeholder}
		{readonly}
		aria-describedby={describedBy}
		aria-required={required || undefined}
		aria-invalid={invalid || undefined}
		{oninput}
		onblur={flush}
		{onkeydown}
	></textarea>
{:else}
	<input
		bind:this={el}
		bind:value={draft}
		{id}
		type="text"
		class="osp-prop-input"
		{placeholder}
		{readonly}
		{inputmode}
		autocomplete="off"
		aria-describedby={describedBy}
		aria-required={required || undefined}
		aria-invalid={invalid || undefined}
		{oninput}
		onblur={flush}
		{onkeydown}
	/>
{/if}

<style>
	.osp-prop-input {
		width: 100%;
		box-sizing: border-box;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
	}
	input.osp-prop-input {
		height: var(--control-height);
		padding-block: 0;
	}
	textarea.osp-prop-input {
		resize: vertical;
		min-height: 4.5rem;
		line-height: 1.4;
	}
	.osp-prop-input[aria-invalid='true'] {
		border-color: var(--color-danger);
	}
	.osp-prop-input:focus-visible {
		outline: 2px solid var(--color-focus, var(--color-accent));
		outline-offset: 1px;
	}
</style>
