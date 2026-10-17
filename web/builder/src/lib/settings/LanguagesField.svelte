<script lang="ts">
	import X from '@lucide/svelte/icons/x';
	import { Button } from '@osp/ui-components';
	import type { Outcome } from '../sync/survey-store.svelte';
	import type { Invocation } from '../sync/transport';
	import { explicitDefaultOf, languagesOf, languagesOp } from './model';

	/**
	 * Survey languages (metadata.languages + defaultLanguage) through `set_languages`.
	 * Removing a language that still has translations is refused by the server; the
	 * researcher can then confirm deleting those translations (`cascade`).
	 */
	let { survey, submit }: { survey: unknown; submit: (ops: Invocation[]) => Promise<Outcome> } = $props();

	const languages = $derived(languagesOf(survey));
	const explicitDefault = $derived(explicitDefaultOf(survey));
	const shownDefault = $derived(explicitDefault ?? languages[0] ?? '');
	let newTag = $state('');
	let problem = $state<string | null>(null);
	let pendingRemoval = $state<string | null>(null);

	async function send(next: string[], def: string | null, cascade = false) {
		problem = null;
		const out = await submit([languagesOp(next, def, cascade)]);
		if (out.status === 'rejected') {
			const d = out.diagnostics[0];
			if (d?.code === 'op.dangling_ref' && !cascade) {
				pendingRemoval = languages.find((l) => !next.includes(l)) ?? null;
				problem = d.message;
			} else problem = d?.message ?? out.message;
			return false;
		}
		pendingRemoval = null;
		return out.status === 'applied';
	}

	async function add() {
		const tag = newTag.trim();
		if (!tag) return;
		if (languages.includes(tag)) {
			problem = `${tag} is already a survey language.`;
			return;
		}
		if (await send([...languages, tag], explicitDefault)) newTag = '';
	}

	function remove(tag: string) {
		const next = languages.filter((l) => l !== tag);
		void send(next, explicitDefault === tag ? null : explicitDefault);
	}
</script>

<div class="languages">
	<ul class="tags" aria-label="Survey languages">
		{#each languages as l (l)}
			<li>
				<span lang={l}>{l}</span>
				{#if l === shownDefault}<span class="badge">default</span>{/if}
				{#if languages.length > 1}
					<button type="button" class="remove" aria-label="Remove language {l}" onclick={() => remove(l)}>
						<X size={14} aria-hidden="true" />
					</button>
				{/if}
			</li>
		{/each}
	</ul>
	<div class="row">
		<label class="field">
			<span>Add a language (tag, e.g. de or pt-BR)</span>
			<input
				type="text"
				autocomplete="off"
				spellcheck="false"
				bind:value={newTag}
				onkeydown={(e) => e.key === 'Enter' && void add()}
			/>
		</label>
		<Button size="sm" onclick={() => void add()} disabled={!newTag.trim()}>Add language</Button>
	</div>
	<label class="field">
		<span>Default language</span>
		<select
			value={shownDefault}
			onchange={(e) => void send(languages, e.currentTarget.value)}
		>
			{#each languages as l (l)}<option value={l}>{l}</option>{/each}
		</select>
	</label>
	{#if problem}
		<div class="problem" role="alert">
			<p>{problem}</p>
			{#if pendingRemoval}
				<Button
					size="sm"
					onclick={() =>
						void send(
							languages.filter((l) => l !== pendingRemoval),
							explicitDefault === pendingRemoval ? null : explicitDefault,
							true
						)}>Remove {pendingRemoval} and delete its translations</Button
				>
			{/if}
		</div>
	{/if}
</div>

<style>
	.languages {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.tags {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.tags li {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-full);
		font-size: var(--text-sm);
	}
	.badge {
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.remove {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-inline-size: 1.5rem;
		min-block-size: 1.5rem;
		padding: 0;
		border: 0;
		border-radius: var(--radius-full);
		background: none;
		color: var(--color-text-muted);
		cursor: pointer;
	}
	.remove:focus-visible {
		outline: 2px solid var(--color-focus);
	}
	.row {
		display: flex;
		align-items: flex-end;
		gap: var(--space-2);
		flex-wrap: wrap;
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		font-size: var(--text-sm);
	}
	.field input,
	.field select {
		min-block-size: 2.25rem;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		max-width: 16rem;
	}
	.problem {
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-danger);
		border-inline-start-width: 4px;
		border-radius: var(--radius-md);
		font-size: var(--text-sm);
	}
	.problem p {
		margin: 0 0 var(--space-2);
	}
</style>
