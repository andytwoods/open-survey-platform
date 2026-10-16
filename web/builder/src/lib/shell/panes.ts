/**
 * F6 pane cycling. Each pane root carries data-pane="<name>"; inside it, the element
 * marked data-pane-focus (e.g. the outline's roving-tabindex item) receives focus,
 * falling back to the first focusable element, then the pane itself.
 */
export const PANE_ORDER = [
	'topbar',
	'outline',
	'canvas',
	'properties',
	// The Appearance view's two panes.
	'appearance-controls',
	'appearance-preview'
] as const;
export type PaneName = (typeof PANE_ORDER)[number];

const FOCUSABLE =
	'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function visiblePanes(doc: Document): HTMLElement[] {
	return PANE_ORDER.map((p) => doc.querySelector<HTMLElement>(`[data-pane="${p}"]`)).filter(
		(el): el is HTMLElement => !!el && el.getClientRects().length > 0
	);
}

export function focusPane(el: HTMLElement) {
	const target =
		el.querySelector<HTMLElement>('[data-pane-focus]') ??
		el.querySelector<HTMLElement>(FOCUSABLE) ??
		el;
	if (target === el && !el.hasAttribute('tabindex')) el.tabIndex = -1;
	target.focus();
}

export function cyclePane(dir: 1 | -1, doc: Document = document): PaneName | null {
	const panes = visiblePanes(doc);
	if (!panes.length) return null;
	const current = (doc.activeElement as HTMLElement | null)?.closest<HTMLElement>('[data-pane]');
	const i = current ? panes.indexOf(current) : -1;
	const next =
		i < 0 ? (dir === 1 ? 0 : panes.length - 1) : (i + dir + panes.length) % panes.length;
	focusPane(panes[next]);
	return (panes[next].dataset.pane as PaneName) ?? null;
}
