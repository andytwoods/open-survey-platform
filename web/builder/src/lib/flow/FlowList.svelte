<script lang="ts">
	import Plus from '@lucide/svelte/icons/plus';
	import { flowCtx } from './context';
	import { ARM_LABEL, armsOf, isNodeType, walk, inSubtree, type ArmName, type FlowNodeType, type Json } from './model';
	import NodeCard from './NodeCard.svelte';

	/**
	 * The flow as nested node lists (the top level and each branch/randomiser arm), with
	 * "+" gaps that are also drop targets. Recursion is a snippet, not a self-import.
	 */
	let { nodes, label }: { nodes: unknown[]; label: string } = $props();

	const ctx = flowCtx();
	const rows = $derived(walk(ctx.survey));
	const nodesOf = (v: unknown): Json[] =>
		Array.isArray(v)
			? v.filter((n): n is Json => typeof n === 'object' && n !== null && isNodeType((n as Json).type))
			: [];
	// While dragging, gaps inside the dragged node are not valid drop targets.
	const isBlocked = (parent: string | null) =>
		ctx.dragging !== null && parent !== null && inSubtree(rows, parent, ctx.dragging);
	const key = (parent: string | null, arm: ArmName | null, index: number) => `${parent ?? 'flow'}:${arm ?? ''}:${index}`;
</script>

{#snippet gap(parent: string | null, arm: ArmName | null, index: number, listLabel: string)}
	{@const blocked = isBlocked(parent)}
	<div
		class="gap"
		class:dropzone={ctx.dragging !== null && !blocked}
		class:over={ctx.overGap === key(parent, arm, index)}
		data-gap={key(parent, arm, index)}
		data-blocked={blocked || undefined}
	>
		<button
			type="button"
			class="add"
			aria-label="Add node to {listLabel} at position {index + 1}"
			title="Add a node here"
			onclick={() => ctx.openAdd({ parent, arm, index })}
		>
			<Plus size={14} aria-hidden="true" />
		</button>
	</div>
{/snippet}

{#snippet list(items: Json[], parent: string | null, arm: ArmName | null, depth: number, listLabel: string)}
	<div class="flow-list" data-depth={depth}>
		{#if items.length}
			<ol aria-label={listLabel}>
				{#each items as node, i (node.id ?? i)}
					{@const type = node.type as FlowNodeType}
					<li>
						{@render gap(parent, arm, i, listLabel)}
						<NodeCard {node} {type} {depth}>
							{#each armsOf(type) as a (a)}
								<section class="arm" aria-label="{ARM_LABEL[a]} of {String(node.id)}">
									<p class="arm-label" aria-hidden="true">{ARM_LABEL[a]}</p>
									{@render list(nodesOf(node[a]), String(node.id), a, depth + 1, `${ARM_LABEL[a]} of ${String(node.id)}`)}
								</section>
							{/each}
						</NodeCard>
					</li>
				{/each}
			</ol>
		{:else}
			<p class="empty">{depth === 0 ? 'The flow is empty.' : 'No nodes yet.'}</p>
		{/if}
		{@render gap(parent, arm, items.length, listLabel)}
	</div>
{/snippet}

{@render list(nodesOf(nodes), null, null, 0, label)}

<style>
	.flow-list {
		display: flex;
		flex-direction: column;
	}
	ol {
		margin: 0;
		padding: 0;
		list-style: none;
		display: flex;
		flex-direction: column;
	}
	.arm {
		position: relative;
		margin-block-start: var(--space-2);
		padding-inline-start: var(--space-3);
		border-inline-start: 2px solid var(--color-border);
	}
	.arm-label {
		margin: 0;
		font-size: var(--text-xs);
		font-weight: var(--weight-bold);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-muted);
	}
	.empty {
		margin: var(--space-1) 0 0;
		font-size: var(--text-sm);
		font-style: italic;
		color: var(--color-text-muted);
	}
	.gap {
		position: relative;
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 1.75rem;
		border-radius: var(--radius-sm);
	}
	.gap::before {
		content: '';
		position: absolute;
		inset-inline: 0;
		top: 50%;
		border-top: 1px dashed transparent;
	}
	.gap:hover::before,
	.gap:focus-within::before {
		border-top-color: var(--color-border-strong);
	}
	.gap.dropzone {
		outline: 1px dashed var(--color-border-strong);
		outline-offset: -4px;
	}
	.gap.over {
		background: var(--color-accent-subtle);
		outline: 2px solid var(--color-accent);
	}
	.add {
		position: relative;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 1.5rem;
		height: 1.5rem;
		padding: 0;
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-full);
		background: var(--color-bg);
		color: var(--color-text-muted);
		cursor: pointer;
	}
	.add:hover {
		border-color: var(--color-accent);
		color: var(--color-accent);
	}
	.add:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}
</style>
