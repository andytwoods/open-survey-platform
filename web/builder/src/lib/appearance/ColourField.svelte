<script lang="ts">
	import { Button } from '@osp/ui-components';
	import type { ThemeDiagnostic } from './guard';

	/**
	 * One theme colour: a native colour picker plus a hex text field, and the guard's
	 * failing pairs for it with the nearest passing colour and a one-click fix.
	 */
	let {
		id,
		label,
		value,
		problems = [],
		onchange,
		onfix
	}: {
		/** Element id of the colour picker (the banner links here). */
		id: string;
		label: string;
		value: string;
		problems?: ThemeDiagnostic[];
		onchange: (hex: string) => void;
		onfix: (d: ThemeDiagnostic) => void;
	} = $props();

	const HEX = /^#[0-9a-fA-F]{6}$/;
	// The text field may hold a half-typed value; it resyncs when the colour changes elsewhere.
	let text = $state('');
	let editing = $state(false);
	$effect(() => {
		if (!editing) text = value;
	});
	const textInvalid = $derived(editing && !HEX.test(normalise(text)));
	const suggestion = $derived(
		problems.find((p) => typeof p.suggestion === 'string')?.suggestion as string | undefined
	);

	function normalise(s: string) {
		const t = s.trim();
		return t.startsWith('#') ? t : `#${t}`;
	}

	const BACKDROP_NAMES: Record<string, string> = {
		bg: 'the page',
		surface: 'a card',
		'surface-raised': 'an input',
		'surface-sunken': 'a hovered choice',
		'accent-subtle': 'a hovered outline button',
		selected: 'a selected choice',
		'accent-hover': 'a hovered button'
	};

	/** "body text on the page: 2.40:1, needs 4.5:1" from the guard's message. */
	function describe(d: ThemeDiagnostic): string {
		const m = /^\w+: (.+?) \((\S+) \S+ on (\S+) \S+\) has contrast ([\d.]+):1; WCAG AA needs ([\d.]+):1\.$/.exec(
			d.message
		);
		if (!m) return d.message;
		const [, what, , bg, ratio, need] = m;
		return `${what} on ${BACKDROP_NAMES[bg] ?? bg}: ${ratio}:1, needs ${+need}:1`;
	}
</script>

<div class="colour" class:failing={problems.length > 0}>
	<div class="row">
		<input
			{id}
			class="swatch"
			type="color"
			{value}
			aria-describedby={problems.length ? `${id}-problems` : undefined}
			oninput={(e) => onchange(e.currentTarget.value)}
		/>
		<label for={id} class="name">{label}</label>
		<input
			class="hex"
			type="text"
			aria-label="{label}, hex value"
			aria-invalid={textInvalid ? 'true' : undefined}
			spellcheck="false"
			autocomplete="off"
			maxlength="7"
			bind:value={text}
			onfocus={() => (editing = true)}
			onblur={() => {
				editing = false;
				text = value;
			}}
			oninput={() => {
				const hex = normalise(text);
				if (HEX.test(hex)) onchange(hex.toLowerCase());
			}}
			onkeydown={(e) => {
				if (e.key === 'Enter') e.currentTarget.blur();
			}}
		/>
	</div>
	{#if problems.length}
		<div class="problems" id="{id}-problems" data-testid="contrast-problems">
			<p class="title">Low contrast in {problems.length} {problems.length === 1 ? 'place' : 'places'}</p>
			<ul>
				{#each problems as d (d.message)}
					<li>{describe(d)}</li>
				{/each}
			</ul>
			{#if suggestion}
				<div class="fix">
					<span class="chip" style:background={suggestion} aria-hidden="true"></span>
					<span id="{id}-suggestion">Nearest passing colour: <code>{suggestion}</code></span>
					<Button
						size="sm"
						variant="secondary"
						aria-describedby="{id}-suggestion"
						onclick={() => onfix(problems[0])}>Use suggestion</Button
					>
				</div>
			{:else}
				<p class="nofix">No nearby colour passes; try a different hue or change the background.</p>
			{/if}
		</div>
	{/if}
</div>

<style>
	.colour {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.row {
		display: grid;
		grid-template-columns: auto 1fr 6.5rem;
		align-items: center;
		gap: var(--space-2);
	}
	.swatch {
		inline-size: 2.5rem;
		block-size: 2.25rem;
		padding: 2px;
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		cursor: pointer;
	}
	.name {
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}
	.hex {
		min-block-size: 2.25rem;
		inline-size: 100%;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font-family: var(--font-mono);
		font-size: var(--text-sm);
	}
	.hex[aria-invalid='true'] {
		border-color: var(--color-danger);
	}
	.swatch:focus-visible,
	.hex:focus-visible {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 2px;
	}
	.problems {
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-danger);
		border-inline-start-width: 4px;
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		font-size: var(--text-xs);
	}
	.title {
		margin: 0;
		font-weight: var(--weight-bold);
		color: var(--color-danger);
	}
	ul {
		margin: var(--space-1) 0 var(--space-2);
		padding-inline-start: var(--space-4);
	}
	.fix {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
	}
	.chip {
		inline-size: 1.25rem;
		block-size: 1.25rem;
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-sm);
	}
	code {
		font-family: var(--font-mono);
	}
	.nofix {
		margin: 0;
	}
</style>
