/**
 * Presentation mode (task V6): the Results page shows only the cards, and the shell hides
 * its top bar. One module-level flag, so the shell and the page agree; the page mirrors it
 * into the URL (`?present=1`, see `presentation.ts`) so the view can be shared or printed.
 */
class Presentation {
	active = $state(false);

	enter() {
		this.active = true;
	}

	exit() {
		this.active = false;
	}

	toggle() {
		this.active = !this.active;
	}
}

export const presentation = new Presentation();
