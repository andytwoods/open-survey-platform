// jsdom setup for the widget tests: Testing Library cleanup, plus the few browser APIs
// Bits UI touches that jsdom lacks.
import '@testing-library/svelte/vitest';

const g = globalThis as Record<string, unknown>;

if (!('PointerEvent' in g)) {
	class PointerEventPolyfill extends MouseEvent {
		pointerId: number;
		pointerType: string;
		constructor(type: string, init: PointerEventInit = {}) {
			super(type, init);
			this.pointerId = init.pointerId ?? 1;
			this.pointerType = init.pointerType ?? 'mouse';
		}
	}
	g.PointerEvent = PointerEventPolyfill;
}

if (!('ResizeObserver' in g)) {
	g.ResizeObserver = class {
		observe() {}
		unobserve() {}
		disconnect() {}
	};
}

if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = () => {};
if (!Element.prototype.hasPointerCapture) {
	Element.prototype.hasPointerCapture = () => false;
	Element.prototype.setPointerCapture = () => {};
	Element.prototype.releasePointerCapture = () => {};
}
if (!g.matchMedia) {
	g.matchMedia = (query: string) => ({
		matches: false,
		media: query,
		onchange: null,
		addEventListener() {},
		removeEventListener() {},
		addListener() {},
		removeListener() {},
		dispatchEvent: () => false
	});
}
