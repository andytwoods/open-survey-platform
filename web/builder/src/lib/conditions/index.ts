// Condition builder (builder-design §3, task B7): "show this question if…".
//   <ConditionBuilder {questions} value={q.showIf} target={q.id} {surveyId}
//       service={apiExpressionService(api)} onOps={(ops) => client.apply(ops)} />
// or the same props on <ConditionDialog bind:open … /> for the property panel.
export { default as ConditionBuilder } from './ConditionBuilder.svelte';
export { default as ConditionDialog } from './ConditionDialog.svelte';
export { apiExpressionService } from './service';
export type { ExpressionService, ParseRequest, ParseResult, PrintResult } from './service';
export { questionsFromSurvey, textOf } from './questions';
export { operatorsForType, operatorsForRow, type OperatorDef, type ValueKind } from './operators';
export { astToTree, treeToAst, type FromAst, type ToAst } from './tree';
export { treeWarnings, requireAnswered, type RowWarning } from './warnings';
export * from './types';
