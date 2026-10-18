/**
 * Runtime plan types (`osp-runtime-plan/1`). The JSON Schema is
 * `contract/runtime-plan.schema.json`; the compiler is
 * `python/osp-runtime/src/osp_runtime/plan.py`. Keep all three in step.
 */

export const PLAN_VERSION = 'osp-runtime-plan/1';
/** Major version of the engine API. A plan whose `engineVersion` differs is refused. */
export const ENGINE_VERSION = '1';

export type Id = string;
export type LanguageTag = string;
export type ChoiceValue = number | string;
export type Order = 'fixed' | 'shuffle';

/** Built-in `$` variables usable in piping and expressions (runtime-design.md §7a). */
export type BuiltinRef =
	| '$trial'
	| '$position.index'
	| '$position.of'
	| '$pagesDone'
	| '$language'
	| '$device'
	// Ending-only (end-of-survey plan §4.2, EN2): empty until the session ends.
	| '$session.id'
	| '$outcome'
	| '$response.id';

/**
 * Researcher text (plain: validated by osp-spec on every write and rendered as text nodes,
 * never as HTML), or a pipe the engine fills (escaped at render).
 */
export type Segment = string | { pipe: Id | BuiltinRef };

// --- Rich text (planning/rich-text.md §3, task RT2) ------------------------------------

export type Mark = 'b' | 'i';
/** A run of text with optional bold/italic marks, an https link and a language span. */
export interface TextRun {
	text: string;
	marks?: Mark[];
	href?: string;
	lang?: string;
}
/** One inline node: a text run, a pipe the engine fills, or a line break. */
export type InlineRun = TextRun | { pipe: Id | BuiltinRef } | { br: true };
/** One block: a paragraph, a heading (1–3, relative to the page) or a single-level list. */
export type RichBlock =
	| { type: 'p'; content: InlineRun[] }
	| { type: 'h'; level: 1 | 2 | 3; content: InlineRun[] }
	| { type: 'ul' | 'ol'; items: InlineRun[][] };

/**
 * Per language, every survey language present: segments for a plain string (unchanged
 * since R1, so plans compiled before RT2 still load), or blocks for a rich-text value.
 */
export type Text = Record<LanguageTag, Segment[] | RichBlock[]>;

export function isBlock(x: Segment | RichBlock): x is RichBlock {
	return typeof x === 'object' && x !== null && 'type' in x;
}

/** A text value as blocks: segments become one paragraph of runs. */
export function toBlocks(value: Segment[] | RichBlock[] | undefined | null): RichBlock[] {
	if (!value || value.length === 0) return [{ type: 'p', content: [] }];
	if (isBlock(value[0]!)) return value as RichBlock[];
	return [{ type: 'p', content: (value as Segment[]).map((s) => (typeof s === 'string' ? { text: s } : s)) }];
}

// --- Expressions: osp-expr AST JSON (python/osp-expr/src/osp_expr/ast.py) -------------

export type CompareOp = '==' | '!=' | '<' | '<=' | '>' | '>=';
export type ArithOp = '+' | '-' | '*' | '/';

export type RefExpr = { kind: 'ref'; id: string };
export type Expr =
	| { kind: 'int'; value: number | string } // text beyond ±(2^53 − 1)
	| { kind: 'decimal'; value: string }
	| { kind: 'text'; value: string }
	| { kind: 'bool'; value: boolean }
	| { kind: 'null' }
	| RefExpr
	| { kind: 'compare'; op: CompareOp; left: Expr; right: Expr }
	| { kind: 'arith'; op: ArithOp; left: Expr; right: Expr }
	| { kind: 'and'; args: Expr[] }
	| { kind: 'or'; args: Expr[] }
	| { kind: 'not'; arg: Expr }
	| { kind: 'answered'; ref: RefExpr }
	| { kind: 'contains'; ref: RefExpr; value: Expr }
	| { kind: 'if'; cond: Expr; then: Expr; else: Expr };

// --- Items, pages, blocks ------------------------------------------------------------

export type QuestionType = 'integer' | 'decimal' | 'text' | 'single' | 'multi' | 'date' | 'slider';
export type ItemType = QuestionType | 'note' | 'matrix';

export interface Choice {
	value: ChoiceValue;
	label: Text;
}

interface ItemBase {
	id: Id;
	page: Id;
	label: Text;
	help?: Text;
	showIf?: Expr;
}

export interface NoteItem extends ItemBase {
	type: 'note';
}

/**
 * A matrix (semantics.md §2, C2c-1): display only. It stores no value; each of its `rows`
 * is a `single` question item of its own (`<matrix id>_<row id>`, with `matrix` set), in
 * `questions`, relevant exactly when the matrix is. The page lists the matrix, not its rows.
 */
