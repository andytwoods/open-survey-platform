<script lang="ts">
	import { Announcer, Button, theme } from '@osp/ui-components';
	import {
		DateInput,
		DecimalInput,
		IntegerInput,
		Matrix,
		MultiChoice,
		Note,
		SingleChoice,
		Slider,
		TextInput,
		dirFor,
		type ChoiceStyle,
		type MatrixValue
	} from '@osp/ui-components/survey';
	import { onMount } from 'svelte';
	import { variantFrom, variants, type Variant } from './content';

	// Developer gallery of the participant widgets: every widget × state, in English, long
	// German and Arabic (?variant=de|ar). Checked by e2e/widgets.spec.ts at 320–1440 px.
	onMount(() => theme.init());

	const variant: Variant = $derived(variantFrom(new URLSearchParams(location.search).get('variant')));
	const c = $derived(variants[variant]);

	type State = 'empty' | 'answered' | 'error' | 'disabled';
	const states: State[] = ['empty', 'answered', 'error', 'disabled'];
	const styles: ChoiceStyle[] = ['cards', 'buttons'];

	const answered = {
		integer: '34',
		decimal: '72.5',
		single: 'pear',
		multi: ['bus', 'train'],
		date: '1990-03-27',
		matrix: { easy: '4', recommend: '5', again: '3' } as MatrixValue,
		slider: 3
	};

	// Live values, keyed by widget id, so every instance can be used.
	let values = $state<Record<string, unknown>>({});
	function initial(key: keyof typeof answered | 'text' | 'long', st: State): unknown {
		const has = st === 'answered' || st === 'disabled';
		if (key === 'text') return has ? c.text.answer : '';
		if (key === 'long') return has ? c.long.answer : '';
		if (key === 'multi') return has ? answered.multi : [];
		if (key === 'matrix') return has ? answered.matrix : {};
		return has ? answered[key] : null;
	}
	function val<T>(id: string, key: Parameters<typeof initial>[0], st: State): T {
		return (id in values ? values[id] : initial(key, st)) as T;
	}
	const set = (id: string) => (v: unknown) => (values[id] = v);
	const err = (st: State) => (st === 'error' ? c.required : undefined);
	const dis = (st: State) => st === 'disabled';

	let showFollowUp = $state(false);
</script>


