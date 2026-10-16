/**
 * Op builders for the choice list editor. Each returns the ops for one user gesture, which
 * the editor hands to `onOps` as one transaction (builder-design §4). An empty array means
 * "nothing to send" (a no-op or an invalid edit). Params follow `osp-ops` choice_ops.py
 * and choice_list_ops.py.
 */
import {
	codeShapeError,
	labelIn,
	parseCode,
	sameCode,
	withLabel,
	LIST_ID,
	type ChoiceCode,
	type ChoiceOp,
	type ChoiceQuestion,
	type SpecChoice
} from './model';

/** A deep copy that also works on Svelte state proxies. */
function clone<T>(v: T): T {
	return JSON.parse(JSON.stringify(v ?? null)) as T;
}

export interface LabelContext {
	lang?: string;
	defaultLanguage?: string;
}

/** Add a choice (the server picks the next integer code) at `index` (default: the end). */
export function addChoiceOps(owner: string, label = '', index?: number): ChoiceOp[] {
	const params: Record<string, unknown> = { owner, label };
	if (index !== undefined) params.index = index;
	return [{ op: 'add_choice', params }];
}

/** A copy of row `i` right below it, with a fresh code and the same label. */
export function duplicateChoiceOps(owner: string, choices: readonly SpecChoice[], i: number): ChoiceOp[] {
	const c = choices[i];
	if (!c) return [];
	return [{ op: 'add_choice', params: { owner, label: clone(c.label), index: i + 1 } }];
}

export function deleteChoiceOps(owner: string, choices: readonly SpecChoice[], i: number): ChoiceOp[] {
	const c = choices[i];
	if (!c || choices.length <= 1) return [];
	return [{ op: 'delete_choice', params: { owner, value: c.value } }];
}

/** Move row `from` so it ends up at `to` (both in the current order). */
export function moveChoiceOps(owner: string, choices: readonly SpecChoice[], from: number, to: number): ChoiceOp[] {
	const c = choices[from];
	if (!c || from === to || to < 0 || to >= choices.length) return [];
	return [{ op: 'move_choice', params: { owner, value: c.value, index: to } }];
}

/**
 * Change row `i`'s code to what the user typed. Nothing when the code is unchanged or
 * invalid (empty, whitespace, already used by another row).
 */
export function setCodeOps(owner: string, choices: readonly SpecChoice[], i: number, raw: string): ChoiceOp[] {
	const c = choices[i];
	if (!c || codeShapeError(raw)) return [];
	const next: ChoiceCode = parseCode(raw);
	if (sameCode(next, c.value)) return [];
	if (choices.some((o, j) => j !== i && sameCode(o.value, next))) return [];
	return [{ op: 'set_choice', params: { owner, value: c.value, new_value: next } }];
}

/** Change row `i`'s label in the editing language. Nothing when the text is unchanged. */
export function setLabelOps(
	owner: string,
	choices: readonly SpecChoice[],
	i: number,
	text: string,
	ctx: LabelContext = {}
): ChoiceOp[] {
	const c = choices[i];
	if (!c) return [];
	const key = ctx.lang ?? ctx.defaultLanguage;
	const has =
		typeof c.label === 'string' ||
		(key !== undefined && !!c.label && typeof c.label === 'object' && Object.hasOwn(c.label, key));
	if (has && labelIn(c.label, key) === text) return [];
	return [
		{ op: 'set_choice', params: { owner, value: c.value, label: withLabel(c.label, text, ctx.lang, ctx.defaultLanguage) } }
	];
}

// --- shared lists ---------------------------------------------------------------------

/** Point the question at shared list `listId` (dropping its inline choices, if any). */
export function useListOps(question: ChoiceQuestion, listId: string): ChoiceOp[] {
	if (!listId || question.choiceList === listId) return [];
	const ops: ChoiceOp[] = [{ op: 'set_property', params: { target: question.id, property: 'choiceList', value: listId } }];
	if (question.choices != null) ops.push({ op: 'set_property', params: { target: question.id, property: 'choices', unset: true } });
	return ops;
}

/** Turn the question's inline choices into a new shared list `listId` that it uses. */
export function makeSharedOps(question: ChoiceQuestion, listId: string): ChoiceOp[] {
	if (!LIST_ID.test(listId) || listId.length > 64 || !question.choices?.length) return [];
	return [
		{ op: 'create_choice_list', params: { id: listId, choices: clone(question.choices) } },
		...useListOps({ ...question, choiceList: null }, listId)
	];
}

/** Give the question its own copy of its shared list's choices (the list is kept). */
export function detachOps(question: ChoiceQuestion, choices: readonly SpecChoice[]): ChoiceOp[] {
	if (!question.choiceList || !choices.length) return [];
	return [
		{ op: 'set_property', params: { target: question.id, property: 'choices', value: clone(choices) } },
		{ op: 'set_property', params: { target: question.id, property: 'choiceList', unset: true } }
	];
}
