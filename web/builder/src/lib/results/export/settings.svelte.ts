import { DEFAULT_K, MAX_MM, MIN_MM, WIDTH_PRESETS } from './model';

/**
 * Export settings for the page's lifetime (task V4): width, DPI, "Hide counts below k"
 * (off by default, V-D4) and the captions the researcher edited, per question. Shared by
 * every card's dialog and "Export all", so a ZIP uses the captions as edited.
 */
export class ExportSettings {
	widthPreset = $state<'single' | 'double' | 'custom'>('single');
	customMm = $state(120);
	dpi = $state(300);
	hide = $state(false);
	kValue = $state(DEFAULT_K);
	#captions = $state<Record<string, string>>({});

	get widthMm(): number {
		if (this.widthPreset === 'custom') return Math.min(MAX_MM, Math.max(MIN_MM, Math.round(Number(this.customMm) || 0)));
		return WIDTH_PRESETS.find((p) => p.id === this.widthPreset)!.mm;
	}

	/** The threshold when "Hide counts below k" is on (k ≥ 2), else null. */
	get k(): number | null {
		const k = Math.round(Number(this.kValue));
		return this.hide && Number.isFinite(k) && k >= 2 ? Math.min(k, 1000) : null;
	}

	caption(question: string): string | undefined {
		return this.#captions[question];
	}

	setCaption(question: string, text: string) {
		this.#captions = { ...this.#captions, [question]: text };
	}

	resetCaption(question: string) {
		const next = { ...this.#captions };
		delete next[question];
		this.#captions = next;
	}
}
