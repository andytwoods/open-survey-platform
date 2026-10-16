<script lang="ts">
	import { Button, Input, Select, announce } from '@osp/ui-components';
	import { LIST_ID, suggestListId, type ChoiceOp, type ChoiceQuestion, type SpecChoice, type SpecChoiceList } from './model';
	import { detachOps, makeSharedOps, useListOps } from './ops';

	/** Shared choice lists: which list the question uses, its usage, switch, share, detach. */
	let {
		question,
		choiceLists,
		usage,
		choices,
		onOps
	}: {
		question: ChoiceQuestion;
		choiceLists: readonly SpecChoiceList[];
		usage: Readonly<Record<string, readonly string[]>>;
		choices: readonly SpecChoice[];
		onOps: (ops: ChoiceOp[]) => void;
	} = $props();

	const used = (id: string) => usage[id]?.length ?? 0;
	const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`;
	const others = $derived(choiceLists.filter((l) => l.id !== question.choiceList));
	const options = $derived(
		others.map((l) => ({
			value: l.id,
			label: `${l.id} (${plural(l.choices.length, 'choice')}, used by ${used(l.id)})`
		}))
	);
	let pick = $state('');
	let sharing = $state(false);
	let newId = $state('');
	const taken = $derived(new Set(choiceLists.map((l) => l.id)));
	const idError = $derived(
		!sharing
			? undefined
			: !LIST_ID.test(newId) || newId.length > 64
				? 'Use letters, digits and _, starting with a letter or _.'
				: taken.has(newId)
					? `A list called ${newId} already exists.`
					: undefined
	);

	function send(ops: ChoiceOp[], message: string) {
		if (!ops.length) return;
		onOps(ops);
		announce(message);
	}

	function startSharing() {
		newId = suggestListId(question.id, taken);
		sharing = true;
	}
</script>

<div class="shared" role="group" aria-label="Shared list">
	{#if question.choiceList}
		{@const n = used(question.choiceList)}
		<p data-testid="shared-status">
			Shared list <code>{question.choiceList}</code>, used by
			<strong>{plural(n, 'question')}</strong>.
			{#if n > 1}Edits here change every question that uses it.{/if}
		</p>
		{#if !choiceLists.some((l) => l.id === question.choiceList)}
			<p class="warn">This list does not exist. Pick another list.</p>
		{/if}
		<Button
			size="sm"
			onclick={() =>
				send(detachOps(question, choices), `${question.id} now has its own copy of the choices`)}
			disabled={!choices.length}
		>
			Use a separate copy
		</Button>
	{:else}
		<p data-testid="shared-status">These choices belong to this question only.</p>
		{#if sharing}
			<form
				class="row"
				onsubmit={(e) => {
					e.preventDefault();
					if (idError) return;
					send(makeSharedOps(question, newId), `Shared as list ${newId}`);
					sharing = false;
				}}
			>
				<Input label="New list id" bind:value={newId} error={idError} autocomplete="off" spellcheck="false" />
				<Button size="sm" type="submit" variant="primary" disabled={!!idError}>Share</Button>
				<Button size="sm" variant="ghost" onclick={() => (sharing = false)}>Cancel</Button>
			</form>
		{:else}
			<Button size="sm" onclick={startSharing} disabled={!choices.length}>Make shared…</Button>
		{/if}
	{/if}

	{#if options.length}
		<div class="row">
			<Select
				label={question.choiceList ? 'Switch to another list' : 'Use a shared list'}
				{options}
				bind:value={pick}
				placeholder="Choose a list…"
			/>
			<Button
				size="sm"
				disabled={!pick}
				onclick={() => {
					send(useListOps(question, pick), `${question.id} now uses list ${pick}`);
					pick = '';
				}}
			>
				Use list
			</Button>
		</div>
		{#if !question.choiceList && pick}
			<p class="hint">This replaces the question's own choices with the list's.</p>
		{/if}
	{/if}
</div>

<style>
	.shared {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-2);
		padding: var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}
	p {
		margin: 0;
	}
	code {
		font-family: var(--font-mono, ui-monospace, monospace);
	}
	.row {
		display: flex;
		align-items: flex-end;
		gap: var(--space-2);
		flex-wrap: wrap;
	}
	.hint {
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.warn {
		color: var(--color-danger);
	}
</style>
