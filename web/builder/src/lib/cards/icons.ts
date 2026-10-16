// Card header icon: the schema's `icon` (a Lucide name) when known, else one per family.
import type { LucideIcon } from '@lucide/svelte';
import Calculator from '@lucide/svelte/icons/calculator';
import Calendar from '@lucide/svelte/icons/calendar';
import CircleDot from '@lucide/svelte/icons/circle-dot';
import CircleQuestionMark from '@lucide/svelte/icons/circle-question-mark';
import Grid3x3 from '@lucide/svelte/icons/grid-3x3';
import Hash from '@lucide/svelte/icons/hash';
import Info from '@lucide/svelte/icons/info';
import ListChecks from '@lucide/svelte/icons/list-checks';
import SlidersHorizontal from '@lucide/svelte/icons/sliders-horizontal';
import SquareCheck from '@lucide/svelte/icons/square-check';
import StickyNote from '@lucide/svelte/icons/sticky-note';
import TextCursorInput from '@lucide/svelte/icons/text-cursor-input';
import type { CardFamily } from './types';

const BY_NAME: Readonly<Record<string, LucideIcon>> = {
	calculator: Calculator,
	calendar: Calendar,
	'circle-dot': CircleDot,
	'grid-3x3': Grid3x3,
	hash: Hash,
	'list-checks': ListChecks,
	'sliders-horizontal': SlidersHorizontal,
	'square-check': SquareCheck,
	'sticky-note': StickyNote,
	'text-cursor-input': TextCursorInput
};

const BY_FAMILY: Readonly<Record<CardFamily, LucideIcon>> = {
	choice: ListChecks,
	text: TextCursorInput,
	number: Hash,
	matrix: Grid3x3,
	scale: SlidersHorizontal,
	note: Info
};

export function cardIcon(icon: unknown, family: CardFamily | null): LucideIcon {
	if (typeof icon === 'string' && Object.hasOwn(BY_NAME, icon)) return BY_NAME[icon];
	return family ? BY_FAMILY[family] : CircleQuestionMark;
}
