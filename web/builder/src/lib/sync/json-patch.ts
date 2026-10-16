/**
 * RFC 6902 JSON Patch (+ RFC 6901 pointers), small and dependency-free.
 *
 * `applyPatch` never mutates its input: it returns a new document, so a failed patch
 * leaves the caller's copy untouched (all or nothing). Errors are `PatchError`s; the
 * survey store answers one by refetching the draft, never by guessing.
 */
export type JsonValue = null | boolean | number | string | JsonValue[] | { [k: string]: JsonValue };

export interface PatchOperation {
	op: string;
	path: string;
	value?: unknown;
	from?: string;
}

export class PatchError extends Error {
	constructor(
		message: string,
		readonly index: number
	) {
		super(message);
		this.name = 'PatchError';
	}
}

type Container = Record<string, unknown> | unknown[];

/** "/a/b~1c" → ["a", "b/c"]. Throws on a pointer that doesn't start with "/". */
export function parsePointer(pointer: string): string[] {
	if (pointer === '') return [];
	if (typeof pointer !== 'string' || !pointer.startsWith('/')) {
		throw new Error(`invalid JSON pointer ${JSON.stringify(pointer)}`);
	}
	return pointer
		.slice(1)
		.split('/')
		.map((t) => t.replace(/~1/g, '/').replace(/~0/g, '~'));
}

function isContainer(v: unknown): v is Container {
	return typeof v === 'object' && v !== null;
}

function clone<T>(v: T): T {
	return v === undefined ? v : (JSON.parse(JSON.stringify(v)) as T);
}

function arrayIndex(arr: unknown[], token: string, forInsert: boolean): number {
	if (forInsert && token === '-') return arr.length;
	if (!/^(0|[1-9][0-9]*)$/.test(token)) throw new Error(`bad array index ${JSON.stringify(token)}`);
	const i = Number(token);
	const max = forInsert ? arr.length : arr.length - 1;
	if (i > max) throw new Error(`array index ${i} out of range`);
	return i;
}

function hasOwn(obj: object, key: string): boolean {
	return Object.prototype.hasOwnProperty.call(obj, key);
}

/** The parent container and last token of `path` inside `doc`. */
function parentOf(doc: unknown, tokens: string[]): { parent: Container; key: string } {
	let cur: unknown = doc;
	for (const t of tokens.slice(0, -1)) {
		if (Array.isArray(cur)) cur = cur[arrayIndex(cur, t, false)];
		else if (isContainer(cur) && hasOwn(cur, t)) cur = (cur as Record<string, unknown>)[t];
		else throw new Error(`path not found at ${JSON.stringify(t)}`);
	}
	if (!isContainer(cur)) throw new Error('parent is not an object or array');
	return { parent: cur, key: tokens[tokens.length - 1] };
}

export function getAt(doc: unknown, pointer: string): unknown {
	let cur: unknown = doc;
	for (const t of parsePointer(pointer)) {
		if (Array.isArray(cur)) cur = cur[arrayIndex(cur, t, false)];
		else if (isContainer(cur) && hasOwn(cur, t)) cur = (cur as Record<string, unknown>)[t];
		else throw new Error(`path not found: ${pointer}`);
	}
	return cur;
}

function deepEqual(a: unknown, b: unknown): boolean {
	if (a === b) return true;
	if (Array.isArray(a) && Array.isArray(b)) {
		return a.length === b.length && a.every((v, i) => deepEqual(v, b[i]));
	}
	if (isContainer(a) && isContainer(b) && !Array.isArray(a) && !Array.isArray(b)) {
		const ka = Object.keys(a);
		const kb = Object.keys(b);
		return (
			ka.length === kb.length &&
			ka.every((k) => hasOwn(b, k) && deepEqual((a as never)[k], (b as never)[k]))
		);
	}
	return false;
}

// Each step returns the (possibly new) root, because an op on "" replaces the document.
function add(doc: unknown, path: string, value: unknown): unknown {
	const tokens = parsePointer(path);
	if (!tokens.length) return clone(value);
	const { parent, key } = parentOf(doc, tokens);
	if (Array.isArray(parent)) parent.splice(arrayIndex(parent, key, true), 0, clone(value));
	else (parent as Record<string, unknown>)[key] = clone(value);
	return doc;
}

function remove(doc: unknown, path: string): unknown {
	const tokens = parsePointer(path);
	if (!tokens.length) throw new Error('cannot remove the document root');
	const { parent, key } = parentOf(doc, tokens);
	if (Array.isArray(parent)) parent.splice(arrayIndex(parent, key, false), 1);
	else if (hasOwn(parent, key)) delete (parent as Record<string, unknown>)[key];
	else throw new Error(`path not found: ${path}`);
	return doc;
}

function replace(doc: unknown, path: string, value: unknown): unknown {
	const tokens = parsePointer(path);
	if (!tokens.length) return clone(value);
	const { parent, key } = parentOf(doc, tokens);
	if (Array.isArray(parent)) parent[arrayIndex(parent, key, false)] = clone(value);
	else if (hasOwn(parent, key)) (parent as Record<string, unknown>)[key] = clone(value);
	else throw new Error(`path not found: ${path}`);
	return doc;
}

function step(doc: unknown, op: PatchOperation): unknown {
	if (!isContainer(op) || typeof op.path !== 'string') throw new Error('operation needs a path');
	switch (op.op) {
		case 'add':
			if (!('value' in op)) throw new Error('add needs a value');
			return add(doc, op.path, op.value);
		case 'remove':
			return remove(doc, op.path);
		case 'replace':
			if (!('value' in op)) throw new Error('replace needs a value');
			return replace(doc, op.path, op.value);
		case 'move': {
			if (typeof op.from !== 'string') throw new Error('move needs from');
			if (op.path !== op.from && op.path.startsWith(op.from + '/')) {
				throw new Error('cannot move a value into itself');
			}
			const value = getAt(doc, op.from);
			return add(remove(doc, op.from), op.path, value);
		}
		case 'copy': {
			if (typeof op.from !== 'string') throw new Error('copy needs from');
			return add(doc, op.path, getAt(doc, op.from));
		}
		case 'test':
			if (!deepEqual(getAt(doc, op.path), op.value)) throw new Error(`test failed at ${op.path}`);
			return doc;
		default:
			throw new Error(`unknown op ${JSON.stringify(op.op)}`);
	}
}

/** Apply `patch` to a copy of `doc`. Throws `PatchError` (doc untouched) on any problem. */
export function applyPatch<T>(doc: T, patch: readonly PatchOperation[]): T {
	if (!Array.isArray(patch)) throw new PatchError('patch must be an array', -1);
	let out: unknown = clone(doc);
	patch.forEach((op, i) => {
		try {
			out = step(out, op);
		} catch (e) {
			throw new PatchError(`patch op ${i}: ${(e as Error).message}`, i);
		}
	});
	return out as T;
}
