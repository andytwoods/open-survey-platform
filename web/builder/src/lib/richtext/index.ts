// Rich text in the builder (planning/rich-text.md §9, task RT3): the edit-on-focus editor
// over Tiptap (loaded lazily on first focus; `@tiptap/*` is imported only inside this
// folder), the read-only renderer the cards use, and the pure helpers behind them.
export { default as RichTextEditor } from './RichTextEditor.svelte';
export { default as RichView } from './RichView.svelte';
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
