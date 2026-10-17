/**
 * PageView → widget props (ui-components/src/survey/types.ts). Pure formatting: which item
 * shows, its value, its error and its choices all come from the engine's view.
 */
import type { RenderedText, ViewItem } from '@osp/engine';
import type { Choice, TextSegment } from '@osp/ui-components/survey';
import { ui } from './messages';

/**
 * Engine text → widget text segments. Widgets render text nodes, never HTML, so researcher
 * text and piped participant values are both safe (§7: values are escaped by construction).
 */
export function segs(text: RenderedText | null | undefined): TextSegment[] {
	return (text ?? []).map((p) => ({ text: p.text }));
}

export function plain(text: RenderedText | null | undefined): string {
	return (text ?? []).map((p) => p.text).join('');
}

/**
 * Rendered text split into paragraphs at blank lines in the researcher's text (piped values
 * are never split), for the ending body (end-of-survey plan §4.1). Empty paragraphs go.
 */
export function paragraphs(text: RenderedText | null | undefined): RenderedText[] {
	const out: RenderedText[] = [[]];
	for (const p of text ?? []) {
		if (p.kind !== 'text') {
			out[out.length - 1]!.push(p);
			continue;
		}
		p.text.split(/\n[^\S\n]*\n\s*/).forEach((t, i) => {
			if (i > 0) out.push([]);
			if (t) out[out.length - 1]!.push({ kind: 'text', text: t });
		});
	}
	return out.filter((par) => par.some((s) => s.text.trim() !== ''));
}

export function choicesOf(item: ViewItem): Choice[] {
	return (item.choices ?? []).map((c) => ({ value: String(c.value), label: segs(c.label) }));
}

/** The engine's error for an item, as the one-line message the widget shows. */
export function errorText(item: Pick<ViewItem, 'error'>): string | null {
	const e = item.error;
	if (!e) return null;
	const msg = plain(e.message);
	if (msg) return msg;
	if (e.kind === 'required') return ui.required;
	if (e.kind === 'constraint') return ui.constraint;
	return ui.invalid;
}

/** Stored engine value → the widget's value shape. */
export function widgetValue(item: ViewItem): unknown {
	const v = item.value;
	switch (item.type) {
		case 'integer':
		case 'decimal':
		case 'single':
		case 'date':
			return v === null || v === undefined ? null : String(v);
		case 'multi':
			return Array.isArray(v) ? v.map(String) : [];
		case 'text':
			return typeof v === 'string' ? v : '';
		default:
			return null;
	}
}

/** DOM id prefix for an item (QuestionFrame prefixes every id it creates with it). */
export const domId = (itemId: string) => `q-${itemId}`;
