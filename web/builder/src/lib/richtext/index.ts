// Rich text in the builder (planning/rich-text.md §9, task RT3): the edit-on-focus editor
// over Tiptap (a lazy chunk, preloaded when the builder is idle; `@tiptap/*` is imported
// only inside this folder), the read-only renderer the cards use, and the pure helpers.
export { default as RichTextEditor } from './RichTextEditor.svelte';
export { default as RichView } from './RichView.svelte';
export { preloadEditorWhenIdle } from './load';
export { LIMITS, LEVELS, allows, isLevel, type Level } from './levels';
export {
	asRich,
	canonical,
	fromDoc,
	isEmptyValue,
	isPipeRef,
	normalForm,
	pipesOf,
	plainToRich,
	sameValue,
	toDoc,
	type PmNode,
	type RichValue
} from './convert';
export { BUILTIN_PIPES, ENDING_PIPES, flaggedPipes, pipeCandidates, pipeProblems, type PipeCandidate, type PipeGroup } from './pipes';
export { cleanPastedHtml, describeReport, type PasteReport } from './paste';
