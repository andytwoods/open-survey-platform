/**
 * Auto-scroll while dragging (B19): with the pointer within `EDGE` px of the scroller's top
 * or bottom edge (and over it sideways), scroll that way, faster the closer it is. Runs on
 * animation frames until `stop()`; `onscroll` lets the caller re-hit-test the pointer.
 * `edgeSpeed` is pure, so it is unit tested.
 */

export const EDGE = 48;
export const MAX_SPEED = 18;
export const DWELL_MS = 120;

/** Pixels per frame to scroll for pointer `y` against a scroller spanning top..bottom. */
export function edgeSpeed(y: number, top: number, bottom: number, edge = EDGE, max = MAX_SPEED): number {
	if (!Number.isFinite(y) || bottom - top < edge * 2) return 0;
	if (y < top + edge) return -Math.ceil(max * Math.min(1, (top + edge - y) / edge));
	if (y > bottom - edge) return Math.ceil(max * Math.min(1, (y - (bottom - edge)) / edge));
	return 0;
}

/** The nearest ancestor (or itself) that scrolls vertically, else the document's scroller. */
export function scrollParent(el: Element | null): HTMLElement | null {
	for (let n = el; n; n = n.parentElement) {
		if (!(n instanceof HTMLElement)) continue;
		const oy = getComputedStyle(n).overflowY;
		if ((oy === 'auto' || oy === 'scroll') && n.scrollHeight > n.clientHeight) return n;
	}
	return (document.scrollingElement as HTMLElement | null) ?? null;
}

export class AutoScroller {
	#frame = 0;
	#since = 0;
	#x = 0;
	#y = 0;
	readonly #scroller: () => HTMLElement | null;
	readonly #onscroll: () => void;

	constructor(scroller: () => HTMLElement | null, onscroll: () => void) {
		this.#scroller = scroller;
		this.#onscroll = onscroll;
	}

	/** The pointer moved; starts the loop if it is not running. */
	update(x: number, y: number) {
		this.#x = x;
		this.#y = y;
		if (!this.#frame && typeof requestAnimationFrame === 'function') {
			this.#frame = requestAnimationFrame(this.#tick);
		}
	}

	stop() {
		if (this.#frame) cancelAnimationFrame(this.#frame);
		this.#frame = 0;
		this.#since = 0;
	}

	#tick = () => {
		this.#frame = 0;
		const el = this.#scroller();
		if (!el) return;
		const r = el.getBoundingClientRect();
		const over = this.#x >= r.left && this.#x <= r.right;
		const dy = over ? edgeSpeed(this.#y, r.top, r.bottom) : 0;
		// Only after resting in the edge zone a moment, so passing through it does not scroll.
		const now = performance.now();
		if (!dy) this.#since = 0;
		else if (!this.#since) this.#since = now;
		if (dy && now - this.#since >= DWELL_MS) {
			const before = el.scrollTop;
			el.scrollTop = before + dy;
			if (el.scrollTop !== before) this.#onscroll();
		}
		// Keep watching while the drag lasts: the pointer may rest at the edge.
		this.#frame = requestAnimationFrame(this.#tick);
	};
}
