<script lang="ts">
	import { filterTypes, type QuestionTypeId, type QuestionTypeInfo } from './catalogue';

	/**
	 * Pick a question type: a filter box (a combobox) over a listbox of the types, each with
	 * its icon, name and one-line description. Arrow keys move, Home/End jump, Enter picks,
	 * typing filters; a click picks too. Escape belongs to the surrounding dialog.
	 */
	let {
		types,
		current,
		lastUsed,
		label = 'Question types',
		onchoose
	}: {
		/** In display order (the last used type first, when there is one). */
		types: readonly QuestionTypeInfo[];
		/** The question's type now (changing a type): marked, and not highlighted first. */
		current?: QuestionTypeId;
		/** Marked "Last used". */
		lastUsed?: QuestionTypeId | null;
		label?: string;
		onchoose: (id: QuestionTypeId) => void;
	} = $props();

	const uid = $props.id();
	const listId = `osp-type-list-${uid}`;
	const optionId = (id: string) => `osp-type-${uid}-${id}`;

	let query = $state('');
	const shown = $derived(filterTypes(types, query));
	const firstChoice = $derived(Math.max(0, shown.findIndex((t) => t.id !== current)));
	let picked = $state<number | null>(null);
	const active = $derived(picked !== null && picked < shown.length ? picked : firstChoice);
	const activeType = $derived(shown[active]);

	let list = $state<HTMLElement | null>(null);
	$effect(() => {
		const id = activeType?.id;
		if (!id || !list) return;
		list.querySelector(`#${CSS.escape(optionId(id))}`)?.scrollIntoView?.({ block: 'nearest' });
	});

	function move(to: number) {
		const n = shown.length;
		if (!n) return;
		picked = ((to % n) + n) % n;
	}

	function onkeydown(e: KeyboardEvent) {
		if (e.key === 'ArrowDown') move(active + 1);
		else if (e.key === 'ArrowUp') move(active - 1);
		else if (e.key === 'Home' && !e.shiftKey) move(0);
		else if (e.key === 'End' && !e.shiftKey) move(shown.length - 1);
		else if (e.key === 'Enter') {
			if (activeType) onchoose(activeType.id);
		} else return;
		e.preventDefault();
	}
</script>

<div class="type-picker">
	<label class="osp-visually-hidden" for="{listId}-filter">Filter question types</label>
	<input
		id="{listId}-filter"
		class="filter"
		type="text"
		role="combobox"
		autocomplete="off"
		spellcheck="false"
		placeholder="Filter types…"
		aria-expanded="true"
		aria-controls={listId}
		aria-autocomplete="list"
		aria-activedescendant={activeType ? optionId(activeType.id) : undefined}
		bind:value={query}
		oninput={() => (picked = null)}
		{onkeydown}
	/>
	<ul class="options" id={listId} role="listbox" aria-label={label} bind:this={list}>
		{#each shown as t, i (t.id)}
			{@const Icon = t.icon}
			<!-- The keyboard drives the options through the filter box (aria-activedescendant). -->
			<!-- svelte-ignore a11y_click_events_have_key_events -->
			<li
				id={optionId(t.id)}
				class="option"
				role="option"
				aria-selected={i === active}
				data-type={t.id}
				data-current={t.id === current ? '' : undefined}
				onclick={() => onchoose(t.id)}
				onpointermove={() => (picked = i)}
			>
				<span class="icon" aria-hidden="true"><Icon size={20} /></span>
				<span class="text">
					<span class="name">
						{t.name}
						{#if t.id === current}<span class="tag">Current</span>{/if}
						{#if t.id === lastUsed && t.id !== current}<span class="tag">Last used</span>{/if}
					</span>
					<span class="desc">{t.description}</span>
				</span>
			</li>
		{/each}
	</ul>
	<p class="empty" role="status">
		{#if !shown.length}No question type matches “{query}”.{/if}
	</p>
</div>

<style>
	.type-picker {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.filter {
		min-height: 2.75rem;
		padding: 0 var(--space-3);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: var(--color-text);
		font: inherit;
		font-size: max(1rem, 16px); /* no zoom on focus on iOS */
	}
	.options {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.option {
		display: flex;
		align-items: flex-start;
		gap: var(--space-3);
		min-height: 2.75rem;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-md);
		cursor: pointer;
	}
	.option[aria-selected='true'] {
		background: var(--color-selected);
		box-shadow: inset 3px 0 0 var(--color-accent);
	}
	.icon {
		display: inline-grid;
		place-items: center;
		flex: none;
		width: 2rem;
		height: 2rem;
		border-radius: var(--radius-sm);
		background: var(--color-surface-sunken);
		color: var(--color-text);
	}
	.text {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.name {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
		font-weight: var(--weight-medium);
	}
	.desc {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.tag {
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-full);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-normal, 400);
	}
	.empty {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.empty:empty {
		display: none;
	}
</style>