export interface MatrixItem extends ItemBase {
	type: 'matrix';
	/** Export-name prefix of the rows. */
	name: string;
	required: boolean;
	/** Row question ids, in display order. */
	rows: Id[];
	/** The columns, shared by every row. */
	choices: Choice[];
}

export interface QuestionItem extends ItemBase {
	type: QuestionType;
	/** Export variable name (defaults to the id). */
	name: string;
	required: boolean;
	constraint?: Expr;
	constraintMessage?: Text;
	/** Present for `single` and `multi`. */
	choices?: Choice[];
	choiceOrder?: Order;
	/** Inclusive bounds for `integer`, `slider` (integers) and `decimal` (integers or decimal text). */
	min?: number | string;
	max?: number | string;
	/** `text` only: long text (a multi-line field that keeps line breaks, semantics §2). */
	multiline?: boolean;
	/** A matrix row: the matrix item it belongs to (its relevance is the matrix's). */
	matrix?: Id;
	/** `slider` only: stored as an integer or a canonical decimal; answers are min + k·step. */
	valueType?: 'integer' | 'decimal';
	step?: number | string;
	minLabel?: Text;
	maxLabel?: Text;
}

export type Item = NoteItem | MatrixItem | QuestionItem;

export interface Page {
	id: Id;
	block: Id;
	items: Id[];
	itemOrder: Order;
	/** Page-level display logic: when false the page is skipped and its items are irrelevant. */
	showIf?: Expr;
}

export interface Block {
	id: Id;
	pages: Id[];
}

// --- Variables and quotas ------------------------------------------------------------

export interface EmbeddedVariable {
	id: Id;
	kind: 'embedded';
	name: string;
	valueType: 'text' | 'integer' | 'decimal';
	source: 'url';
	param: string;
	default: string | number | null;
}

export interface AssignedVariable {
	id: Id;
	kind: 'assigned';
	name: string;
	levels: ChoiceValue[];
	/** node_id for the seeded draw (`<assign node>/<variable>`); same as RuntimeConfig's seedNode. */
	seedNode: string;
}

export interface ComputedVariable {
	id: Id;
	kind: 'computed';
	name: string;
	expr: Expr;
}

/**
 * A variable only researcher hooks set (task R7, runtime-design.md §7a): `setVariable` from a
 * hook writes it, conditions and pipes read it. Null until a hook sets it.
 * NOTE (R7): not yet in contract/runtime-plan.schema.json or the Python plan compiler.
 */
export interface HookVariable {
	id: Id;
	kind: 'hook';
	name: string;
	valueType: 'text' | 'integer' | 'decimal' | 'boolean';
}

export type Variable = EmbeddedVariable | AssignedVariable | ComputedVariable | HookVariable;

export interface Quota {
	id: Id;
	when: Expr;
	limit: number;
	countOn: 'complete';
	onFull: { block: Id | null; pages: Id[]; outcome: Id };
}

// --- Flow ----------------------------------------------------------------------------

export interface BlockNode {
	type: 'block';
	id: Id;
	block: Id;
	pages: Id[];
}
export interface BranchNode {
	type: 'branch';
	id: Id;
	if: Expr;
	then: FlowNode[];
	else: FlowNode[];
}
export interface RandomiserNode {
	type: 'randomiser';
	id: Id;
	children: FlowNode[];
	pick: number | null;
}
export interface AssignNode {
	type: 'assign';
	id: Id;
	variables: Id[];
}
export interface QuotaCheckNode {
	type: 'quotaCheck';
	id: Id;
	quota: Id;
}
export interface EndNode {
	type: 'end';
	id: Id;
	outcome: Id;
	message?: Text;
}
/**
 * An external-task hop (task EX2, planning/external-tasks.md): the participant goes to
 * `template` filled with `params` (the redirect-template machinery) plus the platform's
 * `osp_return` and `osp_token`, does the task, and returns. The values named in `returns`
 * are captured into the session's URL parameters (each into the embedded variable whose
 * `param` matches), exactly as a start-time URL parameter is.
 */
export interface ExternalTaskNode {
	type: 'externalTask';
	id: Id;
	template: string;
	params: Record<string, Segment[]>;
	returns: Array<{ variable: Id; param: string }>;
}
export type FlowNode =
	| BlockNode
	| BranchNode
	| RandomiserNode
	| AssignNode
	| QuotaCheckNode
	| ExternalTaskNode
	| EndNode;

/**
 * The consent page (semantics.md §11): shown before the flow, at most once. `version` is
 * the checksum of the compiled texts; a decline ends with `declineOutcome` and records
 * no response.
 */
