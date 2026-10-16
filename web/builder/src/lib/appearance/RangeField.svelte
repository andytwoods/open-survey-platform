<script lang="ts">
	/** A labelled native slider with its current value shown (and announced via aria-valuetext). */
	let {
		label,
		value,
		min,
		max,
		step = 1,
		unit = '',
		description,
		onchange
	}: {
		label: string;
		value: number;
		min: number;
		max: number;
		step?: number;
		unit?: string;
		description?: string;
		onchange: (value: number) => void;
	} = $props();

	const uid = $props.id();
	const text = $derived(`${value}${unit}`);
</script>

<div class="range">
	<div class="head">
		<label for="{uid}-r">{label}</label>
		<output for="{uid}-r">{text}</output>
	</div>
	<input
		id="{uid}-r"
		type="range"
		{min}
		{max}
		{step}
		{value}
		aria-valuetext={text}
		aria-describedby={description ? `${uid}-d` : undefined}
		oninput={(e) => onchange(Number(e.currentTarget.value))}
	/>
	{#if description}<p class="desc" id="{uid}-d">{description}</p>{/if}
</div>

<style>
	.range {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.head {
		display: flex;
		justify-content: space-between;
		font-size: var(--text-sm);
	}
	label {
		font-weight: var(--weight-medium);
	}
	output {
		color: var(--color-text-muted);
		font-variant-numeric: tabular-nums;
	}
	input {
		inline-size: 100%;
		min-block-size: 1.75rem;
		margin: 0;
		accent-color: var(--color-accent);
	}
	input:focus-visible {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 2px;
	}
	.desc {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
</style>
