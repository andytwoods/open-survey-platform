/**
 * Native radio groups select on arrow keys even when nothing is selected yet; Bits UI's
 * RadioGroup only moves focus in that case. These handlers (put on each item; they run
 * before Bits' own) select the item that an arrow key moved focus to, so keyboard users
 * get the same behaviour as a native group.
 */
export function arrowSelect(isEmpty: () => boolean, select: (value: string) => void) {
	let arrow = false;
	return {
		onkeydown(e: KeyboardEvent) {
			arrow = e.key.startsWith('Arrow');
			// Bits moves focus synchronously inside this keydown; reset after it.
			queueMicrotask(() => (arrow = false));
		},
		onfocus(value: string) {
			if (arrow && isEmpty()) select(value);
		}
	};
}
