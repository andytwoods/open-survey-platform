// Family → card component. QuestionCard.svelte renders whatever this returns.
import type { Component } from 'svelte';
import ChoiceCard from './ChoiceCard.svelte';
import MatrixCard from './MatrixCard.svelte';
import NoteCard from './NoteCard.svelte';
import NumberCard from './NumberCard.svelte';
import ScaleCard from './ScaleCard.svelte';
import TextCard from './TextCard.svelte';
import type { CardFamily, CardProps } from './types';

export const CARDS: Readonly<Record<CardFamily, Component<CardProps>>> = {
	choice: ChoiceCard,
	text: TextCard,
	number: NumberCard,
	matrix: MatrixCard,
	scale: ScaleCard,
	note: NoteCard
};

/** The card for a family, or null (the dispatcher then shows a generic card). */
export function cardFor(family: CardFamily | null): Component<CardProps> | null {
	return family ? CARDS[family] : null;
}