<main class="gallery" lang={c.lang} dir={dirFor(c.lang)}>
	<h1>{c.title}</h1>
	<nav aria-label="Language variants" lang="en" dir="ltr">
		<a href="/dev/widgets?variant=en" aria-current={variant === 'en' ? 'page' : undefined}>English</a>
		<a href="/dev/widgets?variant=de" aria-current={variant === 'de' ? 'page' : undefined}>Deutsch (long labels)</a>
		<a href="/dev/widgets?variant=ar" aria-current={variant === 'ar' ? 'page' : undefined}>العربية (RTL)</a>
	</nav>

	{#key variant}
		<section aria-labelledby="h-integer">
			<h2 id="h-integer" lang="en">IntegerInput</h2>
			{#each states as st (st)}
				{@const id = `integer-${st}`}
				<div class="state" data-state={st}>
					<h3>{c.states[st]}</h3>
					<IntegerInput {id} {...c.integer} required lang={c.lang} messages={c.messages}
						value={val(id, 'integer', st)} error={err(st)} disabled={dis(st)} onchange={set(id)} />
				</div>
			{/each}
		</section>

		<section aria-labelledby="h-decimal">
			<h2 id="h-decimal" lang="en">DecimalInput</h2>
			{#each states as st (st)}
				{@const id = `decimal-${st}`}
				<div class="state" data-state={st}>
					<h3>{c.states[st]}</h3>
					<DecimalInput {id} {...c.decimal} lang={c.lang} messages={c.messages}
						value={val(id, 'decimal', st)} error={err(st)} disabled={dis(st)} onchange={set(id)} />
				</div>
			{/each}
		</section>

		<section aria-labelledby="h-text">
			<h2 id="h-text" lang="en">TextInput</h2>
			{#each states as st (st)}
				{@const id = `text-${st}`}
				<div class="state" data-state={st}>
					<h3>{c.states[st]}</h3>
					<TextInput {id} label={c.text.label} help={c.text.help} required lang={c.lang}
						messages={c.messages} value={val(id, 'text', st)} error={err(st)} disabled={dis(st)}
						onchange={set(id)} />
				</div>
			{/each}
			{#each states as st (st)}
				{@const id = `long-${st}`}
				<div class="state" data-state={st}>
					<h3>{c.states[st]} · multiline</h3>
					<TextInput {id} label={c.long.label} help={c.long.help} multiline lang={c.lang}
						messages={c.messages} value={val(id, 'long', st)} error={err(st)} disabled={dis(st)}
						onchange={set(id)} />
				</div>
			{/each}
		</section>

		<section aria-labelledby="h-single">
			<h2 id="h-single" lang="en">SingleChoice</h2>
			{#each states as st (st)}
				{@const id = `single-${st}`}
				<div class="state" data-state={st}>
					<h3>{c.states[st]}</h3>
					<SingleChoice {id} {...c.single} required lang={c.lang} messages={c.messages}
						value={val(id, 'single', st)} error={err(st)} disabled={dis(st)} onchange={set(id)} />
				</div>
			{/each}
			{#each styles as choiceStyle (choiceStyle)}
				{@const id = `single-${choiceStyle}`}
				<div class="state" data-state="answered">
					<h3>{c.states.answered} · {choiceStyle}</h3>
					<SingleChoice {id} {...c.single} {choiceStyle} lang={c.lang} messages={c.messages}
						value={val(id, 'single', 'answered')} onchange={set(id)} />
				</div>
			{/each}
		</section>

		<section aria-labelledby="h-multi">
			<h2 id="h-multi" lang="en">MultiChoice</h2>
			{#each states as st (st)}
				{@const id = `multi-${st}`}
				<div class="state" data-state={st}>
					<h3>{c.states[st]}</h3>
					<MultiChoice {id} {...c.multi} required lang={c.lang} messages={c.messages}
						value={val(id, 'multi', st)} error={err(st)} disabled={dis(st)} onchange={set(id)} />
				</div>
			{/each}
			{#each styles as choiceStyle (choiceStyle)}
				{@const id = `multi-${choiceStyle}`}
				<div class="state" data-state="answered">
					<h3>{c.states.answered} · {choiceStyle}</h3>
					<MultiChoice {id} {...c.multi} {choiceStyle} lang={c.lang} messages={c.messages}
						value={val(id, 'multi', 'answered')} onchange={set(id)} />
				</div>
			{/each}
		</section>

		<section aria-labelledby="h-date">
			<h2 id="h-date" lang="en">DateInput</h2>
			{#each states as st (st)}
				{@const id = `date-${st}`}
				<div class="state" data-state={st}>
					<h3>{c.states[st]}</h3>
					<DateInput {id} {...c.date} required lang={c.lang} messages={c.messages}
						value={val(id, 'date', st)} error={err(st)} disabled={dis(st)} onchange={set(id)} />
				</div>
			{/each}
		</section>

		<section aria-labelledby="h-note">
			<h2 id="h-note" lang="en">Note</h2>
			<div class="state" data-state="answered">
				<Note id="note" {...c.note} lang={c.lang} messages={c.messages} />
			</div>
		</section>

		<section aria-labelledby="h-matrix">
			<h2 id="h-matrix" lang="en">Matrix</h2>
			{#each states as st (st)}
				{@const id = `matrix-${st}`}
				<div class="state" data-state={st}>
					<h3>{c.states[st]}</h3>
					<Matrix {id} {...c.matrix} required lang={c.lang} messages={c.messages}
						value={val(id, 'matrix', st)} error={err(st)} disabled={dis(st)} onchange={set(id)} />
				</div>
			{/each}
		</section>

		<section aria-labelledby="h-slider">
			<h2 id="h-slider" lang="en">Slider</h2>
			{#each states as st (st)}
				{@const id = `slider-${st}`}
				<div class="state" data-state={st}>
					<h3>{c.states[st]}</h3>
					<Slider {id} {...c.slider} min={0} max={10} required lang={c.lang} messages={c.messages}
						value={val(id, 'slider', st)} error={err(st)} disabled={dis(st)} onchange={set(id)} />
				</div>
			{/each}
		</section>

		<section aria-labelledby="h-reveal">
			<h2 id="h-reveal" lang="en">Conditional reveal</h2>
			<div class="state">
				<Button onclick={() => (showFollowUp = !showFollowUp)} aria-expanded={showFollowUp}>
					{c.reveal.button}
				</Button>
				{#if showFollowUp}
					<TextInput id="follow-up" label={c.reveal.label} lang={c.lang} messages={c.messages}
						revealed value={val('follow-up', 'text', 'empty')} onchange={set('follow-up')} />
				{/if}
			</div>
		</section>
	{/key}
</main>

<Announcer />

<style>
	.gallery {
		max-inline-size: 42rem;
		margin-inline: auto;
		padding-block: var(--space-6);
		padding-inline: var(--space-4);
	}
	h1 {
		margin-block: 0 var(--space-3);
		font-size: var(--text-xl);
	}
	nav {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-4);
	}
	nav a {
		color: var(--color-accent);
	}
	nav a[aria-current='page'] {
		color: var(--color-text);
		font-weight: var(--weight-bold);
	}
	section {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		margin-block-start: var(--space-8);
	}
	h2 {
		margin: 0;
		padding-block-end: var(--space-2);
		border-block-end: 1px solid var(--color-border);
		font-size: var(--text-lg);
	}
	.state {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding: var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		background: var(--color-bg);
	}
	h3 {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}
</style>
