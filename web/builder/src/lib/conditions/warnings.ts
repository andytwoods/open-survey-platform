/**
 * Builder warnings on a condition tree (task B7):
 *
 * - `unknown-question`: a row refers to a question that is not in the survey (deleted).
 * - server diagnostics that name a question (`ref.forward`, `ref.unknown`, …) are pinned
 *   to the rows that use it.
 * - `may-be-unanswered` (decision C1-2, two-valued logic): `not null` is true, so a row whose
 *   effective test is negated ("excludes", or anything inside "None of") is **true** for a
 *   participant who skipped the question. Offer "also require answered", which adds
 *   `answered(q)` alongside. `is not` compiles to `!=`, which is already false when
 *   unanswered, so it needs no warning.
 *
 * "May be unanswered" is a builder hint: a question is assumed answerable-empty unless it is
 * required and has no display condition of its own.
 */
import { findNode, newGroup, newRow } from './tree';
import type { CondNode, ExprDiagnostic, GroupNode, QuestionInfo, RowNode } from './types';

export type WarningKind = 'unknown-question' | 'server' | 'may-be-unanswered';

export interface RowWarning {
	kind: WarningKind;
	rowKey: string;
	question: string;
	message: string;
	code?: string;
	/** For `may-be-unanswered`: the node to guard with `answered(question)`. */
	fixKey?: string;
}

export function mayBeUnanswered(q: QuestionInfo | undefined): boolean {
	return !q || !q.required || q.conditional;
}

/** Ids a row uses: its question and a question it is compared with. */
export function rowRefs(row: RowNode): string[] {
	const out = row.question ? [row.question] : [];
	if (row.value?.kind === 'ref' && typeof row.value.id === 'string') out.push(row.value.id);
	return out;
}

interface Frame {
	node: CondNode;
	/** Ancestors from the root down (groups). */
	path: GroupNode[];
	/** True when an odd number of "None of" groups enclose the node. */
	negated: boolean;
}

function* walk(root: GroupNode): Generator<Frame> {
	const stack: Frame[] = [{ node: root, path: [], negated: false }];
	while (stack.length) {
		const f = stack.pop() as Frame;
		yield f;
		if (f.node.kind === 'group') {
			const g = f.node;
			const negated = g.mode === 'none' ? !f.negated : f.negated;
			for (let i = g.children.length - 1; i >= 0; i--) {
				stack.push({ node: g.children[i], path: [...f.path, g], negated });
			}
		}
	}
}

/** True if `row` (effective polarity `negated`) is true for an unanswered question. */
function trueWhenUnanswered(row: RowNode, negated: boolean): boolean {
	if (!row.op) return false;
	if (!negated) return row.op === 'not_contains';
	// Negated: not(test). Only tests that are false on null become true; "not answered"
	// inside "None of" is the deliberate "is answered" and is never a surprise.
	return row.op !== 'answered' && row.op !== 'not_contains' && row.op !== 'not_answered';
}

function isAnsweredRow(n: CondNode, q: string): boolean {
	return n.kind === 'row' && n.op === 'answered' && n.question === q;
}

/**
 * The node to guard and whether it is already guarded. The guard target is the row itself
 * (positive polarity) or the outermost "None of" group that negates it.
 */
function guardFor(frame: Frame, q: string): { target: CondNode; guarded: boolean } {
	let target: CondNode = frame.node;
	let ancestors = frame.path;
	if (frame.negated) {
		// Climb to the outermost "None of" whose own context is not negated.
		let neg = false;
		for (let i = 0; i < frame.path.length; i++) {
			const g = frame.path[i];
			if (g.mode === 'none' && !neg) {
				target = g;
				ancestors = frame.path.slice(0, i);
				break;
			}
			if (g.mode === 'none') neg = !neg;
		}
	}
	// Guarded if an "All of" ancestor in a non-negated context has `answered(q)` as a child.
	let guarded = false;
	for (let i = ancestors.length - 1; i >= 0; i--) {
		const g = ancestors[i];
		if (g.mode === 'none') break;
		if (g.mode === 'all' && g.children.some((c) => isAnsweredRow(c, q))) {
			guarded = true;
			break;
		}
	}
	return { target, guarded };
}

export function treeWarnings(
	root: GroupNode,
	questions: ReadonlyMap<string, QuestionInfo>,
	diagnostics: readonly ExprDiagnostic[] = []
): RowWarning[] {
	const out: RowWarning[] = [];
	const byQuestion = new Map<string, ExprDiagnostic[]>();
	for (const d of diagnostics) {
		if (!d.questionId) continue;
		byQuestion.set(d.questionId, [...(byQuestion.get(d.questionId) ?? []), d]);
	}
	for (const frame of walk(root)) {
		if (frame.node.kind !== 'row') continue;
		const row = frame.node;
		for (const id of rowRefs(row)) {
			const known = questions.has(id);
			if (!known) {
				out.push({
					kind: 'unknown-question',
					rowKey: row.key,
					question: id,
					message: `Question “${id}” no longer exists. Choose another question or remove this row.`
				});
			}
			for (const d of byQuestion.get(id) ?? []) {
				if (!known && (d.code === 'ref.unknown' || d.code === 'unknown-question')) continue;
				out.push({ kind: 'server', rowKey: row.key, question: id, message: d.message, code: d.code });
			}
		}
		const q = row.question;
		if (q && questions.has(q) && trueWhenUnanswered(row, frame.negated) && mayBeUnanswered(questions.get(q))) {
			const { target, guarded } = guardFor(frame, q);
			if (!guarded) {
				out.push({
					kind: 'may-be-unanswered',
					rowKey: row.key,
					question: q,
					fixKey: target.key,
					message: `This is also true for someone who did not answer “${q}”.`
				});
			}
		}
	}
	return out;
}

/**
 * "Also require answered": put `answered(question)` next to the node `fixKey`, in an
 * "All of" group (the node's own parent if it is one, else a new group around the node).
 * Returns the new root (it changes when the root itself is wrapped).
 */
export function requireAnswered(root: GroupNode, fixKey: string, question: string): GroupNode {
	const found = findNode(root, fixKey);
	if (!found) return root;
	const guard = newRow(question, 'answered');
	const { node, parent } = found;
	if (!parent) return newGroup('all', [guard, node]);
	const i = parent.children.indexOf(node);
	if (parent.mode === 'all') {
		parent.children.splice(i, 0, guard);
	} else {
		parent.children.splice(i, 1, newGroup('all', [guard, node]));
	}
	return root;
}
