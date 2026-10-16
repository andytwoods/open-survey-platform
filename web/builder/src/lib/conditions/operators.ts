/**
 * Which operators a question offers, by question type (task B7), and what value each needs.
 *
 * | type             | operators                                                      |
 * |------------------|----------------------------------------------------------------|
 * | integer, decimal | = ≠ < ≤ > ≥ (shown as words + symbol), is (not) answered        |
 * | single           | is, is not, is answered, is not answered                       |
 * | multi            | includes, excludes, is answered, is not answered               |
 * | text             | is, is empty, is answered                                      |
 * | date             | is on, is not on, before, on or before, after, on or after     |
 * |                  | (another date question: osp-expr has no date literal), answered|
 * | anything else    | is answered, is not answered                                   |
 */
import type { OperatorId, QuestionInfo } from './types';

/** What the value editor shows. */
export type ValueKind = 'none' | 'number' | 'choice' | 'text' | 'question';

export interface OperatorDef {
	id: OperatorId;
	label: string;
	value: ValueKind;
}

const COMPARE: Record<string, OperatorId> = {
	'==': 'eq',
	'!=': 'ne',
	'<': 'lt',
	'<=': 'le',
	'>': 'gt',
	'>=': 'ge'
};
export const COMPARE_OPS: Readonly<Record<string, OperatorId>> = COMPARE;
export const COMPARE_SYMBOL: Readonly<Partial<Record<OperatorId, string>>> = Object.fromEntries(
	Object.entries(COMPARE).map(([sym, id]) => [id, sym])
);

const ANSWERED: OperatorDef = { id: 'answered', label: 'is answered', value: 'none' };
const NOT_ANSWERED: OperatorDef = { id: 'not_answered', label: 'is not answered', value: 'none' };

// Words first (readable, and native-select type-ahead can reach them), symbol after.
const NUMBER: OperatorDef[] = [
	{ id: 'eq', label: 'equals (=)', value: 'number' },
	{ id: 'ne', label: 'does not equal (≠)', value: 'number' },
	{ id: 'lt', label: 'less than (<)', value: 'number' },
	{ id: 'le', label: 'at most (≤)', value: 'number' },
	{ id: 'gt', label: 'more than (>)', value: 'number' },
	{ id: 'ge', label: 'at least (≥)', value: 'number' },
	ANSWERED,
	NOT_ANSWERED
];

const BY_TYPE: Record<string, OperatorDef[]> = {
	integer: NUMBER,
	decimal: NUMBER,
	single: [
		{ id: 'eq', label: 'is', value: 'choice' },
		{ id: 'ne', label: 'is not', value: 'choice' },
		ANSWERED,
		NOT_ANSWERED
	],
	multi: [
		{ id: 'contains', label: 'includes', value: 'choice' },
		{ id: 'not_contains', label: 'excludes', value: 'choice' },
		ANSWERED,
		NOT_ANSWERED
	],
	text: [
		{ id: 'eq', label: 'is', value: 'text' },
		{ id: 'not_answered', label: 'is empty', value: 'none' },
		ANSWERED
	],
	date: [
		{ id: 'eq', label: 'is on the same day as', value: 'question' },
		{ id: 'ne', label: 'is not on the same day as', value: 'question' },
		{ id: 'lt', label: 'is before', value: 'question' },
		{ id: 'le', label: 'is on or before', value: 'question' },
		{ id: 'gt', label: 'is after', value: 'question' },
		{ id: 'ge', label: 'is on or after', value: 'question' },
		ANSWERED,
		NOT_ANSWERED
	]
};

const FALLBACK: OperatorDef[] = [ANSWERED, NOT_ANSWERED];

/** Generic labels, used for a row whose question is unknown (deleted) or of another type. */
const GENERIC: Record<OperatorId, OperatorDef> = {
	eq: { id: 'eq', label: 'equals (=)', value: 'text' },
	ne: { id: 'ne', label: 'does not equal (≠)', value: 'text' },
	lt: { id: 'lt', label: 'less than (<)', value: 'number' },
	le: { id: 'le', label: 'at most (≤)', value: 'number' },
	gt: { id: 'gt', label: 'more than (>)', value: 'number' },
	ge: { id: 'ge', label: 'at least (≥)', value: 'number' },
	contains: { id: 'contains', label: 'includes', value: 'text' },
	not_contains: { id: 'not_contains', label: 'excludes', value: 'text' },
	answered: ANSWERED,
	not_answered: NOT_ANSWERED
};

/** Operators offered for a question type (in display order). */
export function operatorsForType(type: string | undefined): OperatorDef[] {
	return (type !== undefined && BY_TYPE[type]) || FALLBACK;
}

/**
 * Operators to show for a row: those of its question's type, plus the row's current
 * operator if that type does not offer it (so a loaded condition is never silently changed).
 */
export function operatorsForRow(question: QuestionInfo | undefined, current: OperatorId | null): OperatorDef[] {
	const ops = question ? operatorsForType(question.type) : [];
	if (current && !ops.some((o) => o.id === current)) return [...ops, GENERIC[current]];
	return ops;
}

/** The definition for `op` on `question` (generic if the type does not offer it). */
export function operatorDef(question: QuestionInfo | undefined, op: OperatorId): OperatorDef {
	return operatorsForRow(question, op).find((o) => o.id === op) ?? GENERIC[op];
}

/** Questions a `question`-kind value may refer to: other questions of the same type. */
export function comparableQuestions(questions: readonly QuestionInfo[], row: QuestionInfo | undefined): QuestionInfo[] {
	return questions.filter((q) => q.id !== row?.id && (!row || q.type === row.type));
}
