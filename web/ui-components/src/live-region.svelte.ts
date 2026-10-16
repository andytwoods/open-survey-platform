/**
 * Screen-reader announcements and toasts. Render <Announcer /> once near the app root;
 * call announce() for messages that only need to be heard, toast() for ones that should
 * also be seen. Both go through aria-live regions that exist from page load, so the
 * first message is not lost.
 */
export type Politeness = 'polite' | 'assertive';
export type ToastKind = 'info' | 'success' | 'error';

export interface ToastItem {
	id: number;
	message: string;
	kind: ToastKind;
}

class AnnouncerState {
	polite = $state('');
	assertive = $state('');
	toasts = $state<ToastItem[]>([]);
	#nextId = 1;
	#timers = new Map<number, ReturnType<typeof setTimeout>>();

	announce(message: string, politeness: Politeness = 'polite') {
		// Clear first so repeating the same message is announced again.
		this[politeness] = '';
		setTimeout(() => (this[politeness] = message), 30);
	}

	toast(message: string, { kind = 'info', timeout = 5000 }: { kind?: ToastKind; timeout?: number } = {}) {
		const id = this.#nextId++;
		this.toasts = [...this.toasts, { id, message, kind }];
		if (timeout > 0) this.#timers.set(id, setTimeout(() => this.dismiss(id), timeout));
		return id;
	}

	dismiss(id: number) {
		clearTimeout(this.#timers.get(id));
		this.#timers.delete(id);
		this.toasts = this.toasts.filter((t) => t.id !== id);
	}
}

export const announcer = new AnnouncerState();

export function announce(message: string, politeness: Politeness = 'polite') {
	announcer.announce(message, politeness);
}

export function toast(message: string, options?: { kind?: ToastKind; timeout?: number }) {
	return announcer.toast(message, options);
}
