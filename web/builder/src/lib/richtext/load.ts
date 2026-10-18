/**
 * The editor chunk (./tiptap) behind every rich-text field, fetched once (RT7). A field
 * waits for it on focus; preloading it when the builder is idle means a first focus seldom
 * waits at all. A failed fetch is forgotten, so the next focus tries again.
 */
export type EditorModule = typeof import('./tiptap');

let modulePromise: Promise<EditorModule> | null = null;

export function loadEditor(): Promise<EditorModule> {
	return (modulePromise ??= import('./tiptap').catch((e: unknown) => {
		modulePromise = null;
		throw e;
	}));
}

/** Start fetching the chunk now (e.g. the pointer went down on a field). */
export function preloadEditor(): void {
	loadEditor().catch(() => {});
}

let queued = false;

/** Fetch the chunk once the page is idle: call it where rich-text fields will soon appear. */
export function preloadEditorWhenIdle(): void {
	if (queued || modulePromise) return;
	queued = true;
	if (typeof requestIdleCallback === 'function') requestIdleCallback(preloadEditor, { timeout: 2000 });
	else setTimeout(preloadEditor, 200);
}
