/** The embedding page: records every window message it receives (postToParent tests). */

declare global {
	interface Window {
		received: Array<{ origin: string; data: unknown }>;
	}
}

window.received = [];
window.addEventListener('message', (e) => {
	window.received.push({ origin: e.origin, data: e.data });
});

export {};
