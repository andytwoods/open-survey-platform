<script lang="ts" generics="T extends string">
	import type { Snippet } from 'svelte';

	/** A labelled group of native radios drawn as a segmented control (arrow keys move). */
	let {
		legend,
		name,
		options,
		value,
		onchange,
		description,
		option: optionSnippet
	}: {
		legend: string;
		name: string;
		options: readonly { value: T; label: string }[];
		value: T;
		onchange: (value: T) => void;
		description?: string;
		option?: Snippet<[{ value: T; label: string }]>;
	} = $props();

	const uid = $props.id();
</script>

<fieldset class="group" aria-describedby={description ? `${uid}-desc` : undefined}>
	<legend>{legend}</legend>
	{#if description}<p class="desc" id="{uid}-desc">{description}</p>{/if}
	<div class="options">
		{#each options as opt (opt.value)}
			<label class="opt">
				<input
					type="radio"
					name="{name}-{uid}"
					value={opt.value}
					checked={opt.value === value}
					onchange={() => onchange(opt.value)}
				/>
				<span>
					{#if optionSnippet}{@render optionSnippet(opt)}{:else}{opt.label}{/if}
				</span>
			</label>
		{/each}
	</div>
</fieldset>

<style>
	.group {
		margin: 0;
		padding: 0;
		border: 0;
		min-inline-size: 0;
	}
	legend {
		padding: 0;
		margin-block-end: var(--space-1);
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}
	.desc {
		margin: 0 0 var(--space-2);
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.options {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1);
	}
	.opt {
		position: relative;
		display: inline-flex;
	}
	.opt input {
		position: absolute;
		inset: 0;
		opacity: 0;
		margin: 0;
		cursor: pointer;
	}
	.opt span {
		display: inline-flex;
		align-items: center;
		min-block-size: 2.25rem;
		padding: 0 var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		font-size: var(--text-sm);
	}
	.opt:hover span {
		background: var(--color-surface-sunken);
	}
	.opt input:checked + span {
		border-color: var(--color-accent);
		background: var(--color-selected);
		box-shadow: inset 0 0 0 1px var(--color-accent);
		font-weight: var(--weight-medium);
	}
	.opt input:focus-visible + span {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 2px;
	}
</style>
