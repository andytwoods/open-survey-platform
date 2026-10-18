/**
 * Helpers for jsdom tests of the rich-text field: activate a field (the editor chunk is a
 * dynamic import, so activation is asynchronous) and reach the Tiptap editor behind its
 * contenteditable (Tiptap keeps the instance on the element as `editor`). Tests drive
 * edits through the editor's commands: jsdom cannot type into a contenteditable.
 */
import { tick } from 'svelte';
import { vi } from 'vitest';
import type { Editor } from './tiptap';

// jsdom has no ResizeObserver (the toolbar watches its width) and no caret geometry
// (ProseMirror asks a Range for its rectangles when it scrolls the selection into view).
globalThis.ResizeObserver ??= class {
	observe() {}
	unobserve() {}
	disconnect() {}
} as unknown as typeof ResizeObserver;
const noRects = () => Object.assign([] as DOMRect[], { item: () => null }) as unknown as DOMRectList;
const zeroRect = () => ({ x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, toJSON: () => ({}) }) as DOMRect;
if (typeof Range !== 'undefined') {
	Range.prototype.getClientRects ??= noRects;
	Range.prototype.getBoundingClientRect ??= zeroRect;
}
if (typeof Element !== 'undefined') {
	Element.prototype.getClientRects ??= noRects;
	Element.prototype.scrollIntoView ??= () => {};
}

/** The contenteditable of an active field, by the field's id. */
export function editable(id: string): HTMLElement | null {
	return document.querySelector<HTMLElement>(`#${CSS.escape(id)}[contenteditable]`);
}

/** The Tiptap editor behind an active field. */
export function editorOf(id: string): Editor {
	const el = editable(id) as (HTMLElement & { editor?: Editor }) | null;
	if (!el?.editor) throw new Error(`field ${id} is not active`);
	return el.editor;
}

/** Focus the idle field (or any element of it) and wait until the editor has mounted. */
export async function activate(el: HTMLElement): Promise<Editor> {
	const id = el.id;
	el.focus();
	await vi.dynamicImportSettled();
	for (let i = 0; i < 20 && !editable(id); i++) await tick();
	// Tiptap focuses the editor on the next animation frame.
	for (let i = 0; i < 20 && document.activeElement !== editable(id); i++) await wait(5);
	return editorOf(id);
}

/** Replace the field's text through the editor, as typing would (the buffer starts). */
export async function typeInto(editor: Editor, text: string): Promise<void> {
	editor.commands.setContent(text === '' ? '<p></p>' : `<p>${text}</p>`, { emitUpdate: true });
	await tick();
}

/** Real milliseconds (for tests on real timers). */
export const wait = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

/**
 * Focus leaves the field towards nothing: the field commits and returns to its read-only
 * view on the next macrotask (it defers, in case focus is moving into one of its dialogs).
 */
export async function blurField(id: string, settle: () => Promise<void> = () => wait(5)): Promise<void> {
	const el = editable(id);
	el?.blur();
	el?.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: null }));
	await settle();
	await tick();
}
