<script lang="ts">
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import { setContext, tick } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { BUFFERS, type BufferRegistry } from './context';
	import { diagnosticsFor, fieldId, getAt, groupProperties, localised, opAddress } from './logic';
	import PropertyField from './PropertyField.svelte';
	import type { OpenEditorRequest, PanelDiagnostic, SetPropertyOp, TypeSchema } from './types';

	/**
	 * The property panel (builder-design §2): renders any type's property schema as a form,
	 * grouped and collapsible, one field editor per `kind`. No per-type code. Every edit is
	 * handed to `onOp` as a `set_property` op; the panel never changes `target` itself.
	 */
	let {
		schema,
		target,
		language,
		defaultLanguage,
		diagnostics = [],
		pointer = '',
		survey,
		groups = ['Basics', 'Choices', 'Logic', 'Validation', 'Advanced'],
		onOp,
		onOpenEditor,
		onDirty
	}: {
		/** One entry of `GET /api/meta/property-schemas` → `schemas`. */
		schema: TypeSchema;
		/** The question, page or block object, or (entity `survey`) the survey document. */
		target: unknown;
		/** The language translatable fields are edited in. */
		language: string;
		/** The survey's default language (plain-string texts belong to it). Default: `language`. */
		defaultLanguage?: string;
		/** Survey diagnostics; those under `pointer` + a property's path show at that field. */
		diagnostics?: PanelDiagnostic[];
		/** RFC 6901 pointer of `target` in the survey document ("" for the survey). */
		pointer?: string;
		/** The survey document, for `optionsFrom`. Default: `target` when it is the survey. */
		survey?: unknown;
		/** Group order (the schema document's `groups`). */
		groups?: readonly string[];
		onOp: (op: SetPropertyOp) => void;
		onOpenEditor?: (request: OpenEditorRequest) => void;
		/** A text buffer started (true) or stopped (false) holding unsent text. */
		onDirty?: (dirty: boolean) => void;
	} = $props();

	const uid = $props.id();
	const prefix = `osp-prop-${uid}`;

	const grouped = $derived(groupProperties(schema, groups));
	const surveyDoc = $derived(survey ?? (schema.entity === 'survey' ? target : undefined));
	const defaultLang = $derived(defaultLanguage ?? language);
	const targetKey = $derived.by(() => {
		const id = (target as { id?: unknown } | null)?.id;
		return `${schema.type}|${schema.entity === 'survey' ? '' : typeof id === 'string' ? id : ''}|${language}`;
	});

	const collapsed = new SvelteSet<string>();
	const toggle = (name: string) => (collapsed.has(name) ? collapsed.delete(name) : collapsed.add(name));

	const buffers: BufferRegistry = new Set();
	setContext(BUFFERS, buffers);

	/** Commit every text buffer holding unsent text now (before undo, save, navigation). */
	export function flush() {
		for (const b of [...buffers]) b.flush();
	}

	/**
	 * Move focus to a property's field (e.g. from a diagnostic elsewhere), expanding its
	 * group. Returns false when the schema has no such property.
	 */
	export async function focusProperty(path: string): Promise<boolean> {
		const group = grouped.find((g) => g.entries.some((e) => e.key === path));
		if (!group) return false;
		collapsed.delete(group.name);
		await tick();
		const el = document.getElementById(fieldId(prefix, path));
		if (!el) return false;
		el.focus();
		el.scrollIntoView?.({ block: 'nearest' });
		return true;
	}
</script>

<div class="osp-property-panel" data-type={schema.type} data-entity={schema.entity}>
	<p class="type-label">{localised(schema.label, language) || schema.type}</p>
	{#key targetKey}
		{#each grouped as group (group.name)}
			{@const open = !collapsed.has(group.name)}
			{@const gid = `${prefix}-group-${group.name.replace(/\W/g, '-')}`}
			<section class="group" aria-labelledby="{gid}-h" data-group={group.name}>
				<h3 class="group-h" id="{gid}-h">
					<button
						type="button"
						class="group-toggle"
						aria-expanded={open}
						aria-controls="{gid}-body"
						onclick={() => toggle(group.name)}
					>
						<span class="chev" class:open aria-hidden="true"><ChevronRight size={14} /></span>
						{group.name}
					</button>
				</h3>
				<div class="group-body" id="{gid}-body" hidden={!open}>
					{#each group.entries as entry (entry.key)}
						<PropertyField
							id={fieldId(prefix, entry.key)}
							propertyKey={entry.key}
							spec={entry.spec}
							raw={getAt(target, entry.key)}
							address={opAddress(schema.entity, target, entry.key)}
							{language}
							defaultLanguage={defaultLang}
							survey={surveyDoc}
							diagnostics={diagnosticsFor(diagnostics, pointer, entry.key)}
							{onOp}
							{onOpenEditor}
							{onDirty}
						/>
					{/each}
				</div>
			</section>
		{/each}
	{/key}
</div>

<style>
	.osp-property-panel {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.type-label {
		margin: 0;
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}
	.group {
		border-top: 1px solid var(--color-border);
		padding-top: var(--space-2);
	}
	.group-h {
		margin: 0;
		font-size: var(--text-sm);
		font-weight: var(--weight-bold);
	}
	.group-toggle {
		display: flex;
		align-items: center;
		gap: var(--space-1);
		width: 100%;
		padding: var(--space-1) 0;
		border: 0;
		background: none;
		color: var(--color-text);
		font: inherit;
		text-align: left;
		cursor: pointer;
	}
	.group-toggle:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}
	.chev {
		display: inline-flex;
		transition: transform 120ms;
	}
	.chev.open {
		transform: rotate(90deg);
	}
	.group-body {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		padding: var(--space-2) 0 var(--space-3);
	}
	.group-body[hidden] {
		display: none;
	}
</style>
