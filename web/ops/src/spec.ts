/**
 * The `osp-spec` helpers the ops call, ported: rich-text shape helpers and
 * `normalise_text` (osp_spec.richtext), `RESERVED_NAMES` (osp_spec.reserved) and the bank
 * helpers `canonical_json`, `fragment_checksum`, `fragment_kind` (osp_spec.bank).
 */

import { canonicalJson as engineCanonicalJson, sha256, toHex, utf8 } from '@osp/engine';
import { has, isObj, truthy, type Json, type JsonObject } from './py.ts';
import { PyException, type PathPart } from './patch.ts';

export const RESERVED_NAMES: ReadonlySet<string> = new Set(
	[
		'id',
		'seed',
		'token',
		'submitdate',
		'lastpage',
		'startlanguage',
		'startdate',
		'datestamp',
		'ipaddr',
		'refurl',
		'instanceID',
		'instanceName',
		'deprecatedID',
		'meta'
	].map((n) => n.toLowerCase())
);

export function isRich(value: Json | undefined): boolean {
	return isObj(value) && value.type === 'rich' && has(value, 'blocks');
}

function contentOf(block: JsonObject): [PathPart[], Json[]][] {
	if (block.type === 'ul' || block.type === 'ol') {
		const items = block.items;
		if (!Array.isArray(items)) return [];
		const out: [PathPart[], Json[]][] = [];
		items.forEach((run, i) => {
			if (Array.isArray(run)) out.push([['items', i], run]);
		});
		return out;
	}
	const content = block.content;
	return Array.isArray(content) ? [[['content'], content]] : [];
}

/** Every inline node of a tree with its path from the tree root, in reading order. */
export function* inlinePaths(tree: Json | undefined): Generator<[PathPart[], Json]> {
	const blocks = isObj(tree) ? tree.blocks : undefined;
	if (!Array.isArray(blocks)) return;
	for (let b = 0; b < blocks.length; b++) {
		const block = blocks[b];
		if (!isObj(block)) continue;
		for (const [sub, runs] of contentOf(block)) {
			for (let i = 0; i < runs.length; i++) yield [['blocks', b, ...sub, i], runs[i]!];
		}
	}
}

/** `(path, id)` of every pipe node of a tree. */
export function* pipesOf(tree: Json | undefined): Generator<[PathPart[], string]> {
	for (const [path, node] of inlinePaths(tree)) {
		if (isObj(node) && typeof node.pipe === 'string') yield [path, node.pipe];
	}
}

function runPlain(node: Json): string | null {
	if (!isObj(node)) return null;
	const keys = Object.keys(node);
	if (typeof node.pipe === 'string' && keys.length === 1) return '${' + node.pipe + '}';
	if (typeof node.text === 'string' && keys.every((k) => k === 'text' || k === 'marks')) {
		return truthy(node.marks) ? null : node.text;
	}
	return null;
}

/** Formatting-free rich text as the plain string it is (`osp_spec.richtext.normalise_text`). */
export function normaliseText(value: Json): Json {
	if (isObj(value) && isRich(value)) {
		const blocks = value.blocks;
		if (!Array.isArray(blocks)) return value;
		if (blocks.length === 0) return '';
		if (blocks.length !== 1) return value;
		const block = blocks[0];
		if (!isObj(block) || block.type !== 'p') return value;
		const content = block.content;
		if (!Array.isArray(content)) return value;
		const parts = content.map(runPlain);
		if (parts.some((p) => p === null)) return value;
		return parts.join('');
	}
	if (isObj(value)) {
		const out: JsonObject = {};
		for (const k of Object.keys(value)) {
			const v = normaliseText(value[k]!);
			if (k === '__proto__') Object.defineProperty(out, k, { value: v, writable: true, enumerable: true, configurable: true });
			else out[k] = v;
		}
		return out;
	}
	return value;
}

/** `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. */
export function canonicalJson(value: Json): string {
	return engineCanonicalJson(value);
}

function wellFormed(v: Json): boolean {
	if (typeof v === 'string') return !/\p{Cs}/u.test(v);
	if (Array.isArray(v)) return v.every(wellFormed);
	if (isObj(v)) return Object.keys(v).every((k) => wellFormed(k) && wellFormed(v[k]!));
	return true;
}

export function fragmentChecksum(fragment: Json): string {
	// Python encodes the canonical JSON as UTF-8, which fails on a lone surrogate.
	if (!wellFormed(fragment)) throw new PyException('UnicodeEncodeError');
	return 'sha256:' + toHex(sha256(utf8(canonicalJson(fragment))));
}

const KINDS = ['question', 'page', 'block'] as const;

export function fragmentKind(fragment: JsonObject): string | null {
	const present = KINDS.filter((k) => has(fragment, k) && fragment[k] !== null);
	return present.length === 1 ? present[0]! : null;
}
