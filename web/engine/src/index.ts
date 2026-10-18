/**
 * @osp/engine: the participant engine (runtime-design.md §3). Pure TypeScript: no DOM, no
 * I/O, no Math.random, no Date.now. The runtime app, the builder preview, the debugger and
 * the simulator all run this.
 */

export * from './plan.ts';
export * from './types.ts';
export * from './redirect.ts';
export * from './richtext.ts';
export {
	agree,
	answer,
	answers,
	answerSummary,
	awaitingConsent,
	decline,
	declinedConsent,
	endRedirect,
	tryConsent,
	back,
	canGoBack,
	checkPlan,
	context,
	escapeHtml,
	HOOK_FAILED_OUTCOME,
	isState,
	next,
	replay,
	resolve,
	restart,
	restore,
	result,
	setLanguage,
	snapshot,
	start,
	toHtml,
	toPlain,
	valueText,
	tryAnswer,
	tryBack,
	tryResolve,
	view,
	withChecksum,
	withResponseId,
	type Rejection
} from './engine.ts';
export {
	evaluate,
	evaluateCondition,
	type DiagnosticSink,
	type ExprDiagnostic,
	type Value,
	type Lookup
} from './expr.ts';
export { canonicalJson, planChecksum } from './canonical.ts';
export {
	assign,
	checkSeed,
	InvalidSeedError,
	MAX_SEED,
	NODE_SEED_MAX,
	NODE_SEED_TAG,
	nodeSeed,
	permuteRaw,
	randomize,
	RandomInputError
} from './random.ts';
export { sha256, toHex, utf8 } from './sha256.ts';
export {
	canonicalDecimal,
	checkAnswer,
	DECIMAL_DIGITS,
	pyStrip,
	trimAnswer,
	TRIM_CODE_POINTS,
	type Stored
} from './values.ts';
export { DECIMAL_PRECISION } from './decimal.ts';
// Plan compile in the browser (task CE3): byte-identical to osp_runtime.plan.
export {
	blocks,
	checksum,
	compilePlan,
	compileSurvey,
	consentVersion,
	embedTheme,
	exprJson,
	PlanError,
	pyDecimalText,
	runtimeConfig,
	seedNode,
	seedVersion,
	segments,
	type CompileOptions,
	type PlanDiagnostic,
	type RuntimeConfigJson,
	type SurveyValidator
} from './compile.ts';
// Expression text syntax (task CE1): identical to osp_expr.syntax.
export {
	codePointToUtf16,
	EXPR_FUNCTIONS,
	EXPR_KEYWORDS,
	EXPR_MAX_DEPTH,
	EXPR_MAX_INT_DIGITS,
	exprToText,
	parseExpr,
	type ParseResult,
	type SyntaxDiagnostic
} from './syntax.ts';
