/**
 * Rich-text levels (planning/rich-text.md §3.1, lead decision 4): what a field may hold
 * and how long it may be. Mirrors `osp_spec.richtext.LIMITS`; the validator is the truth,
 * these numbers only drive the editor's toolbar and its character count.
 */

export type Level = 'block' | 'stem' | 'inline';

export const LEVELS: readonly Level[] = ['block', 'stem', 'inline'];

/** Text characters per field per language (pipes and breaks count 0). */
export const LIMITS: Readonly<Record<Level, number>> = { block: 20_000, stem: 2_000, inline: 500 };

export function isLevel(v: unknown): v is Level {
	return v === 'block' || v === 'stem' || v === 'inline';
}

/** Which toolbar controls a level offers (RT-D5: headings only at block; nothing structural inline). */
export function allows(level: Level, feature: 'heading' | 'list' | 'break' | 'paragraphs'): boolean {
	switch (feature) {
		case 'heading':
			return level === 'block';
		case 'list':
		case 'paragraphs':
			return level !== 'inline';
		case 'break':
			return true;
	}
}
