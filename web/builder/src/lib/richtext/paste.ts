/**
 * Paste cleaning (planning/rich-text.md §6). ProseMirror parses pasted HTML through the
 * schema, so anything the schema has no rule for is dropped or unwrapped by construction;
 * this pass runs before that parse to lower what the schema would otherwise lose badly
 * (nested lists, h4–h6, tables, Word's wrappers) and to count what the researcher loses, for
 * the "Formatting simplified" status line. DOM parsing only: nothing here is executed and
 * nothing is inserted into the live page. The server re-validates every value anyway; this
 * is for the researcher, not for safety.
 */
import type { Level } from './levels';

export interface PasteReport {
	images: number;
	tables: number;
	underline: number;
	/** Links removed because their target is not https. */
	links: number;
	/** Headings lowered (h4–h6 → h3, or any heading in a stem/inline field). */
	headings: number;
	/** Nested lists flattened to one level. */
	nested: number;
	/** Colours, fonts, sizes, alignment or other styling dropped. */
	styles: boolean;
	/** Several paragraphs or list items merged into one line (inline fields). */
	merged: number;
}

export const emptyReport = (): PasteReport => ({
	images: 0,
	tables: 0,
	underline: 0,
	links: 0,
	headings: 0,
	nested: 0,
	styles: false,
	merged: 0
});

const DROP = 'script, style, meta, link, title, head, img, picture, svg, video, audio, iframe, object, embed, input, button, select, textarea, canvas, map, noscript, template';
/** Inline wrappers the schema has no mark for: their text stays. Spans keep a font-weight / font-style (Bold and Italic read those). */
const UNWRAP_INLINE = 'font, span:not([lang]):not([style]), code, kbd, samp, var, mark, small, big, sub, sup, abbr, cite, q, dfn, time, label, legend, tt, s, strike, del, ins, u, dt, summary';
/** Block containers: unwrapped when they hold blocks, else they become a paragraph. */
const CONTAINERS = 'div, section, article, header, footer, main, nav, aside, blockquote, pre, form, fieldset, center, address, figure, figcaption, dl, dd, details';
const BLOCKS = 'p, div, h1, h2, h3, h4, h5, h6, ul, ol, li, table, blockquote, section, article, figure, figcaption, pre, dl, dd, header, footer, main, nav, aside, form, fieldset, center, address, details';
const STYLED = /(^|;)\s*(color|background[a-z-]*|font-family|font-size|text-align|letter-spacing|line-height|margin[a-z-]*|padding[a-z-]*|text-indent)\s*:/i;

function unwrap(el: Element): void {
	const parent = el.parentNode;
	if (!parent) return;
	while (el.firstChild) parent.insertBefore(el.firstChild, el);
	parent.removeChild(el);
}

function isHttps(href: string | null): boolean {
	return !!href && /^https:\/\/\S+$/i.test(href.trim()) && href.trim().length <= 2000;
}

/**
 * Clean pasted HTML for a field of `level`. Returns the HTML ProseMirror should parse and
 * what was changed. `pipes` false leaves `${id}` as text (the editor converts otherwise).
 */
