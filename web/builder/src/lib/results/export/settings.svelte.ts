import { DEFAULT_K, DPI_CHOICES, MAX_MM, MIN_MM, WIDTH_PRESETS } from './model';

/** What "Export all" puts in the ZIP (task V6). */
export type Bundle = 'svg' | 'png' | 'all';
export const BUNDLES: readonly Bundle[] = ['svg', 'png', 'all'];

/** The export settings a saved layout keeps (task V6). */
export interface ExportChoices {
	widthMm: number;
	dpi: number;
	/** "Hide counts below k", or null when off. */
	k: number | null;
	bundle: Bundle;
}

export const DEFAULT_EXPORT: ExportChoices = { widthMm: 85, dpi: 300, k: null, bundle: 'all' };

/**
 * Export settings (task V4): width, DPI, "Hide counts below k" (off by default, V-D4),
 * what "Export all" bundles (V6) and the captions the researcher edited, per question.
 * Shared by every card's dialog and "Export all", so a ZIP uses the captions as edited.
 * A saved layout keeps all of it (V5b, V6).
 */
export class ExportSettings {
	widthPreset = $state<'single' | 'double' | 'custom'>('single');
	customMm = $state(120);
	dpi = $state(300);
	hide = $state(false);
	kValue = $state(DEFAULT_K);
	bundle = $state<Bundle>('all');
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

	/** The edited captions (a saved layout keeps them, task V5b). */
	get captions(): Readonly<Record<string, string>> {
		return this.#captions;
	}

	/** Replace the edited captions (a layout was opened). */
	restoreCaptions(captions: Readonly<Record<string, string>>) {
		this.#captions = { ...captions };
	}

	/** Width, DPI, k and bundle as a saved layout keeps them. */
	snapshot(): ExportChoices {
		return { widthMm: this.widthMm, dpi: this.dpi, k: this.k, bundle: this.bundle };
	}

	/** Replace width, DPI, k and bundle (a layout was opened); out-of-range values take the defaults. */
	restore(c: ExportChoices) {
		const mm = Number.isFinite(c.widthMm) && c.widthMm >= MIN_MM && c.widthMm <= MAX_MM ? Math.round(c.widthMm) : DEFAULT_EXPORT.widthMm;
		const preset = WIDTH_PRESETS.find((p) => p.mm === mm);
		this.widthPreset = preset?.id ?? 'custom';
		if (!preset) this.customMm = mm;
		this.dpi = (DPI_CHOICES as readonly number[]).includes(c.dpi) ? c.dpi : DEFAULT_EXPORT.dpi;
		const k = c.k === null || c.k === undefined ? null : Math.round(Number(c.k));
		this.hide = k !== null && Number.isFinite(k) && k >= 2;
		this.kValue = this.hide ? Math.min(k!, 1000) : DEFAULT_K;
		this.bundle = BUNDLES.includes(c.bundle) ? c.bundle : DEFAULT_EXPORT.bundle;
	}
}
