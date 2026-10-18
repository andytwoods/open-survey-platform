/**
 * RFC 6902 JSON Patch: a structural diff and an applier, for plain JSON values; a port of
 * `osp_ops.patch` (same patches, same error messages).
 *
 * `diff(a, b)` keeps patches small for the edits ops make: a changed key is replaced, a
 * list insert/remove is one `add`/`remove`, and a single element moved within a list is
 * one `move`. `apply(doc, patch)` returns a new document and never mutates its input; a
 * bad patch throws `PatchError`.
 */

import { deepCopy, isObj, has, pyLen, reprStr, same, slice, type Json, type JsonObject } from './py.ts';

export type PatchOp = JsonObject;
export type Patch = PatchOp[];
export type PathPart = string | number;

export class PatchError extends Error {}

/** A Python exception other than the ones the code catches (becomes `op.internal`). */
export class PyException extends Error {
	constructor(readonly pyType: string) {
		super(pyType);
	}
}

export function toPointer(parts: readonly PathPart[]): string {
	let out = '';
	for (const p of parts) out += '/' + String(p).replaceAll('~', '~0').replaceAll('/', '~1');
	return out;
}

export function fromPointer(ptr: string): string[] {
	if (ptr === '') return [];
	if (!ptr.startsWith('/')) throw new PatchError(`JSON pointer must start with '/': ${reprStr(slice(ptr, 0, 60))}`);
	return ptr
		.slice(1)
		.split('/')
		.map((p) => p.replaceAll('~1', '/').replaceAll('~0', '~'));
}

// --- diff -----------------------------------------------------------------------------------

export function diff(a: Json, b: Json): Patch {
	const out: Patch = [];
	diffInto(a, b, [], out);
	return out;
}

function diffInto(a: Json, b: Json, path: PathPart[], out: Patch): void {
	if (same(a, b)) return;
	if (isObj(a) && isObj(b)) {
		for (const k of Object.keys(a)) if (!has(b, k)) out.push({ op: 'remove', path: toPointer([...path, k]) });
		for (const k of Object.keys(b)) {
			if (has(a, k)) diffInto(a[k]!, b[k]!, [...path, k], out);
			else out.push({ op: 'add', path: toPointer([...path, k]), value: deepCopy(b[k]!) });
		}
		return;
	}
	if (Array.isArray(a) && Array.isArray(b)) {
		diffList(a, b, path, out);
		return;
	}
	out.push({ op: 'replace', path: toPointer(path), value: deepCopy(b) });
}

function diffList(a: Json[], b: Json[], path: PathPart[], out: Patch): void {
	let start = 0;
	while (start < a.length && start < b.length && same(a[start]!, b[start]!)) start++;
	let endA = a.length;
	let endB = b.length;
	while (endA > start && endB > start && same(a[endA - 1]!, b[endB - 1]!)) {
		endA--;
		endB--;
	}
	const midA = a.slice(start, endA);
	const midB = b.slice(start, endB);
	const n = midA.length;
	if (n === midB.length && n >= 2) {
		const last = start + n - 1;
		if (same(midA[0]!, midB[n - 1]!) && midA.slice(1).every((x, i) => same(x, midB[i]!))) {
			out.push(move(path, start, last));
			return;
		}
		if (same(midA[n - 1]!, midB[0]!) && midA.slice(0, -1).every((x, i) => same(x, midB[i + 1]!))) {
			out.push(move(path, last, start));
			return;
		}
	}
	const common = Math.min(n, midB.length);
	for (let i = 0; i < common; i++) diffInto(midA[i]!, midB[i]!, [...path, start + i], out);
	for (let i = common; i < n; i++) out.push({ op: 'remove', path: toPointer([...path, start + common]) });
	for (let i = common; i < midB.length; i++) {
		out.push({ op: 'add', path: toPointer([...path, start + i]), value: deepCopy(midB[i]!) });
	}
}

function move(path: PathPart[], src: number, dst: number): PatchOp {
	return { op: 'move', from: toPointer([...path, src]), path: toPointer([...path, dst]) };
}

// --- apply ----------------------------------------------------------------------------------

const MAX_OPS = 10_000;

type Root = [Json];

/** Apply an RFC 6902 patch to a copy of `doc`. Throws `PatchError`. */
export function apply(doc: Json, patch: unknown): Json {
	if (!Array.isArray(patch)) throw new PatchError('a patch is a list of operations');
	if (patch.length > MAX_OPS) throw new PatchError(`a patch may have at most ${MAX_OPS} operations`);
	const root: Root = [deepCopy(doc)];
	patch.forEach((op, i) => {
		try {
			applyOne(root, op);
		} catch (e) {
			if (e instanceof PatchError) throw new PatchError(`operation ${i}: ${e.message}`);
			throw e;
		}
	});
	return root[0];
}