export function cleanPastedHtml(html: string, level: Level, parser: DOMParser = new DOMParser()): { html: string; report: PasteReport } {
	const report = emptyReport();
	const doc = parser.parseFromString(html, 'text/html');
	const body = doc.body;
	// Comments (Word's conditional comments, Google Docs markers).
	const walker = doc.createTreeWalker(body, 128 /* NodeFilter.SHOW_COMMENT */);
	const comments: Node[] = [];
	while (walker.nextNode()) comments.push(walker.currentNode);
	for (const c of comments) c.parentNode?.removeChild(c);

	report.images = body.querySelectorAll('img, picture, svg, video, audio, iframe, object, embed, canvas').length;
	for (const el of [...body.querySelectorAll(DROP)]) el.remove();
	// Word's `<o:p>` and other namespaced wrappers.
	for (const el of [...body.querySelectorAll('*')]) if (el.tagName.includes(':')) unwrap(el);

	// Tables: one paragraph per row, cells separated by a space (the model has no tables).
	for (const table of [...body.querySelectorAll('table')]) {
		report.tables++;
		const frag = doc.createDocumentFragment();
		for (const row of [...table.querySelectorAll('tr')]) {
			const p = doc.createElement('p');
			[...row.children].forEach((cell, i) => {
				if (i > 0) p.appendChild(doc.createTextNode(' '));
				while (cell.firstChild) p.appendChild(cell.firstChild);
			});
			frag.appendChild(p);
		}
		table.replaceWith(frag);
	}

	// Underline (no underline mark: lead decision 1), links that are not https, styles.
	for (const el of [...body.querySelectorAll('u, ins, [style*="underline" i]')]) {
		report.underline++;
		if (el.matches('u, ins')) unwrap(el);
		else (el as HTMLElement).style.removeProperty('text-decoration');
	}
	for (const a of [...body.querySelectorAll('a')]) {
		if (isHttps(a.getAttribute('href'))) {
			a.setAttribute('href', a.getAttribute('href')!.trim());
			continue;
		}
		report.links++;
		unwrap(a);
	}
	for (const el of [...body.querySelectorAll('[style]')]) {
		const style = el.getAttribute('style') ?? '';
		if (STYLED.test(style)) report.styles = true;
		// Keep only what the Bold/Italic parse rules read.
		const weight = (el as HTMLElement).style.fontWeight;
		const fstyle = (el as HTMLElement).style.fontStyle;
		el.removeAttribute('style');
		if (weight) (el as HTMLElement).style.fontWeight = weight;
		if (fstyle) (el as HTMLElement).style.fontStyle = fstyle;
	}
	if (body.querySelector('font, [color], [face], [size], [align]')) report.styles = true;
	for (const el of [...body.querySelectorAll('[color], [face], [size], [align], [bgcolor], [class], [id], [dir], [width], [height]')]) {
		for (const attr of ['color', 'face', 'size', 'align', 'bgcolor', 'class', 'id', 'dir', 'width', 'height']) el.removeAttribute(attr);
	}

	// Headings: h4–h6 become h3 in block fields; any heading becomes a paragraph elsewhere.
	for (const h of [...body.querySelectorAll('h1, h2, h3, h4, h5, h6')]) {
		const n = Number(h.tagName[1]);
		if (level !== 'block') {
			report.headings++;
			retag(doc, h, 'p');
		} else if (n > 3) {
			report.headings++;
			retag(doc, h, 'h3');
		}
	}

	// Lists: flatten nesting (items of an inner list follow their parent item), and an item's
	// block children become one run (breaks between paragraphs).
	let nested = body.querySelector('li ul, li ol');
	while (nested) {
		report.nested++;
		const li = nested.parentElement!;
		const list = li.parentElement!;
		const after = li.nextSibling;
		for (const inner of [...nested.children]) list.insertBefore(inner, after);
		nested.remove();
		nested = body.querySelector('li ul, li ol');
	}
	for (const li of [...body.querySelectorAll('li')]) {
		const blocks = [...li.children].filter((c) => /^(P|DIV|H[1-6])$/.test(c.tagName));
		blocks.forEach((b, i) => {
			if (i > 0) b.before(doc.createElement('br'));
			unwrap(b);
		});
	}
	// Containers, outermost first: one holding blocks is unwrapped (its blocks stand on their
	// own); one holding only inline content becomes a paragraph.
	for (const el of [...body.querySelectorAll(CONTAINERS)]) {
		if (!el.isConnected) continue;
		if (el.querySelector(BLOCKS)) unwrap(el);
		else retag(doc, el, 'p');
	}
	for (const el of [...body.querySelectorAll(UNWRAP_INLINE)]) unwrap(el);
	// Stray breaks between blocks (Google Docs' trailing "interchange newline").
	for (const br of [...body.children].filter((c) => c.tagName === 'BR')) br.remove();
	// Inline fields hold one line: block boundaries become breaks.
	if (level === 'inline') {
		const blocks = [...body.children].filter((c) => /^(P|H[1-6]|UL|OL)$/.test(c.tagName));
		if (blocks.length > 1 || blocks.some((b) => /^(UL|OL)$/.test(b.tagName))) {
			const p = doc.createElement('p');
			let parts = 0;
			for (const b of blocks) {
				const items = /^(UL|OL)$/.test(b.tagName) ? [...b.querySelectorAll('li')] : [b];
				for (const item of items) {
					if (parts++ > 0) p.appendChild(doc.createElement('br'));
					while (item.firstChild) p.appendChild(item.firstChild);
				}
				b.remove();
			}
			report.merged = Math.max(0, parts - 1);
			body.appendChild(p);
		}
	}
	// `&nbsp;` to spaces.
	const texts = doc.createTreeWalker(body, 4 /* NodeFilter.SHOW_TEXT */);
	while (texts.nextNode()) {
		const t = texts.currentNode as Text;
		if (t.data.includes('\u00a0')) t.data = t.data.replace(/\u00a0/g, ' ');
	}
	return { html: body.innerHTML, report };
}

function retag(doc: Document, el: Element, tag: string): Element {
	const next = doc.createElement(tag);
	while (el.firstChild) next.appendChild(el.firstChild);
	el.replaceWith(next);
	return next;
}

const plural = (n: number, one: string, many = one + 's') => `${n} ${n === 1 ? one : many}`;

/** The status line after a paste that changed something, or null when nothing was lost. */
export function describeReport(r: PasteReport): string | null {
	const parts: string[] = [];
	if (r.styles) parts.push('colours and fonts');
	if (r.images) parts.push(plural(r.images, 'image'));
	if (r.tables) parts.push(plural(r.tables, 'table'));
	if (r.underline) parts.push('underline');
	if (r.headings) parts.push(plural(r.headings, 'heading'));
	if (r.nested) parts.push(plural(r.nested, 'nested list'));
	if (r.merged) parts.push(plural(r.merged, 'line break', 'line breaks') + ' kept as one line');
	if (r.links) parts.push(`${plural(r.links, 'link')} removed: not https`);
	if (!parts.length) return null;
	const removed = parts.filter((p) => !p.includes('removed') && !p.includes('kept'));
	const rest = parts.filter((p) => p.includes('removed') || p.includes('kept'));
	const head = removed.length ? `${removed.join(', ').replace(/, ([^,]*)$/, ' and $1')} removed` : '';
	return `Formatting simplified: ${[head, ...rest].filter(Boolean).join('; ')}`;
}
