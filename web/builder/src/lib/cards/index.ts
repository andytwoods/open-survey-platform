// Question cards for the builder canvas (builder-design §2, task B5).
// Use <QuestionCard {question} {schema} {selected} {diagnostics} onselect={...} />.
export { default as QuestionCard } from './QuestionCard.svelte';
export { default as ChoiceCard } from './ChoiceCard.svelte';
export { default as TextCard } from './TextCard.svelte';
export { default as NumberCard } from './NumberCard.svelte';
export { default as MatrixCard } from './MatrixCard.svelte';
export { default as ScaleCard } from './ScaleCard.svelte';
export { default as NoteCard } from './NoteCard.svelte';
export { CARDS, cardFor } from './dispatch';
export { badgesFor, exprToText, pipeSegments, resolveFamily, textFor } from './logic';
export * from './types';
