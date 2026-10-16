// Choice list editor (builder-design §3, task B6).
//
//   const inputs = editorInputs(store.survey, questionId);
//   <ChoiceListDialog bind:open question={inputs.question} choiceLists={inputs.choiceLists}
//     usage={inputs.usage} pointer={inputs.pointer} lang defaultLanguage={inputs.defaultLanguage}
//     publishedVersions diagnostics onOps={(ops) => store.submit(ops)} />
//
// Every gesture calls `onOps` once with the ops of one transaction.
export { default as ChoiceListEditor } from './ChoiceListEditor.svelte';
export { default as ChoiceListDialog } from './ChoiceListDialog.svelte';
export * from './model';
export * from './ops';
export { parsePaste, pasteOps, MAX_PASTE } from './paste';
export type { PasteMode, PastePreview, PastedRow } from './paste';
export { dropIndex, dropSlot, keyMoveTarget } from './reorder';