function applyOne(root: Root, op: unknown): void {
	if (!isObj(op) || typeof op.op !== 'string' || !has(op, 'op')) {
		throw new PatchError("each operation is an object with an 'op' string");
	}
	const kind = op.op;
	const path = strField(op, 'path');
	if (kind === 'add') add(root, path, value(op));
	else if (kind === 'remove') remove(root, path);
	else if (kind === 'replace') {
		const v = value(op);
		if (path === '') root[0] = v;
		else {
			remove(root, path);
			add(root, path, v);
		}
	} else if (kind === 'move') {
		const src = strField(op, 'from');
		if (path !== src && (path + '/').startsWith(src + '/')) throw new PatchError('cannot move a value into itself');
		const v = remove(root, src);
		add(root, path, v);
	} else if (kind === 'copy') {
		add(root, path, deepCopy(getAt(root, strField(op, 'from'))));
	} else if (kind === 'test') {
		if (!same(getAt(root, path), value(op))) throw new PatchError(`test failed at ${reprStr(slice(path, 0, 80))}`);
	} else throw new PatchError(`unknown patch op ${reprStr(slice(kind, 0, 20))}`);
}

function strField(op: JsonObject, key: string): string {
	const v = has(op, key) ? op[key] : undefined;
	if (typeof v !== 'string') throw new PatchError(`'${key}' must be a JSON pointer string`);
	return v;
}

function value(op: JsonObject): Json {
	if (!has(op, 'value')) throw new PatchError("'value' is missing");
	return deepCopy(op.value!);
}

function parent(root: Root, ptr: string): [Json | Root, PathPart] {
	const parts = fromPointer(ptr);
	let cur: Json | Root = root;
	let key: PathPart = 0;
	for (const part of parts) {
		cur = step(cur, key);
		key = part;
	}
	return [cur, key];
}

function step(cur: Json | Root, key: PathPart): Json {
	if (isObj(cur)) {
		if (typeof key !== 'string' || !has(cur, key)) throw new PatchError(`no member ${reprStr(slice(String(key), 0, 40))}`);
		return cur[key]!;
	}
	if (Array.isArray(cur)) return (cur as Json[])[index(cur as Json[], key, false)]!;
	throw new PatchError('path goes through a scalar');
}

// Python's `str.isdigit()` is true for any Unicode decimal digit, and `int()` reads them.
const DIGITS = /^\p{Nd}+$/u;
const DIGITISH = /[²³¹⁰⁴-⁹₀-₉①-⑨⑴-⑼⒈-⒐⓵-⓽⓪❶-❾➀-➈➊-➒፩-፱]/u;

function digitValue(ch: string): number {
	const cp = ch.codePointAt(0)!;
	let start = cp;
	while (start > 0 && /^\p{Nd}$/u.test(String.fromCodePoint(start - 1))) start--;
	return (cp - start) % 10;
}

function isDigitKey(key: string): boolean {
	if (DIGITS.test(key)) return true;
	if (key.length > 0 && Array.from(key).every((c) => DIGITS.test(c) || DIGITISH.test(c))) {
		return true;
	}
	return false;
}

function parseDigits(key: string): number {
	let n = 0;
	for (const ch of key) {
		if (!DIGITS.test(ch)) throw new PyException('ValueError');
		n = n * 10 + digitValue(ch);
	}
	return n;
}

function index(lst: Json[], key: PathPart, allowEnd: boolean): number {
	let i: number;
	if (typeof key === 'number') i = key;
	else if (key === '-' && allowEnd) return lst.length;
	else if (isDigitKey(key) && (key === '0' || !key.startsWith('0')) && pyLen(key) < 10) i = parseDigits(key);
	else throw new PatchError(`bad array index ${reprStr(slice(String(key), 0, 20))}`);
	if (i > lst.length || (i === lst.length && !allowEnd)) throw new PatchError(`array index ${i} out of range`);
	return i;
}

function getAt(root: Root, ptr: string): Json {
	const [p, key] = parent(root, ptr);
	return step(p, key);
}

function add(root: Root, ptr: string, v: Json): void {
	const [p, key] = parent(root, ptr);
	if (isObj(p)) p[String(key)] = v;
	else if (Array.isArray(p)) {
		if (p === root) root[0] = v;
		else (p as Json[]).splice(index(p as Json[], key, true), 0, v);
	} else throw new PatchError('cannot add into a scalar');
}

function remove(root: Root, ptr: string): Json {
	if (ptr === '') throw new PatchError('cannot remove the document root');
	const [p, key] = parent(root, ptr);
	if (isObj(p)) {
		if (!has(p, String(key))) throw new PatchError(`no member ${reprStr(slice(String(key), 0, 40))}`);
		const v = p[String(key)]!;
		delete p[String(key)];
		return v;
	}
	if (Array.isArray(p)) {
		const lst = p as Json[];
		return lst.splice(index(lst, key, false), 1)[0]!;
	}
	throw new PatchError('cannot remove from a scalar');
}
