<script lang="ts">
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import CircleStop from '@lucide/svelte/icons/circle-stop';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import Gauge from '@lucide/svelte/icons/gauge';
	import GitBranch from '@lucide/svelte/icons/git-branch';
	import GripVertical from '@lucide/svelte/icons/grip-vertical';
	import Layers from '@lucide/svelte/icons/layers';
	import Shuffle from '@lucide/svelte/icons/shuffle';
	import Trash from '@lucide/svelte/icons/trash';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import Users from '@lucide/svelte/icons/users';
	import { Button, IconButton, Tooltip } from '@osp/ui-components';
	import type { Snippet } from 'svelte';
	import { withTranslation } from '../properties/logic';
	import { textFor } from '../cards/logic';
	import { endingOf } from '../settings/endings';
	import BufferedTextField from '../shell/BufferedTextField.svelte';
	import { flowCtx } from './context';
	import {
		armsOf,
		assignedVariables,
		blocks,
		conditionText,
		endMessage,
		flagFor,
		nodeLabel,
		quotas,
		redirectTemplateIds,
		setProp,
		TYPE_LABEL,
		type FlowNodeType,
		type Invocation,
		type Json
	} from './model';

	let {
		node,
		type,
		depth,
		children
	}: { node: Json; type: FlowNodeType; depth: number; children?: Snippet } = $props();

	const ctx = flowCtx();
	const uid = $props.id();
	const id = $derived(String(node.id));
	const label = $derived(nodeLabel(node, ctx.survey));
	const flags = $derived((ctx.diagnostics.get(id) ?? []).map(flagFor));
	const arms = $derived(armsOf(type));
	const collapsed = $derived(ctx.isCollapsed(id));
	const level = $derived(Math.min(6, 3 + depth));
	const ICONS = { block: Layers, branch: GitBranch, randomiser: Shuffle, assign: Users, quotaCheck: Gauge, externalTask: ExternalLink, end: CircleStop };
	const Icon = $derived(ICONS[type]);

	// EN1: every End node with this outcome shares the outcome's ending (Survey settings).
	const outcome = $derived(typeof node.outcome === 'string' ? node.outcome : 'complete');
	const ending = $derived(type === 'end' ? endingOf(ctx.survey, outcome) : null);
	const endingTitle = $derived(ending ? textFor(ending.title, ctx.language) : '');

	const send = (ops: Invocation[]) => ctx.store.submit(ops);
	const set = (property: string, value: unknown) => send([setProp(id, property, value)]);

	function onkeydown(e: KeyboardEvent) {
		if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
		if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
		const t = e.target as HTMLElement | null;
		if (t?.closest('article') !== e.currentTarget) return; // a nested card handles its own
		if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
		e.preventDefault();
		ctx.moveBy(id, e.key === 'ArrowUp' ? -1 : 1);
	}

	// Pointer drag on the handle: past a small threshold it becomes a drag; the gap under
	// the pointer (a `data-gap` element not inside the dragged node) is the drop target.
	let press: { x: number; y: number; pointer: number } | null = null;
	function onpointerdown(e: PointerEvent) {
		if (e.button !== 0) return;
		press = { x: e.clientX, y: e.clientY, pointer: e.pointerId };
		(e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
	}
	function onpointermove(e: PointerEvent) {
		if (!press || e.pointerId !== press.pointer) return;
		if (ctx.dragging !== id) {
			if (Math.hypot(e.clientX - press.x, e.clientY - press.y) < 4) return;
			ctx.dragStart(id);
		}
		const gap = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>('[data-gap]:not([data-blocked])');
		ctx.dragOver(gap?.dataset.gap ?? null);
	}
	function onpointerup(e: PointerEvent) {
		if (!press || e.pointerId !== press.pointer) return;
		press = null;
		if (ctx.dragging === id) ctx.drop();
	}
	function cancelDrag() {
		press = null;
		if (ctx.dragging === id) ctx.dragEnd();
	}

	// Field data
	const blockList = $derived(type === 'block' ? blocks(ctx.survey) : []);
	const children_n = $derived(Array.isArray(node.children) ? node.children.length : 0);
	const vars = $derived(type === 'assign' ? assignedVariables(ctx.survey) : []);
	const chosen = $derived(Array.isArray(node.variables) ? node.variables.map(String) : []);
	const quotaList = $derived(type === 'quotaCheck' ? quotas(ctx.survey) : []);
	const quota = $derived(quotaList.find((q) => q.id === node.quota));
	const templateList = $derived(type === 'externalTask' ? redirectTemplateIds(ctx.survey) : []);
	const returnsCount = $derived(Array.isArray(node.returns) ? node.returns.length : 0);

	function toggleVariable(v: string, on: boolean) {
		const next = on ? [...chosen, v] : chosen.filter((x) => x !== v);
		if (next.length) void set('variables', next);
	}
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions (Alt+arrow keys from the card's controls bubble here) -->
<article
	class="card"
	data-type={type}
	data-node-id={id}
	data-flag={flags[0]?.kind}
	class:dragging={ctx.dragging === id}
	aria-labelledby="{uid}-h"
	{onkeydown}
>
	<header>
		<button
			type="button"
			class="handle"
			data-flow-handle={id}
			aria-label="Move {label}"
			aria-describedby="flow-move-hint"
			aria-keyshortcuts="Alt+ArrowUp Alt+ArrowDown"
			{onpointerdown}
			{onpointermove}
			{onpointerup}
			onpointercancel={cancelDrag}
			onlostpointercapture={() => ctx.dragging === id && press && cancelDrag()}
			onkeydown={(e) => {
				if (e.key === 'Escape' && ctx.dragging === id) cancelDrag();
			}}
		>
			<GripVertical size={16} aria-hidden="true" />
		</button>
		{#if arms.length}
			<button
				type="button"
				class="toggle"
				aria-expanded={!collapsed}
				aria-controls="{uid}-arms"
				aria-label="{collapsed ? 'Expand' : 'Collapse'} {label}"
				onclick={() => ctx.toggle(id)}
			>
				{#if collapsed}<ChevronRight size={16} aria-hidden="true" />{:else}<ChevronDown size={16} aria-hidden="true" />{/if}
			</button>
		{/if}
		<span class="icon" aria-hidden="true"><Icon size={16} /></span>
		<svelte:element this={`h${level}`} id="{uid}-h" class="title">
			<span class="kind">{TYPE_LABEL[type]}:</span> <span class="summary"
				>{label.slice(label.indexOf(':') + 1).trim()}</span
			>
		</svelte:element>
		{#each flags as f (f.code + f.explanation)}
			<Tooltip text={f.explanation} side="top">
				{#snippet trigger(props)}
					<button type="button" {...props} class="flag" data-kind={f.kind} aria-label={f.explanation}>
						<TriangleAlert size={14} aria-hidden="true" />
						{f.label}
					</button>
				{/snippet}
			</Tooltip>
		{/each}
		<span class="spacer"></span>
		<IconButton icon={Trash} label="Delete {label}" tooltipSide="top" onclick={() => ctx.remove(id)} />
	</header>

	<div class="body">
		{#if type === 'block'}
			<div class="field">
				<label for="{uid}-f1">Block</label>
				<select id="{uid}-f1" value={String(node.block ?? '')} onchange={(e) => void set('block', e.currentTarget.value)}>
					{#each blockList as b (b.id)}
						<option value={b.id}>
							{b.label} ({b.questions} {b.questions === 1 ? 'question' : 'questions'}){b.placed && b.id !== node.block ? ', already in the flow' : ''}
						</option>
					{/each}
				</select>
			</div>
		{:else if type === 'branch'}
			<p class="condition">
				<span class="kw">If</span>
				<code>{conditionText(node) || '…'}</code>
			</p>
			<Button size="sm" onclick={() => ctx.openCondition(id)}>Edit condition…</Button>
		{:else if type === 'randomiser'}
			<div class="field">
				<label for="{uid}-f2">Show</label>
				<select id="{uid}-f2"
					value={typeof node.pick === 'number' ? String(node.pick) : ''}
					onchange={(e) => void set('pick', e.currentTarget.value ? Number(e.currentTarget.value) : undefined)}
				>
					<option value="">All {children_n}, in random order</option>
					{#each Array.from({ length: Math.max(children_n, typeof node.pick === 'number' ? node.pick : 0) }, (_, k) => k + 1) as k (k)}
						<option value={String(k)}>{k} of {children_n}, chosen at random</option>
					{/each}
				</select>
			</div>
		{:else if type === 'assign'}
			<fieldset class="field">
				<legend>Variables to assign</legend>
				{#each vars as v (v.id)}
					<label class="check">
						<input
							type="checkbox"
							checked={chosen.includes(v.id)}
							disabled={chosen.length === 1 && chosen[0] === v.id}
							onchange={(e) => toggleVariable(v.id, e.currentTarget.checked)}
						/>
						<span>{v.id}</span>
						<span class="muted">({v.levels.join(' / ')})</span>
					</label>
				{/each}
				{#each chosen.filter((c) => !vars.some((v) => v.id === c)) as missing (missing)}
					<span class="muted">{missing} (not an assigned variable)</span>
				{/each}
			</fieldset>
			<p class="muted hint">Each participant gets one level of each, recorded in their response.</p>
		{:else if type === 'quotaCheck'}
			<div class="field">
				<label for="{uid}-f3">Quota</label>
				<select id="{uid}-f3" value={String(node.quota ?? '')} onchange={(e) => void set('quota', e.currentTarget.value)}>
					{#each quotaList as q (q.id)}<option value={q.id}>{q.id}</option>{/each}
				</select>
			</div>
			{#if quota}
				<p class="muted hint">
					Limit {quota.limit ?? '?'} · counts when <code>{quota.when}</code> · when full: {quota.onFull}
				</p>
			{/if}
		{:else if type === 'externalTask'}
			<div class="field">
				<label for="{uid}-et">Task URL template</label>
				<select id="{uid}-et" value={String(node.template ?? '')} onchange={(e) => void set('template', e.currentTarget.value)}>
					{#each templateList as tmpl (tmpl)}<option value={tmpl}>{tmpl}</option>{/each}
				</select>
			</div>
			<p class="muted hint">
				Sends the participant to the task with a signed, expiring return token, then resumes here.
				{returnsCount} returned {returnsCount === 1 ? 'value' : 'values'} captured. Parameters sent and
				the captured variables are edited in the JSON view.
			</p>
		{:else if type === 'end'}
			<div class="row">
				<BufferedTextField
					label="Outcome"
					value={typeof node.outcome === 'string' ? node.outcome : 'complete'}
					store={ctx.store}
					commit={(t) => set('outcome', t.trim() && t.trim() !== 'complete' ? t.trim() : undefined)}
				/>
				<BufferedTextField
					label="Message"
					value={endMessage(node, ctx.language)}
					store={ctx.store}
					commit={(t) => set('message', withTranslation(node.message, ctx.language, ctx.language, t))}
				/>
			</div>
			<p class="muted hint ending" data-testid="ending-line">
				<span>
					Ending for outcome <code>{outcome}</code>:
					{#if ending}{endingTitle ? `“${endingTitle}”` : 'custom text'}{:else}the default screen{/if}.
					The message above is shown before it.
				</span>
				<Button size="sm" onclick={() => ctx.openEnding(outcome)}>Edit ending…</Button>
			</p>
		{/if}
	</div>

	{#if arms.length && !collapsed}
		<div class="arms" id="{uid}-arms">
			{@render children?.()}
		</div>
	{/if}
</article>

<style>
	.card {
		border: 1px solid var(--color-border);
		border-inline-start: 4px solid var(--type-colour, var(--color-border-strong));
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		box-shadow: var(--shadow-sm, none);
	}
	.card[data-type='branch'] {
		--type-colour: var(--color-accent);
	}
	.card[data-type='randomiser'] {
		--type-colour: var(--color-success);
	}
	.card[data-type='end'] {
		--type-colour: var(--color-danger);
	}
	.card[data-flag='unreachable'],
	.card[data-flag='empty'],
	.card[data-flag='warning'] {
		border-style: dashed;
		border-color: var(--color-warning);
		border-inline-start-style: solid;
	}
	.card[data-flag='error'] {
		border-color: var(--color-danger);
	}
	.card.dragging {
		opacity: 0.5;
	}
	header {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-2) 0;
		min-height: 2.25rem;
	}
	.handle,
	.toggle {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 1.75rem;
		height: 1.75rem;
		padding: 0;
		border: 1px solid transparent;
		border-radius: var(--radius-sm);
		background: transparent;
		color: var(--color-text-muted);
		cursor: grab;
		touch-action: none;
	}
	.toggle {
		cursor: pointer;
	}
	.handle:hover,
	.toggle:hover {
		background: var(--color-surface-sunken);
		color: var(--color-text);
	}
	.handle:focus-visible,
	.toggle:focus-visible,
	.flag:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}
	.icon {
		display: inline-flex;
		color: var(--type-colour, var(--color-text-muted));
	}
	.title {
		margin: 0;
		min-width: 0;
		font-size: var(--text-sm);
		font-weight: var(--weight-bold);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.kind {
		color: var(--color-text);
	}
	.summary {
		font-weight: normal;
		color: var(--color-text-muted);
	}
	.spacer {
		flex: 1;
	}
	.flag {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		padding: 0 var(--space-2);
		border: 1px solid var(--color-warning);
		border-radius: var(--radius-full);
		background: transparent;
		color: var(--color-warning);
		font-size: var(--text-xs);
		font-weight: var(--weight-bold);
		cursor: help;
		white-space: nowrap;
	}
	.flag[data-kind='error'] {
		border-color: var(--color-danger);
		color: var(--color-danger);
	}
	.body {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-3);
		padding: var(--space-2) var(--space-3) var(--space-3) calc(1.75rem + var(--space-4));
		font-size: var(--text-sm);
	}
	.field {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		border: 0;
	}
	fieldset.field {
		flex-wrap: wrap;
	}
	legend {
		float: left;
		margin-inline-end: var(--space-2);
		padding: 0;
		color: var(--color-text-muted);
	}
	.field > label {
		color: var(--color-text-muted);
	}
	select {
		min-height: 2rem;
		max-width: 100%;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-sm);
		background: var(--color-bg);
		color: var(--color-text);
		font: inherit;
	}
	select:focus-visible,
	input[type='checkbox']:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}
	.check {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		margin-inline-end: var(--space-3);
	}
	.condition {
		margin: 0;
		display: inline-flex;
		align-items: baseline;
		gap: var(--space-2);
	}
	.kw {
		font-weight: var(--weight-bold);
		color: var(--color-accent);
	}
	code {
		padding: 0 var(--space-1);
		border-radius: var(--radius-sm);
		background: var(--color-surface-sunken);
		font-family: var(--font-mono, ui-monospace, monospace);
		font-size: var(--text-sm);
	}
	.muted {
		color: var(--color-text-muted);
	}
	.ending {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
	}
	.hint {
		flex-basis: 100%;
		margin: 0;
		font-size: var(--text-xs);
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
		flex: 1;
	}
	.row > :global(*) {
		flex: 1 1 12rem;
	}
	.arms {
		padding: 0 var(--space-2) var(--space-2) var(--space-4);
	}
</style>
