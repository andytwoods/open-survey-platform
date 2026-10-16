<script lang="ts">
	/**
	 * Vertical splitter between two panes (WAI-ARIA window splitter pattern).
	 * `size` is the controlled pane's width in px. Drag with the pointer, or focus it and
	 * use Left/Right (Shift for bigger steps), Home/End for min/max.
	 * `edge`: which side of the splitter the controlled pane is on.
	 */
	let {
		size = $bindable(280),
		min = 180,
		max = 560,
		step = 16,
		edge = 'left',
		label,
		controls
	}: {
		size?: number;
		min?: number;
		max?: number;
		step?: number;
		edge?: 'left' | 'right';
		label: string;
		/** id of the pane being resized */
		controls: string;
	} = $props();

	let dragging = $state(false);
	let startX = 0;
	let startSize = 0;

	const clamp = (v: number) => Math.min(max, Math.max(min, Math.round(v)));
	const dir = $derived(edge === 'left' ? 1 : -1);

	function onpointerdown(e: PointerEvent) {
		if (e.button !== 0) return;
		dragging = true;
		startX = e.clientX;
		startSize = size;
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
		e.preventDefault();
	}
	function onpointermove(e: PointerEvent) {
		if (!dragging) return;
		size = clamp(startSize + dir * (e.clientX - startX));
	}
	function onpointerup(e: PointerEvent) {
		dragging = false;
		(e.currentTarget as HTMLElement).releasePointerCapture?.(e.pointerId);
	}
	function onkeydown(e: KeyboardEvent) {
		const s = e.shiftKey ? step * 4 : step;
		const keys: Record<string, () => number> = {
			ArrowLeft: () => size - dir * s,
			ArrowRight: () => size + dir * s,
			Home: () => min,
			End: () => max
		};
		const next = keys[e.key];
		if (!next) return;
		e.preventDefault();
		size = clamp(next());
	}
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div
	class="osp-resizer"
	class:dragging
	role="separator"
	aria-orientation="vertical"
	aria-label={label}
	aria-controls={controls}
	aria-valuenow={size}
	aria-valuemin={min}
	aria-valuemax={max}
	tabindex="0"
	{onpointerdown}
	{onpointermove}
	{onpointerup}
	onpointercancel={onpointerup}
	{onkeydown}
></div>

<style>
	.osp-resizer {
		position: relative;
		width: 6px;
		margin-inline: -3px;
		z-index: 2;
		cursor: col-resize;
		touch-action: none;
		background: transparent;
	}
	.osp-resizer::after {
		content: '';
		position: absolute;
		inset-block: 0;
		left: 2px;
		width: 2px;
		background: transparent;
		transition: background var(--duration-fast);
	}
	.osp-resizer:hover::after,
	.osp-resizer.dragging::after,
	.osp-resizer:focus-visible::after {
		background: var(--color-accent);
	}
	.osp-resizer:focus-visible {
		outline-offset: 0;
	}
</style>
