/**
 * Condition builder data (builder-design §3, task B7).
 *
 * The builder edits a **tree** of groups and rows. The tree is a view of an `osp-expr`
 * AST (JSON, `kind` discriminator): `tree.ts` converts both ways. Parsing and printing
 * text happen on the server (`/api/meta/expressions/parse` and `/print`), never here.
 */

/** One `osp-expr` AST node as JSON. Unknown kinds are tolerated (they fall back to text). */
export interface ExprNode {
	kind: string;
	[field: string]: unknown;
}

/** A choice as the builder shows it. */
export interface ChoiceInfo {
	value: string | number;
	label: string;
}

/** What the builder needs to know about a question it can refer to. */
export interface QuestionInfo {
	id: string;
	/** osp-spec question type: integer, decimal, text, single, multi, date (others tolerated). */
	type: string;
	label: string;
	choices: ChoiceInfo[];
	required: boolean;
	/** True if the question has its own display condition (so it may be skipped). */
	conditional: boolean;
}

/** All of = and, Any of = or, None of = not (a or b …). */
export type GroupMode = 'all' | 'any' | 'none';

export interface GroupNode {
	kind: 'group';
	key: string;
	mode: GroupMode;
	children: CondNode[];
}

/**
 * Operators are named after the AST shape they produce, not the label shown, so a row
 * round-trips even when its question has been deleted (and its type is unknown).
 */
export type OperatorId =
	| 'eq'
	| 'ne'
	| 'lt'
	| 'le'
	| 'gt'
	| 'ge'
	| 'contains'
	| 'not_contains'
	| 'answered'
	| 'not_answered';

export interface RowNode {
	kind: 'row';
	key: string;
	/** Question id ('' until picked). */
	question: string;
	op: OperatorId | null;
	/** Literal (`int`, `decimal`, `text`) or `ref` node; null until entered (or not needed). */
	value: ExprNode | null;
	/** What the user typed in a number/text input (kept while it is not a valid value). */
	draft?: string;
}

export type CondNode = GroupNode | RowNode;

/** A diagnostic from the expression endpoints (contract `ExprDiagnostic`). */
export interface ExprDiagnostic {
	code: string;
	message: string;
	severity?: 'error' | 'warning' | 'info';
	start?: number | null;
	end?: number | null;
	path?: string | null;
	questionId?: string | null;
}

/** One op emitted on Apply (`set_condition`). */
export interface ConditionOp {
	op: 'set_condition';
	params: {
		target: string;
		condition: ExprNode | null;
		field?: ConditionField;
	};
}

export type ConditionField = 'showIf' | 'constraint' | 'if' | 'when' | 'expr';
