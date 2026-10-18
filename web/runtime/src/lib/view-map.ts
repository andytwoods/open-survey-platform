/**
 * PageView → widget props (ui-components/src/survey/types.ts). Pure formatting: which item
 * shows, its value, its error and its choices all come from the engine's view.
 */
import { toPlain, type RenderedBlock, type RenderedRun, type RenderedText, type ViewItem } from '@osp/engine';
import type { Choice, InlineNode, Text, TextBlock } from '@osp/ui-components/survey';
import { ui } from './messages';

function node(r: RenderedRun): InlineNode {
	if (r.kind === 'br') return { br: true };
	if (r.kind === 'value') return { text: r.text };
	return {
		text: r.text,
		...(r.marks?.includes('b') ? { strong: true } : {}),
		...(r.marks?.includes('i') ? { em: true } : {}),
		...(r.lang ? { lang: r.lang } : {}),
		...(r.href ? { href: r.href } : {})
	};
}

function block(b: RenderedBlock): TextBlock {
	if (b.type === 'ul' || b.type === 'ol') return { type: b.type, items: b.items.map((i) => i.map(node)) };
	if (b.type === 'h') return { type: 'h', level: b.level, content: b.content.map(node) };
	return { type: 'p', content: b.content.map(node) };
}

/**
 * Engine text → widget text (planning/rich-text.md §7). Widgets render text nodes and
 * our own elements, never HTML, so researcher text and piped participant values are both
 * safe (§7: values are escaped by construction). A single paragraph becomes inline runs
 * (valid inside a `<label>`); anything else becomes blocks.
 */
export function segs(text: RenderedText | null | undefined): Text {
	if (!text || text.length === 0) return [];
	if (text.length === 1 && text[0]!.type === 'p') return text[0]!.content.map(node);
	return text.map(block);
}

/** Engine text as widget blocks, always (a reading page: every paragraph gets its `<p>`). */
export function blocks(text: RenderedText | null | undefined): TextBlock[] {
	return (text ?? []).map(block);
}

export function plain(text: RenderedText | null | undefined): string {
	return toPlain(text ?? null);
}

/**
 * Rendered text as blocks for a reading page (the ending body, the consent text; end-of-
 * survey plan §4.1): plain-string paragraphs are split at blank lines in the researcher's
 * text (piped values are never split), as before RT2; rich blocks stay as they are. Empty
 * paragraphs go.
 */
export function paragraphs(text: RenderedText | null | undefined): RenderedText {
	const out: RenderedText = [];
	for (const b of text ?? []) {
		if (b.type !== 'p') {
			out.push(b);
			continue;
		}
		const parts: RenderedRun[][] = [[]];
		for (const p of b.content) {
			if (p.kind !== 'text') {
				parts[parts.length - 1]!.push(p);
				continue;
			}
			p.text.split(/\n[^\S\n]*\n\s*/).forEach((t, i) => {
				if (i > 0) parts.push([]);
				if (t) parts[parts.length - 1]!.push({ ...p, text: t });
			});
		}
		for (const content of parts) {
			if (content.some((s) => s.kind === 'br' || s.text.trim() !== '')) out.push({ type: 'p', content });
		}
	}
	return out;
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
