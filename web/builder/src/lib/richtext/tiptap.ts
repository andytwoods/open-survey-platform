/**
 * The Tiptap 3 editor behind RichTextEditor.svelte (planning/rich-text.md §2, §9): a
 * schema that can hold exactly the survey model's rich tree for a level (so the editor
 * cannot produce what the spec cannot store), the pipe chip node, our own https-only link
 * mark, the paste pass and the keyboard contract. Loaded as a lazy chunk on the first focus
 * of a text field; the only module outside this folder that `@tiptap/*` may be imported
 * from is nowhere (dependency-cruiser rule `tiptap-stays-in-richtext`).
 *
 * Clean-room: Tiptap's API is learnt from its documentation (MIT code we depend on).
 */
import { Editor, Extension, InputRule, Mark, Node, mergeAttributes, type Range } from '@tiptap/core';
import Bold from '@tiptap/extension-bold';
import Document from '@tiptap/extension-document';
import HardBreak from '@tiptap/extension-hard-break';
import Heading from '@tiptap/extension-heading';
import Italic from '@tiptap/extension-italic';
import { BulletList, ListItem, OrderedList } from '@tiptap/extension-list';
import Paragraph from '@tiptap/extension-paragraph';
import Text from '@tiptap/extension-text';
import { Placeholder, UndoRedo } from '@tiptap/extensions';
import { Fragment, Slice, type Node as PmNodeModel, type Schema } from '@tiptap/pm/model';
import { Plugin, PluginKey, Selection, TextSelection } from '@tiptap/pm/state';
import { Decoration, DecorationSet } from '@tiptap/pm/view';
import { M, N, PIPE_RE, isPipeRef, type PmNode } from './convert';
import type { Level } from './levels';
import { cleanPastedHtml, type PasteReport } from './paste';

export type { Editor, Range };

// --- Nodes and marks -----------------------------------------------------------------------

const isHttps = (href: string | null | undefined): href is string =>
	!!href && /^https:\/\/\S+$/i.test(href.trim()) && href.trim().length <= 2000;

/** `{pipe: id}`: an atom chip, one caret stop, removed as a whole (§4). */
const Pipe = Node.create({
	name: N.pipe,
	group: 'inline',
	inline: true,
	atom: true,
	selectable: true,
	draggable: false,
	addAttributes() {
		return {
			id: {
				default: '',
				parseHTML: (el: HTMLElement) => el.getAttribute('data-pipe') ?? '',
				renderHTML: (attrs: Record<string, unknown>) => ({ 'data-pipe': String(attrs.id ?? '') })
			}
		};
	},
	parseHTML() {
		return [{ tag: 'span[data-pipe]' }];
	},
	renderHTML({ node, HTMLAttributes }) {
		const id = String(node.attrs.id ?? '');
		return [
			'span',
			mergeAttributes(HTMLAttributes, {
				class: 'osp-rt-chip',
				contenteditable: 'false',
				role: 'img',
				'aria-label': `Piped answer: ${id}`,
				title: `Piped answer: ${id}`
			}),
			`\${${id}}`
		];
	},
	renderText({ node }) {
		return `\${${String(node.attrs.id ?? '')}}`;
	}
});

/** `href`: an absolute https URL (RT-D7). Not Tiptap's Link: no autolink, no linkify, no clicks. */
const Link = Mark.create({
	name: M.link,
	inclusive: false,
	keepOnSplit: false,
	addAttributes() {
		return { href: { default: null } };
	},
	parseHTML() {
		return [
			{
				tag: 'a[href]',
				getAttrs: (el: HTMLElement) => {
					const href = el.getAttribute('href');
					return isHttps(href) ? { href: href.trim() } : false;
				}
			}
		];
	},
	renderHTML({ HTMLAttributes }) {
		return ['a', mergeAttributes(HTMLAttributes, { class: 'osp-rt-link', target: '_blank', rel: 'noopener noreferrer' }), 0];
	}
});

/** `lang`: a per-run language span. No toolbar control yet; kept so a value round-trips. */
const LangSpan = Mark.create({
	name: M.lang,
	addAttributes() {
		return { lang: { default: null, parseHTML: (el: HTMLElement) => el.getAttribute('lang') } };
	},
	parseHTML() {
		return [{ tag: 'span[lang]' }];
	},
	renderHTML({ HTMLAttributes }) {
		return ['span', HTMLAttributes, 0];
	}
});

