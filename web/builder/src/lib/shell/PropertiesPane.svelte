<script lang="ts">
	import { Tabs } from '@osp/ui-components';
	import {
		defaultLanguage,
		findObject,
		pointerOf,
		pointerWithin,
		textIn,
		withText,
		type OutlineNode
	} from '../model/outline';
	import { findNode } from '../outline/tree-nav';
	import type { SelectionStore } from '../selection.svelte';
	import type { SurveyStore } from '../sync/survey-store.svelte';
	import BufferedTextField from './BufferedTextField.svelte';

	/**
	 * Shows what is selected, plus the one editable field each object has here (question
	 * label, page/block title) so the edit flow is wired end to end. The schema-driven
	 * property panel is task B4.
	 */
	let {
		roots,
		selection,
		store = null
	}: { roots: OutlineNode[]; selection: SelectionStore; store?: SurveyStore | null } = $props();

	const node = $derived(selection.id ? findNode(roots, selection.id) : undefined);
	const raw = $derived(store && node ? findObject(store.survey, node.id) : undefined);
	const lang = $derived(store ? defaultLanguage(store.survey) : 'en');
	let tab = $state('details');

	const field = $derived.by(() => {
		if (!store || !node || !raw) return undefined;
		if (node.type === 'question') return { label: 'Question text', property: 'label' };
		if (node.type === 'page') return { label: 'Page title', property: 'title' };
		if (node.type === 'block') return { label: 'Block name', property: 'title' };
		return undefined;
	});

	// Block titles are plain strings (builder-only); page titles and labels are translatable.
	const fieldValue = $derived(
		field && raw ? (node?.type === 'block' ? String(raw.title ?? '') : textIn(raw[field.property], lang)) : ''
	);

	/**
	 * The commit for one object, bound when its field is rendered: a buffer flushed after
	 * the selection moved on must still edit the object it was typed into.
	 */
	function commitFor(id: string, type: OutlineNode['type'], property: string) {
		return (text: string) => {
			if (!store) return;
			const unset = { op: 'set_property', params: { target: id, property, unset: true } };
			const blank = !text.trim();
			if (type === 'block') {
				return store.submit([blank ? unset : { op: 'set_property', params: { target: id, property, value: text } }]);
			}
			if (type === 'page' && blank) return store.submit([unset]);
			const current = findObject(store.survey, id)?.[property];
			const value = withText(current, defaultLanguage(store.survey), text);
			return store.submit([{ op: 'set_property', params: { target: id, property, value } }]);
		};
	}

	const nodeDiagnostics = $derived.by(() => {
		if (!store || !node) return [];
		const base = pointerOf(store.survey, node.id);
		if (!base) return [];
		const all = [...store.diagnostics, ...(store.rejection?.diagnostics ?? [])];
		return all.filter((d) => pointerWithin(d.pointer, base));
	});
</script>

<div class="properties">
	<h2 id="properties-heading" tabindex="-1" data-pane-focus>Properties</h2>
	{#if node}
		{#snippet details()}
			{#if field && store}
				{#key node.id}
					<div class="field">
						<BufferedTextField
							label={field.label}
							value={fieldValue}
							{store}
							commit={commitFor(node.id, node.type, field.property)}
						/>
					</div>
				{/key}
			{/if}
			<dl data-testid="selected-details">
				<dt>Id</dt>
				<dd><code>{node.id}</code></dd>
				<dt>Type</dt>
				<dd>{node.type}{node.questionType ? ` (${node.questionType})` : ''}</dd>
				{#if node.family}
					<dt>Family</dt>
					<dd>{node.family}</dd>
				{/if}
				<dt>Label</dt>
				<dd>{node.label}</dd>
			</dl>
		{/snippet}
		{#snippet diagnostics()}
			{#if !store}
				<p class="muted">No diagnostics. Validation is not connected yet.</p>
			{:else if nodeDiagnostics.length === 0}
				<p class="muted">No diagnostics for this item.</p>
			{:else}
				<ul class="diagnostics">
					{#each nodeDiagnostics as d, i (i)}
						<li data-severity={d.severity}>
							<strong>{d.severity}</strong>
							{d.message}
							<code>{d.code}</code>
						</li>
					{/each}
				</ul>
			{/if}
		{/snippet}
		<Tabs
			label="Property sections"
			bind:value={tab}
			tabs={[
				{ value: 'details', label: 'Details', content: details },
				{
					value: 'diagnostics',
					label: nodeDiagnostics.length ? `Diagnostics (${nodeDiagnostics.length})` : 'Diagnostics',
					content: diagnostics
				}
			]}
		/>
	{:else}
		<p class="muted">Select an item in the outline or on the canvas to see its properties.</p>
	{/if}
</div>

<style>
	.properties {
		padding: var(--space-3) var(--space-4);
	}
	h2 {
		margin: 0 0 var(--space-3);
		font-size: var(--text-sm);
		font-weight: var(--weight-bold);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-muted);
	}
	.field {
		margin-bottom: var(--space-4);
	}
	dl {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: var(--space-2) var(--space-4);
		margin: 0;
		font-size: var(--text-sm);
	}
	dt {
		color: var(--color-text-muted);
	}
	dd {
		margin: 0;
		overflow-wrap: anywhere;
	}
	code {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		padding: 0.1rem 0.3rem;
		border-radius: var(--radius-sm);
		background: var(--color-surface-sunken);
	}
	.muted {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.diagnostics {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		list-style: none;
		font-size: var(--text-sm);
	}
	.diagnostics strong {
		text-transform: capitalize;
	}
	[data-severity='error'] strong {
		color: var(--color-danger);
	}
	[data-severity='warning'] strong {
		color: var(--color-warning);
	}
</style>
