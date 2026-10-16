/**
 * The questions a condition can refer to, read from survey JSON (osp-survey). Tolerant of
 * any input: a malformed survey gives fewer questions, never an exception.
 */
import type { ChoiceInfo, QuestionInfo } from './types';

type Json = Record<string, unknown>;

function obj(v: unknown): Json | null {
	return typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Json) : null;
}

function list(v: unknown): unknown[] {
	return Array.isArray(v) ? v : [];
}

/** Translatable text → one string (`lang`, then English, then the first language). */
export function textOf(v: unknown, lang = 'en'): string {
	if (typeof v === 'string') return v;
	const o = obj(v);
	if (!o) return '';
	const s = o[lang] ?? o.en ?? Object.values(o)[0];
	return typeof s === 'string' ? s : '';
}

function choices(raw: unknown, lang: string): ChoiceInfo[] {
	return list(raw)
		.map(obj)
		.filter((c): c is Json => !!c && (typeof c.value === 'string' || typeof c.value === 'number'))
		.map((c) => ({ value: c.value as string | number, label: textOf(c.label, lang) || String(c.value) }));
}

/** Every question with a value (notes are left out), in document order. */
export function questionsFromSurvey(survey: unknown, lang = 'en'): QuestionInfo[] {
	const s = obj(survey);
	if (!s) return [];
	const lists = new Map<string, unknown>();
	for (const cl of list(s.choiceLists).map(obj)) {
		if (cl && typeof cl.id === 'string') lists.set(cl.id, cl.choices);
	}
	const out: QuestionInfo[] = [];
	for (const block of list(s.blocks).map(obj)) {
		for (const page of list(block?.pages).map(obj)) {
			for (const q of list(page?.items).map(obj)) {
				if (!q || typeof q.id !== 'string' || typeof q.type !== 'string' || q.type === 'note') continue;
				const raw = q.choices ?? (typeof q.choiceList === 'string' ? lists.get(q.choiceList) : undefined);
				out.push({
					id: q.id,
					type: q.type,
					label: textOf(q.label, lang),
					choices: choices(raw, lang),
					required: q.required === true,
					conditional: q.showIf !== undefined && q.showIf !== null
				});
			}
		}
	}
	return out;
}
