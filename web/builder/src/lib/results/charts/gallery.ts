// Every chart the builders draw, from the fixture cards: the /dev/charts gallery and the
// spec tests both walk this list, so a new chart choice shows up in both.
import { FIXTURE_CARDS } from './fixtures';
import { chartsFor, isChart, splitsFor } from './menu';
import type { BuildOptions, Card, ChartChoice, SplitLayout } from './types';

export interface GalleryEntry {
	id: string;
	title: string;
	card: Card;
	choice: ChartChoice;
	split?: SplitLayout;
	intervals?: boolean;
}

export function galleryEntries(): GalleryEntry[] {
	const out: GalleryEntry[] = [];
	for (const [name, card] of Object.entries(FIXTURE_CARDS)) {
		for (const { id: choice, label } of chartsFor(card).choices) {
			if (!isChart(choice)) continue;
			const splits = splitsFor(card, choice);
			const layouts: (SplitLayout | undefined)[] = splits.length ? splits : [undefined];
			for (const split of layouts) {
				const base = `${name}-${choice}${split ? `-${split}` : ''}`;
				out.push({ id: base, title: `${name} · ${label}${split ? ` · ${split}` : ''}: ${card.label}`, card, choice, split });
			}
		}
	}
	// Interval variants (V1's Wilson / t intervals) for the cards that carry them.
	out.push(
		{ id: 'single-bars-intervals', title: 'Bars with 95 % Wilson intervals', card: FIXTURE_CARDS.single, choice: 'bars', intervals: true },
		{ id: 'multi-dot-intervals', title: 'Dot plot with 95 % Wilson intervals', card: FIXTURE_CARDS.multi, choice: 'dot', intervals: true },
		{ id: 'integer-box-intervals', title: 'Box plot with the mean and its 95 % t interval', card: FIXTURE_CARDS.integer, choice: 'box', intervals: true },
		{ id: 'integerSplit-box-intervals', title: 'Box plots per group with t intervals', card: FIXTURE_CARDS.integerSplit, choice: 'box', split: 'grouped', intervals: true }
	);
	return out;
}

export function entryOptions(e: GalleryEntry, extra: BuildOptions = {}): BuildOptions {
	return { ...extra, split: e.split, intervals: e.intervals ?? false, description: `${e.card.label}: ${e.title}` };
}
