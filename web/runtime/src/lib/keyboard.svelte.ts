/**
 * Is the on-screen keyboard (probably) open? runtime-design §6: the sticky nav bar docks
 * below the content while a text input is focused and the keyboard is up, and the focused
 * input is kept in view.
 *
 * Signals: a text-entry element has focus, and either the visual viewport is clearly shorter
 * than the layout viewport (iOS Safari, Android with `resizes-visual`) or the device has a
 * coarse pointer (Android Chrome resizes the layout viewport instead, so the heights match).
 */
const TEXT_TYPES = new Set(['text', 'search', 'email', 'tel', 'url', 'number', 'password', '']);

export function isTextEntry(el: Element | null): boolean {
	if (!el) return false;
	if (el instanceof HTMLTextAreaElement) return true;
	if (el instanceof HTMLInputElement) return TEXT_TYPES.has(el.type);
	return el instanceof HTMLElement && el.isContentEditable;
}

class KeyboardState {
	open = $state(false);
	private focused = false;

	start(): () => void {
		const vv = window.visualViewport;
		const coarse = window.matchMedia?.('(pointer: coarse)');
		const update = () => {
			const shrunk = !!vv && window.innerHeight - vv.height > 120;
			this.open = this.focused && (shrunk || !!coarse?.matches);
		};
		const onFocusIn = (e: FocusEvent) => {
			this.focused = isTextEntry(e.target as Element);
			update();
		};
		const onFocusOut = () => {
			// focusout fires before the next focusin; wait for it.
			queueMicrotask(() => {
				this.focused = isTextEntry(document.activeElement);
				update();
			});
		};
		const onResize = () => {
			update();
			if (this.focused) {
				(document.activeElement as HTMLElement | null)?.scrollIntoView?.({ block: 'nearest' });
			}
		};
		document.addEventListener('focusin', onFocusIn);
		document.addEventListener('focusout', onFocusOut);
		vv?.addEventListener('resize', onResize);
		return () => {
			document.removeEventListener('focusin', onFocusIn);
			document.removeEventListener('focusout', onFocusOut);
			vv?.removeEventListener('resize', onResize);
		};
	}
}

export const keyboard = new KeyboardState();