/** Headings 1–3; pasted h4–h6 are lowered to 3 (§6). */
const OspHeading = Heading.extend({
	parseHTML() {
		return [...(this.parent?.() ?? []), ...['h4', 'h5', 'h6'].map((tag) => ({ tag, attrs: { level: 3 } }))];
	}
}).configure({ levels: [1, 2, 3] });

/** Single-level lists: an item is one paragraph; Tab never nests (and so leaves the editor). */
const OspListItem = ListItem.extend({
	content: 'paragraph',
	addKeyboardShortcuts() {
		return { Enter: () => this.editor.commands.splitListItem(this.name) };
	}
});

// --- Keyboard contract (§9) ------------------------------------------------------------------

export interface KeyboardHooks {
	/** Bold/Italic toggled from the keyboard: announce "Bold on". */
	onToggle?: (name: 'Bold' | 'Italic', on: boolean) => void;
	onToolbar?: () => void;
	/** Escape: return true when handled (a draft was reverted), false to let it bubble. */
	onEscape?: () => boolean;
	/** Inline fields: Enter commits instead of splitting. */
	onEnter?: () => void;
}

const Shortcuts = Extension.create<KeyboardHooks>({
	name: 'ospShortcuts',
	priority: 1000,
	addOptions() {
		return {};
	},
	addKeyboardShortcuts() {
		const o = this.options;
		const toggle = (mark: 'bold' | 'italic', name: 'Bold' | 'Italic') => () => {
			const ok = this.editor.commands.toggleMark(mark);
			o.onToggle?.(name, this.editor.isActive(mark));
			return ok;
		};
		return {
			'Mod-b': toggle('bold', 'Bold'),
			'Mod-i': toggle('italic', 'Italic'),
			// No underline (lead decision 1): swallow the browser's own Ctrl+U.
			'Mod-u': () => true,
			// No link shortcut: Ctrl/Cmd+K is the builder's command palette.
			'Alt-F10': () => {
				o.onToolbar?.();
				return true;
			},
			Escape: () => o.onEscape?.() ?? false,
			Enter: () => {
				if (!o.onEnter) return false;
				o.onEnter();
				return true;
			},
			// Tab and Shift+Tab always leave the editor.
			Tab: () => false,
			'Shift-Tab': () => false
		};
	}
});

// --- Pipes and paste ---------------------------------------------------------------------------

export interface PipeHooks {
	/** Pipes allowed in this field (consent: no). */
	enabled: boolean;
	level: Level;
	/** `${` typed: open the picker for `range` (the two characters, left in place). */
	onTrigger?: (range: Range) => void;
	onPaste?: (report: PasteReport) => void;
}

/** Text nodes with `${id}` references split into text and pipe nodes. */
function convertPipes(frag: Fragment, schema: Schema): Fragment {
	const out: PmNodeModel[] = [];
	frag.forEach((node) => {
		if (node.isText && node.text && PIPE_RE.test(node.text)) {
			PIPE_RE.lastIndex = 0;
			let last = 0;
			for (const m of node.text.matchAll(PIPE_RE)) {
				const inner = m[1]!.trim();
				if (!isPipeRef(inner)) continue;
				const at = m.index ?? 0;
				if (at > last) out.push(schema.text(node.text.slice(last, at), node.marks));
				out.push(schema.nodes[N.pipe]!.create({ id: inner }));
				last = at + m[0].length;
			}
			if (last < node.text.length) out.push(schema.text(node.text.slice(last), node.marks));
		} else if (node.content.size) out.push(node.copy(convertPipes(node.content, schema)));
		else out.push(node);
	});
	PIPE_RE.lastIndex = 0;
	return Fragment.fromArray(out);
}

/** Block content flattened to one line of inline nodes (breaks between blocks), or null if already inline. */
function flattenInline(frag: Fragment, schema: Schema): Fragment | null {
	let hasBlock = false;
	frag.forEach((n) => {
		if (!n.isInline) hasBlock = true;
	});
	if (!hasBlock) return null;
	const out: PmNodeModel[] = [];
	const br = () => {
		if (out.length) out.push(schema.nodes[N.hardBreak]!.create());
	};
	const walk = (node: PmNodeModel) => {
		if (node.isInline) out.push(node);
		else if (node.isTextblock) {
			br();
			node.content.forEach((c) => out.push(c));
		} else node.content.forEach(walk);
	};
	frag.forEach(walk);
	return Fragment.fromArray(out);
}

