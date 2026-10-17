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
	| '$device';

/** Researcher text (sanitised at save), or a pipe the engine fills (escaped at render). */
export type Segment = string | { pipe: Id | BuiltinRef };
/** Segments per language. Every survey language is present. */
export type Text = Record<LanguageTag, Segment[]>;

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
export type FlowNode =
	| BlockNode
	| BranchNode
	| RandomiserNode
	| AssignNode
	| QuotaCheckNode
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
