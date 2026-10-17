/**
 * The question types a researcher can pick, as the type picker shows them: a plain name,
 * a one-line description and an icon. The ids are osp-ops' `QuestionType`; what each type
 * does lives in the survey model and the ops, never here.
 */
import type { LucideIcon } from '@lucide/svelte';
import Calendar from '@lucide/svelte/icons/calendar';
import CircleDot from '@lucide/svelte/icons/circle-dot';
import DecimalsArrowRight from '@lucide/svelte/icons/decimals-arrow-right';
import Grid3x3 from '@lucide/svelte/icons/grid-3x3';
import Hash from '@lucide/svelte/icons/hash';
import SlidersHorizontal from '@lucide/svelte/icons/sliders-horizontal';
import SquareCheckBig from '@lucide/svelte/icons/square-check-big';
import StickyNote from '@lucide/svelte/icons/sticky-note';
import TextCursorInput from '@lucide/svelte/icons/text-cursor-input';

export type QuestionTypeId = 'text' | 'integer' | 'decimal' | 'single' | 'multi' | 'date' | 'matrix' | 'slider' | 'note';

export interface QuestionTypeInfo {
	id: QuestionTypeId;
	/** Plain name, e.g. "Single choice". */
	name: string;
	/** One line: what the participant does. */
	description: string;
	/** Extra words the filter matches (e.g. "radio", "checkbox", "likert"). */
	keywords: readonly string[];
	icon: LucideIcon;
}

export const QUESTION_TYPES: readonly QuestionTypeInfo[] = [
	{
		id: 'text',
		name: 'Text',
		description: 'A typed answer: a word, a sentence or a paragraph.',
		keywords: ['open', 'free text', 'string', 'essay', 'comment'],
		icon: TextCursorInput
	},
	{
		id: 'integer',
		name: 'Whole number',
		description: 'A number without decimals, such as an age or a count.',
		keywords: ['integer', 'number', 'numeric', 'count', 'age'],
		icon: Hash
	},
	{
		id: 'decimal',
		name: 'Decimal number',
		description: 'A number that may have decimals, such as a weight.',
		keywords: ['decimal', 'number', 'numeric', 'float', 'fraction'],
		icon: DecimalsArrowRight
	},
	{
		id: 'single',
		name: 'Single choice',
		description: 'Pick one option from a list.',
		keywords: ['radio', 'one', 'select', 'dropdown', 'yes no', 'likert'],
		icon: CircleDot
	},
	{
		id: 'multi',
		name: 'Multiple choice',
		description: 'Tick all the options that apply.',
		keywords: ['checkbox', 'checkboxes', 'many', 'select all'],
		icon: SquareCheckBig
	},
	{
		id: 'date',
		name: 'Date',
		description: 'A calendar date.',
		keywords: ['day', 'calendar', 'when', 'birthday'],
		icon: Calendar
	},
	{
		id: 'matrix',
		name: 'Grid',
		description: 'Rows of statements, each rated on the same columns.',
		keywords: ['matrix', 'table', 'likert', 'rows', 'scale'],
		icon: Grid3x3
	},
	{
		id: 'slider',
		name: 'Slider',
		description: 'Pick a number by dragging along a track.',
		keywords: ['range', 'scale', 'visual analogue', 'vas', 'rating'],
		icon: SlidersHorizontal
	},
	{
		id: 'note',
		name: 'Note',
		description: 'Display text for participants; nothing to answer.',
		keywords: ['text block', 'instructions', 'information', 'display', 'heading'],
		icon: StickyNote
	}
];

const BY_ID = new Map(QUESTION_TYPES.map((t) => [t.id, t]));

export function isQuestionType(v: unknown): v is QuestionTypeId {
	return typeof v === 'string' && BY_ID.has(v as QuestionTypeId);
}

export function questionTypeInfo(id: string | undefined): QuestionTypeInfo | undefined {
	return isQuestionType(id) ? BY_ID.get(id) : undefined;
}

/** The catalogue with `first` (the last used type) moved to the top. */
export function orderTypes(first: QuestionTypeId | null | undefined): QuestionTypeInfo[] {
	const all = [...QUESTION_TYPES];
	const i = first ? all.findIndex((t) => t.id === first) : -1;
	if (i > 0) all.unshift(...all.splice(i, 1));
	return all;
}

/**
 * Types matching `query` (case-insensitive): every word must start a word of the name or
 * keywords, or appear in the id. Name matches come before keyword-only matches; an empty
 * query keeps every type in order.
 */
export function filterTypes(types: readonly QuestionTypeInfo[], query: string): QuestionTypeInfo[] {
	const words = query.toLowerCase().split(/\s+/).filter(Boolean);
	if (!words.length) return [...types];
	const starts = (hay: string, w: string) => hay.split(/[^a-z0-9]+/).some((part) => part.startsWith(w));
	const scored: { t: QuestionTypeInfo; score: number }[] = [];
	for (const t of types) {
		const name = t.name.toLowerCase();
		const extra = [t.id, ...t.keywords].join(' ').toLowerCase();
		let score = 0;
		let ok = true;
		for (const w of words) {
			if (starts(name, w)) score += 2;
			else if (starts(extra, w) || t.id.includes(w)) score += 1;
			else ok = false;
		}
		if (ok) scored.push({ t, score });
	}
	return scored.sort((a, b) => b.score - a.score).map((s) => s.t);
}

// -- last used type (per browser) -----------------------------------------------------

export const LAST_TYPE_KEY = 'osp.builder.lastQuestionType';

/** The last type this browser added, or null (storage may be unavailable or hold junk). */
export function lastUsedType(storage: Pick<Storage, 'getItem'> | undefined = safeStorage()): QuestionTypeId | null {
	try {
		const v = storage?.getItem(LAST_TYPE_KEY);
		return isQuestionType(v) ? v : null;
	} catch {
		return null;
	}
}

export function rememberType(id: QuestionTypeId, storage: Pick<Storage, 'setItem'> | undefined = safeStorage()) {
	try {
		storage?.setItem(LAST_TYPE_KEY, id);
	} catch {
		// Private mode or blocked storage: nothing to remember.
	}
}

function safeStorage(): Storage | undefined {
	try {
		return typeof localStorage === 'undefined' ? undefined : localStorage;
	} catch {
		return undefined;
	}
}