export interface ConsentPlan {
	version: string;
	text: Text;
	agree: Text;
	decline: Text;
	declineOutcome: Id;
	countDeclines: boolean;
}

/**
 * The ending screen of one outcome (end-of-survey plan §4.1, osp-survey `settings.endings`).
 * `title` and `body` pipe like labels; absent means the app's own default. `status: auto`
 * shows the app's truthful status line, `none` hides it (a decline always shows it).
 * `summary: answers` lists the participant's answers under the body (§4.4, task EN5;
 * `answerSummary`).
 */
export interface EndingPlan {
	title?: Text;
	body?: Text;
	status: 'auto' | 'none';
	summary: 'none' | 'answers';
	/** Where the participant is sent after the submit is acknowledged (§4.2, EN2). */
	redirect?: EndRedirectPlan;
}

/**
 * An ending's redirect (end-of-survey plan §4.2): a template name from `redirectTemplates`,
 * one value per placeholder as segments (literal text and pipes, filled like labels, then
 * pattern-checked and encoded by `redirect.ts`), the delay before the automatic navigation
 * (`0`: at once, no screen), `auto` (countdown, "Stay on this page" cancels) or `link`
 * (the participant clicks), and the button label (absent: the app's "Continue to {host}").
 */
export interface EndRedirectPlan {
	template: string;
	params: Record<string, Segment[]>;
	delay: number;
	mode: 'auto' | 'link';
	label?: Text;
}

/**
 * A redirect template (osp-survey `settings.redirectTemplates` / `hooks.redirects`): an
 * absolute https URL with `{name}` placeholders after the origin, each with the pattern its
 * value must match in full (default `redirect.ts` DEFAULT_PARAM_PATTERN).
 */
export interface RedirectTemplatePlan {
	url: string;
	params: Record<string, { pattern?: string }>;
}

/** The page id the view reports while the consent page is shown (the `$` namespace is reserved). */
export const CONSENT_PAGE = '$consent';

// --- Plan ----------------------------------------------------------------------------

export interface Plan {
	planVersion: typeof PLAN_VERSION;
	engineVersion: string;
	/** `sha256:<hex>` of the canonical JSON of the plan without this field. */
	checksum: string;
	survey: {
		id: Id;
		version: number | null;
		specVersion: string;
		/** The `surveyVersion` string fed to node_seed (semantics.md §7, R1-1). */
		seedVersion: string;
	};
	languages: LanguageTag[];
	defaultLanguage: LanguageTag;
	title: Text;
	settings: {
		backNavigation: boolean;
		/** `every-page`: autosave to the server; `end-only`: nothing until submit (runtime-design §5.0). */
		saveMode: 'every-page' | 'end-only';
		/** Where an `end-only` session keeps its copy; `memory` restarts on refresh (semantics.md §5). */
		localCopy: 'browser' | 'memory';
		/** Days of inactivity after which a resume link stops working. */
		resumeExpiryDays: number;
	};
	/** Optional consent page, shown before any question (semantics.md §11). */
	consent?: ConsentPlan;
	/** Ending screens keyed by outcome; absent when the survey sets none (inside the checksum). */
	endings?: Record<Id, EndingPlan>;
	/** Redirect templates endings and hooks may name; absent when there are none (inside the checksum). */
	redirectTemplates?: Record<string, RedirectTemplatePlan>;
	items: Record<Id, Item>;
	/** Answerable question ids in flow order (export column order). */
	questions: Id[];
	pages: Record<Id, Page>;
	blocks: Record<Id, Block>;
	variables: Record<Id, Variable>;
	quotas: Record<Id, Quota>;
	flow: FlowNode[];
	/**
	 * Researcher hooks declared at publish (runtime-design.md §7a): the `osp-hooks/1`
	 * manifest (`web/hooks-sandbox` HookManifest). Opaque to the engine, but part of the plan
	 * and so of its checksum. Absent when the survey runs no custom code.
	 */
	hooks?: PlanHooks;
}

export interface PlanHooks {
	format: 'osp-hooks/1';
	source: string;
	handlers: Record<string, { reads: Id[]; writes: Id[]; timeoutMs?: number }>;
	[key: string]: unknown;
}

/** An item that stores a value (not a note, not a matrix: a matrix's rows are questions). */
export function isQuestion(item: Item): item is QuestionItem {
	return item.type !== 'note' && item.type !== 'matrix';
}

export function isMatrix(item: Item | undefined): item is MatrixItem {
	return item?.type === 'matrix';
}

/** The value type a question stores and expressions see: a slider's `valueType`, else its type. */
export function valueTypeOf(item: QuestionItem): Exclude<QuestionType, 'slider'> {
	return item.type === 'slider' ? (item.valueType ?? 'integer') : item.type;
}
