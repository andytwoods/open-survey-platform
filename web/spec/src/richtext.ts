/**
 * Rich text (osp_spec.richtext; planning/rich-text.md §3): levels, limits, the level/link/size
 * rules and character counting, over parsed (structurally valid) texts: a string, a
 * `{type: "rich", blocks}` tree, or a `Map` of language to either.
 */

import { pointer } from './diagnostics.ts';
import { pyLen } from './py.ts';

export type Level = 'block' | 'stem' | 'inline';
export const LIMITS: Record<Level, number> = { block: 20_000, stem: 2_000, inline: 500 };
export const MAX_BLOCKS = 200;
export const MAX_LIST_ITEMS = 100;

export const PIPE = /\$\{([^}]*)\}/g;

export interface RichTree {
	type: 'rich';
	blocks: Array<Record<string, unknown>>;
}

export type TextValue = string | RichTree | Map<string, string | RichTree>;

export function isTree(v: unknown): v is RichTree {
	return typeof v === 'object' && v !== null && !(v instanceof Map) && (v as RichTree).type === 'rich';
}

/** Every inline node of a tree with its path from the tree root, in reading order. */
function* inlinePaths(tree: RichTree): Generator<[Array<string | number>, Record<string, unknown>]> {
	for (const [b, block] of tree.blocks.entries()) {
		if (block.type === 'ul' || block.type === 'ol') {
			for (const [i, run] of (block.items as Array<Array<Record<string, unknown>>>).entries()) {
				for (const [k, node] of run.entries()) yield [['blocks', b, 'items', i, k], node];
			}
		} else {
			for (const [k, node] of (block.content as Array<Record<string, unknown>>).entries()) {
				yield [['blocks', b, 'content', k], node];
			}
		}
	}
}

export function hasPipes(value: TextValue): boolean {
	if (typeof value === 'string') return new RegExp(PIPE.source).test(value);
	if (isTree(value)) {
		for (const [, node] of inlinePaths(value)) if (typeof node.pipe === 'string') return true;
		return false;
	}
	for (const v of value.values()) if (hasPipes(v)) return true;
	return false;
}

/** Text characters of one plain string or tree: pipes and breaks count 0. */
export function charCount(value: string | RichTree): number {
	if (typeof value === 'string') return pyLen(value.replace(PIPE, ''));
	let n = 0;
	for (const [, node] of inlinePaths(value)) if (typeof node.text === 'string') n += pyLen(node.text);
	return n;
}

export type Emit = (code: string, ptr: string, message: string) => void;

function https(href: string): boolean {
	return href.startsWith('https://') && href.length > 'https://'.length && !href.includes(' ');
}

/** check_rich: the level, link and size rules for one tree at `ptr`; returns
 * `(pointer, raw id)` for every pipe node. */
export function checkRich(tree: RichTree, level: Level, ptr: string, emit: Emit): Array<[string, string]> {
	const blocks = tree.blocks;
	if (blocks.length > MAX_BLOCKS) emit('text.too_many_blocks', ptr, `${blocks.length} blocks; at most ${MAX_BLOCKS}`);
	if (level === 'inline' && blocks.length > 1) {
		emit(
			'text.block_not_allowed',
			ptr + '/blocks',
			`${blocks.length} blocks in a one-line field; only one paragraph is allowed`
		);
	}
	blocks.forEach((block, b) => {
		const bp = ptr + pointer('blocks', b);
		if (block.type === 'h' && level !== 'block') {
			emit('text.block_not_allowed', bp, 'a heading is only allowed in notes, descriptions, consent and ending text');
		} else if (block.type === 'ul' || block.type === 'ol') {
			if (level === 'inline') emit('text.block_not_allowed', bp, 'a list is not allowed in a one-line field');
			const items = block.items as unknown[];
			if (items.length > MAX_LIST_ITEMS) {
				emit('text.too_many_blocks', bp + '/items', `${items.length} list items; at most ${MAX_LIST_ITEMS}`);
			}
		}
	});
	const pipes: Array<[string, string]> = [];
	for (const [path, node] of inlinePaths(tree)) {
		const np = ptr + pointer(...path);
		if (typeof node.pipe === 'string') {
			pipes.push([np, node.pipe]);
			continue;
		}
		const href = node.href;
		if (href === null || href === undefined) continue;
		if (typeof href !== 'string' || !https(href)) emit('link.scheme', np + '/href', 'a link must be an absolute https: URL');
		if (typeof node.text !== 'string' || node.text === '') emit('link.empty', np, 'a link needs text');
	}
	return pipes;
}
