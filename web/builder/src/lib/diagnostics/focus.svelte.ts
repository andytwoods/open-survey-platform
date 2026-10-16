/**
 * "Go to this property" requests from the diagnostics strip and export badges to the
 * properties pane (task B10). The pane owns the property panel and calls its
 * `focusProperty(path)`; this only carries the request across the shell.
 */
export interface FocusRequest {
	/** Block, page or question id, or `SURVEY_ID`. */
	id: string;
	/** Candidate property keys, most specific first. */
	properties: string[];
	seq: number;
}

class PropertyFocus {
	request = $state.raw<FocusRequest | null>(null);
	#seq = 0;

	ask(id: string, properties: string[]) {
		this.request = { id, properties, seq: ++this.#seq };
	}

	/** The pane handled request `seq` (focused a field, or gave up). */
	done(seq: number) {
		if (this.request?.seq === seq) this.request = null;
	}
}

export const propertyFocus = new PropertyFocus();
