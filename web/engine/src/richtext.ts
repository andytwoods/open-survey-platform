/**
 * The survey model's rich text (planning/rich-text.md §3) in TypeScript: the tree shape a
 * `Text` field may hold, `normaliseText` (the same rule as `osp_spec.richtext.normalise_text`,
 * proved equal by the shared cases in python/osp-spec/tests/cases/richtext-normalise.json)
 * and `plainTextOf` for accessible names and search. Pure; used by the builder's editor
 * (RT3) and the runtime. The plan's `Block` / `InlineRun` types (plan.ts) are the same
 * shapes, so a tree's blocks are its plan blocks.
 */

import type { InlineRun, RichBlock, TextRun } from './plan.ts';

/** `{"type": "rich", "blocks": [...]}`: the rich variant of a survey `Text`. */
export interface RichText {
	type: 'rich';
	blocks: RichBlock[];
}

/** A survey `Text`: plain, rich, or per language (each plain or rich). */
export type SurveyText = string | RichText | Record<string, string | RichText>;

export function isRichText(value: unknown): value is RichText {
	return (
		typeof value === 'object' &&
		value !== null &&
		!Array.isArray(value) &&
		(value as { type?: unknown }).type === 'rich' &&
		'blocks' in (value as object)
	);
}

function plainRun(node: unknown): string | null {
	if (typeof node !== 'object' || node === null) return null;
	const n = node as Record<string, unknown>;
	const keys = Object.keys(n);
	if (typeof n.pipe === 'string' && keys.length === 1) return `\${${n.pipe}}`;
	if (typeof n.text === 'string' && keys.every((k) => k === 'text' || k === 'marks')) {
		const marks = n.marks;
		return Array.isArray(marks) && marks.length > 0 ? null : n.text;
	}
	return null;
}

/**
 * Rich text with no formatting (one paragraph; no marks, links, breaks, headings, lists
 * or language spans) as the plain string it is, pipes written back as `${id}`; an empty
 * tree is `""`. Everything else (plain strings, formatted trees, non-text values) comes
 * back unchanged; a per-language map is normalised value by value (RT-D3).
 */
export function normaliseText<T>(value: T): T | string {
	if (typeof value !== 'object' || value === null || Array.isArray(value)) return value;
	const v = value as Record<string, unknown>;
	if (isRichText(v)) {
		const blocks = v.blocks as unknown;
		if (!Array.isArray(blocks)) return value;
		if (blocks.length === 0) return '';
		if (blocks.length !== 1) return value;
		const block = blocks[0] as Record<string, unknown> | null;
		if (typeof block !== 'object' || block === null || block.type !== 'p') return value;
		const content = block.content;
		if (!Array.isArray(content)) return value;
		const parts = content.map(plainRun);
		if (parts.some((p) => p === null)) return value;
		return parts.join('');
	}
	const out: Record<string, unknown> = {};
	for (const [k, x] of Object.entries(v)) out[k] = normaliseText(x);
	return out as T;
}

function runsPlain(runs: InlineRun[]): string {
	return runs
		.map((r) => {
			if ('br' in r) return '\n';
			if ('pipe' in r) return `\${${r.pipe}}`;
			return (r as TextRun).text;
		})
		.join('');
}

/**
 * One value flattened to plain text: runs joined, pipes as `${id}`, breaks as newlines,
 * blocks separated by a blank line, list items on their own lines with `- ` / `1. `.
 * Mirrors `osp_spec.richtext.to_plain`.
 */
export function plainTextOf(value: string | RichText | undefined | null): string {
	if (value === undefined || value === null) return '';
	if (typeof value === 'string') return value;
	return value.blocks
		.map((b) => {
			if ('items' in b) {
				return b.items.map((item, i) => (b.type === 'ol' ? `${i + 1}. ` : '- ') + runsPlain(item)).join('\n');
			}
			return runsPlain(b.content);
		})
		.join('\n\n');
}

/** The text characters of one value (pipes and breaks count 0), as the validator counts. */
export function charCount(value: string | RichText | undefined | null): number {
	if (!value) return 0;
	if (typeof value === 'string') return value.replace(/\$\{[^}]*\}/g, '').length;
	let n = 0;
	for (const b of value.blocks) {
		const runs = 'items' in b ? b.items.flat() : b.content;
		for (const r of runs) if ('text' in r) n += r.text.length;
	}
	return n;
}