const PipeRules = Extension.create<PipeHooks>({
	name: 'ospPipes',
	addOptions() {
		return { enabled: true, level: 'stem' as Level };
	},
	addInputRules() {
		if (!this.options.enabled) return [];
		const o = this.options;
		return [
			// `${` opens the picker; the characters stay in place (Escape leaves them as text).
			new InputRule({
				find: /\$\{$/,
				handler: ({ range }) => {
					o.onTrigger?.({ from: range.from, to: range.to });
					return null;
				}
			}),
			// A typed `${id}` becomes a chip when the inner text could be a reference.
			new InputRule({
				find: /\$\{([^}\s]+)\}$/,
				handler: ({ range, match, chain }) => {
					const inner = match[1]!.trim();
					if (!isPipeRef(inner)) return null;
					chain().deleteRange(range).insertContentAt(range.from, { type: N.pipe, attrs: { id: inner } }).run();
				}
			})
		];
	},
	addProseMirrorPlugins() {
		const o = this.options;
		return [
			new Plugin({
				key: new PluginKey('ospPaste'),
				props: {
					transformPastedHTML: (html) => {
						const { html: out, report } = cleanPastedHtml(html, o.level);
						o.onPaste?.(report);
						return out;
					},
					transformPasted: (slice, view) => pasteTransform(slice, view.state.schema, o.level, o.enabled)
				}
			})
		];
	}
});

/**
 * The slice-level paste pass: `${id}` references become chips (when the field pipes), and
 * an inline field takes block content as one line with breaks between the blocks.
 */
export function pasteTransform(slice: Slice, schema: Schema, level: Level, pipes: boolean): Slice {
	const frag = pipes ? convertPipes(slice.content, schema) : slice.content;
	if (level === 'inline') {
		const flat = flattenInline(frag, schema);
		if (flat) return new Slice(flat, 0, 0);
	}
	return new Slice(frag, slice.openStart, slice.openEnd);
}

// --- Server diagnostics on chips -----------------------------------------------------------------

const problemsKey = new PluginKey<ReadonlyMap<string, string>>('ospPipeProblems');

const problemsPlugin = new Plugin<ReadonlyMap<string, string>>({
	key: problemsKey,
	state: {
		init: () => new Map(),
		apply: (tr, prev) => (tr.getMeta(problemsKey) as ReadonlyMap<string, string> | undefined) ?? prev
	},
	props: {
		decorations(state) {
			const problems = problemsKey.getState(state);
			if (!problems?.size) return null;
			const decos: Decoration[] = [];
			state.doc.descendants((node, pos) => {
				if (node.type.name !== N.pipe) return;
				const message = problems.get(String(node.attrs.id));
				if (message) decos.push(Decoration.node(pos, pos + node.nodeSize, { class: 'osp-rt-chip-error', title: message, 'data-error': '' }));
			});
			return DecorationSet.create(state.doc, decos);
		}
	}
});

/** Show (or clear) the server's diagnostics on the chips they are about. */
export function setPipeProblems(editor: Editor, problems: ReadonlyMap<string, string>): void {
	editor.view.dispatch(editor.state.tr.setMeta(problemsKey, problems).setMeta('addToHistory', false));
}

// --- The editor --------------------------------------------------------------------------------------

export interface CreateOptions {
	element: HTMLElement;
	level: Level;
	pipes: boolean;
	content: PmNode;
	placeholder: string;
	/** Attributes of the editable root (role, aria-*, id). */
	attributes: Record<string, string>;
	onUpdate: () => void;
	onTransaction: () => void;
	keyboard: KeyboardHooks;
	pipeHooks: Omit<PipeHooks, 'enabled' | 'level'>;
}

/** The schema (nodes and marks) a level allows: exactly what the survey model can store. */
export function schemaExtensions(level: Level) {
	return [
		Document.extend({ content: level === 'inline' ? 'paragraph' : 'block+' }),
		Paragraph,
		Text,
		Bold,
		Italic,
		Link,
		LangSpan,
		Pipe,
		HardBreak,
		...(level === 'block' ? [OspHeading] : []),
		...(level === 'inline' ? [] : [BulletList, OrderedList, OspListItem])
	];
}

export function createEditor(o: CreateOptions): Editor {
	const extensions = [
		...schemaExtensions(o.level),
		UndoRedo,
		Placeholder.configure({ placeholder: o.placeholder, showOnlyWhenEditable: true }),
		Shortcuts.configure(o.keyboard),
		PipeRules.configure({ ...o.pipeHooks, enabled: o.pipes, level: o.level }),
		Extension.create({ name: 'ospProblems', addProseMirrorPlugins: () => [problemsPlugin] })
	];
	return new Editor({
		element: o.element,
		extensions,
		content: o.content,
		injectCSS: false,
		autofocus: false,
		editorProps: { attributes: o.attributes },
		onUpdate: () => o.onUpdate(),
		onTransaction: () => o.onTransaction()
	});
}

