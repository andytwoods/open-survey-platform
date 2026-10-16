// Participant question widgets (runtime-design §6, §8). Import from '@osp/ui-components/survey'.
// Every widget takes QuestionProps<V> (types.ts) and reports edits through onchange(value).
// Render <Announcer /> once on the page so revealed questions are announced.
export { default as QuestionFrame } from './QuestionFrame.svelte';
export type { FrameContext, FrameKind } from './QuestionFrame.svelte';
export { default as RichText } from './RichText.svelte';
export { default as IntegerInput } from './IntegerInput.svelte';
export { default as DecimalInput } from './DecimalInput.svelte';
export { default as TextInput } from './TextInput.svelte';
export { default as SingleChoice } from './SingleChoice.svelte';
export { default as MultiChoice } from './MultiChoice.svelte';
export { default as DateInput } from './DateInput.svelte';
export { default as Note } from './Note.svelte';
export { default as Matrix } from './Matrix.svelte';
export { default as Slider } from './Slider.svelte';
export * from './types';
export { defaultMessages, dirFor, plainText } from './locale';
