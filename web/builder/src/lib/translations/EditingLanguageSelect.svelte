<script lang="ts">
	import { announce } from '@osp/ui-components';
	import { defaultLanguage } from '../model/outline';
	import { languagesOf } from '../settings/model';
	import { languageOptions } from './editing-language';
	import { editLanguageOf, setEditingLanguage } from './editing-language.svelte';

	/**
	 * The "Editing language" select (planning/rich-text.md §5): the survey's languages, default
	 * first, bound to the shared editing language. Rendered only when the survey has more than
	 * one language (with one there is nothing to choose).
	 */
	let { survey, id }: { survey: unknown; id?: string } = $props();

	const uid = $props.id();
	const selectId = $derived(id ?? `osp-edit-lang-${uid}`);
	const languages = $derived(languagesOf(survey));
	const def = $derived(defaultLanguage(survey));
	const value = $derived(editLanguageOf(survey));
	const options = $derived(languageOptions(languages, def));

	function choose(lang: string) {
		setEditingLanguage(lang, def);
		announce(lang === def ? `Editing ${lang}, the default language` : `Editing ${lang}`);
	}
</script>

{#if languages.length > 1}
	<div class="edit-lang" data-testid="editing-language">
		<label for={selectId}>Editing language</label>
		<select id={selectId} {value} onchange={(e) => choose(e.currentTarget.value)}>
			{#each options as o (o.value)}<option value={o.value}>{o.label}</option>{/each}
		</select>
	</div>
{/if}

<style>
	.edit-lang {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		font-size: var(--text-sm);
	}
	label {
		font-weight: var(--weight-medium);
	}
	select {
		min-height: var(--control-height, 2.25rem);
		max-width: 16rem;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
	}
	select:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}
</style>
