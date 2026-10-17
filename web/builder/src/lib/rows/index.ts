// Grid (matrix) rows editor (task B15), opened from the property panel's "Edit rows…".
//
//   const inputs = rowsEditorInputs(store.survey, questionId);
//   <RowsDialog bind:open question={inputs.question} pointer={inputs.pointer} lang
//     defaultLanguage={inputs.defaultLanguage} survey={store.survey} diagnostics
//     submit={(ops, o) => store.submit(ops, o)} />
//
// Every gesture calls `submit` once with the ops of one transaction.
export { default as RowsEditor } from './RowsEditor.svelte';
export { default as RowsDialog } from './RowsDialog.svelte';
export * from './model';
