<script lang="ts">
	import { Tooltip } from '@osp/ui-components';
	import type { ExportBadge } from './model';

	/**
	 * Export badges for one card (task B10): `<li>` items, for a card's `exportBadges` slot or
	 * any `<ul>`. Each is a button (so the tooltip is reachable by keyboard) that goes to the
	 * property concerned; the reasons are also in its accessible description.
	 */
	let { badges, ongo }: { badges: readonly ExportBadge[]; ongo?: (b: ExportBadge) => void } = $props();
	const uid = $props.id();
</script>

{#each badges as b, i (b.level)}
	{@const rid = `xb-${uid}-${i}`}
	<li class="xbadge" data-export-badge={b.level}>
		<Tooltip text={b.reasons.join(' ')} side="top">
			{#snippet trigger(props)}
				<button {...props} type="button" class="xbadge-btn" aria-describedby={rid} onclick={() => ongo?.(b)}>
					{b.label}
				</button>
			{/snippet}
		</Tooltip>
		<span id={rid} class="osp-visually-hidden">{b.reasons.join(' ')}</span>
	</li>
{/each}

<style>
	.xbadge {
		position: relative;
		z-index: 2; /* above a card's stretched select button */
		display: inline-flex;
		list-style: none;
	}
	.xbadge-btn {
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-full);
		background: var(--color-surface-sunken);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		line-height: 1.6;
		cursor: pointer;
	}
	[data-export-badge='unsupported'] .xbadge-btn {
		border-color: var(--color-danger);
		color: var(--color-danger);
	}
	[data-export-badge='approximated'] .xbadge-btn {
		border-color: var(--color-warning);
		color: var(--color-warning);
	}
	.xbadge-btn:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}
</style>