/** Replace the root's attributes (e.g. aria-invalid changed). */
export function setAttributes(editor: Editor, attributes: Record<string, string>): void {
	editor.setOptions({ editorProps: { ...editor.options.editorProps, attributes } });
}

// --- Commands the toolbar and dialogs use -----------------------------------------------------------

export interface ToolbarState {
	bold: boolean;
	italic: boolean;
	link: boolean;
	bulletList: boolean;
	orderedList: boolean;
	/** 0 for a paragraph. */
	heading: 0 | 1 | 2 | 3;
	canUndo: boolean;
	canRedo: boolean;
	/** The selection is empty (a caret). */
	collapsed: boolean;
}

export function toolbarState(editor: Editor): ToolbarState {
	const heading = ([1, 2, 3] as const).find((l) => editor.isActive(N.heading, { level: l })) ?? 0;
	return {
		bold: editor.isActive(M.bold),
		italic: editor.isActive(M.italic),
		link: editor.isActive(M.link),
		bulletList: editor.isActive(N.bulletList),
		orderedList: editor.isActive(N.orderedList),
		heading,
		canUndo: editor.can().undo(),
		canRedo: editor.can().redo(),
		collapsed: editor.state.selection.empty
	};
}

export function toggleMark(editor: Editor, mark: 'bold' | 'italic'): void {
	editor.chain().focus().toggleMark(mark).run();
}

export function toggleList(editor: Editor, list: 'bulletList' | 'orderedList'): void {
	if (list === 'bulletList') editor.chain().focus().toggleBulletList().run();
	else editor.chain().focus().toggleOrderedList().run();
}

export function setHeading(editor: Editor, level: 0 | 1 | 2 | 3): void {
	if (level === 0) editor.chain().focus().setParagraph().run();
	else editor.chain().focus().setHeading({ level }).run();
}

export function insertBreak(editor: Editor): void {
	editor.chain().focus().setHardBreak().run();
}

export function clearFormatting(editor: Editor): void {
	editor.chain().focus().unsetAllMarks().clearNodes().run();
}

export function undo(editor: Editor): void {
	editor.chain().focus().undo().run();
}

export function redo(editor: Editor): void {
	editor.chain().focus().redo().run();
}

/** The link under the selection (or caret), and the selected text, for the link dialog. */
export function currentLink(editor: Editor): { href: string; text: string } {
	const href = String(editor.getAttributes(M.link).href ?? '');
	const { from, to } = editor.state.selection;
	return { href, text: editor.state.doc.textBetween(from, to, ' ', ' ') };
}

/**
 * Apply a link: to the selection (extended over the existing link), or, with a collapsed
 * caret outside a link, by inserting `text` as a new link.
 */
export function applyLink(editor: Editor, href: string, text: string): void {
	const chain = editor.chain().focus();
	if (editor.state.selection.empty && !editor.isActive(M.link)) {
		if (!text) return;
		chain.insertContent({ type: N.text, text, marks: [{ type: M.link, attrs: { href } }] }).run();
		return;
	}
	chain.extendMarkRange(M.link).setMark(M.link, { href }).run();
}

export function removeLink(editor: Editor): void {
	editor.chain().focus().extendMarkRange(M.link).unsetMark(M.link).run();
}

/** Insert a chip, replacing `range` (the typed `${`) when given. */
export function insertPipe(editor: Editor, id: string, range?: Range | null): void {
	const node = { type: N.pipe, attrs: { id } };
	const chain = editor.chain().focus();
	if (range) chain.deleteRange(range).insertContentAt(range.from, node).run();
	else chain.insertContent(node).run();
}

/**
 * Put the caret where the researcher clicked on the read-only view (else at the end) and
 * focus the editor now. Synchronous on purpose: Tiptap's own `focus()` waits for an
 * animation frame, during which a Tab that just landed on the field would find nothing
 * focused and move on.
 */
export function placeCaret(editor: Editor, point: { x: number; y: number } | null): void {
	const { doc } = editor.state;
	let selection = Selection.atEnd(doc);
	if (point) {
		const at = editor.view.posAtCoords({ left: point.x, top: point.y });
		if (at) selection = TextSelection.near(doc.resolve(at.pos));
	}
	editor.view.dispatch(editor.state.tr.setSelection(selection).scrollIntoView());
	editor.view.focus();
}
