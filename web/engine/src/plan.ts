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
	| { kind: 'int'; value: number }
	| { kind: 'decimal'; value: string }
	| { kind: 'text'; value: string }
	| { kind: 'null' }
	| RefExpr
	| { kind: 'compare'; op: CompareOp; left: Expr; right: Expr }
	| { kind: 'arith'; op: ArithOp; left: Expr; right: Expr }
	| { kind: 'and'; args: Expr[] }
	| { kind: 'or'; args: Expr[] }
	| { kind: 'not'; arg: Expr }
	| { kind: 'answered'; ref: RefExpr }
	| { kind: 'contains'; ref: RefExpr; value: Expr };

// --- Items, pages, blocks ------------------------------------------------------------

export type QuestionType = 'integer' | 'decimal' | 'text' | 'single' | 'multi' | 'date';
export type ItemType = QuestionType | 'note';

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
}

export type Item = NoteItem | QuestionItem;

export interface Page {
	id: Id;
	block: Id;
	items: Id[];
	itemOrder: Order;
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

export type Variable = EmbeddedVariable | AssignedVariable | ComputedVariable;

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
	settings: { backNavigation: boolean };
	items: Record<Id, Item>;
	/** Answerable question ids in flow order (export column order). */
	questions: Id[];
	pages: Record<Id, Page>;
	blocks: Record<Id, Block>;
	variables: Record<Id, Variable>;
	quotas: Record<Id, Quota>;
	flow: FlowNode[];
}

export function isQuestion(item: Item): item is QuestionItem {
	return item.type !== 'note';
}
