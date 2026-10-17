/**
 * JSON text helpers for the JSON view (task B9): a validating scanner that reports the
 * first syntax error with its position, and maps every RFC 6901 JSON pointer in the text to
 * the span it occupies, so a server diagnostic (`pointer`) can be shown at its place.
 *
 * Pure: no DOM, no CodeMirror. Never throws on any input.
 */

export interface Span {
	from: number;
	to: number;
}

export interface Position {
	/** 1-based. */
	line: number;
	/** 1-based, in UTF-16 code units. */
	col: number;
}

export type ParseResult =
	| { ok: true; value: unknown; spans: Map<string, Span> }
	| { ok: false; message: string; offset: number; position: Position };

class SyntaxProblem extends Error {
	constructor(
		message: string,
		readonly offset: number
	) {
		super(message);
	}
}

const WS = new Set([' ', '\t', '\n', '\r']);
const MAX_DEPTH = 512;

/** Escape one pointer segment (RFC 6901). */
export function escapeSegment(s: string): string {
	return s.replace(/~/g, '~0').replace(/\//g, '~1');
}

/** Split a pointer into unescaped segments; "" is the root. */
export function pointerSegments(pointer: string): string[] {
	if (!pointer) return [];
	return pointer
		.split('/')
		.slice(1)
		.map((s) => s.replace(/~1/g, '/').replace(/~0/g, '~'));
}

function describe(ch: string | undefined): string {
	if (ch === undefined) return 'end of input';
	if (ch === '\n') return 'a line break';
	return `"${ch}"`;
}

/** Scan `text` as JSON, recording the span of every value by its pointer. */
function scan(text: string): Map<string, Span> {
	const spans = new Map<string, Span>();
	let i = 0;

	const skip = () => {
		while (i < text.length && WS.has(text[i])) i++;
	};
	const fail = (what: string): never => {
		throw new SyntaxProblem(`Expected ${what} but found ${describe(text[i])}.`, i);
	};

	const string = (): string => {
		if (text[i] !== '"') fail('a string');
		const start = i++;
		let out = '';
		for (;;) {
			if (i >= text.length) throw new SyntaxProblem('Unterminated string.', start);
			const ch = text[i];
			if (ch === '"') {
				i++;
				return out;
			}
			if (ch === '\\') {
				const e = text[i + 1];
				const simple: Record<string, string> = {
					'"': '"',
					'\\': '\\',
					'/': '/',
					b: '\b',
					f: '\f',
					n: '\n',
					r: '\r',
					t: '\t'
				};
				if (e !== undefined && e in simple) {
					out += simple[e];
					i += 2;
				} else if (e === 'u' && /^[0-9a-fA-F]{4}$/.test(text.slice(i + 2, i + 6))) {
					out += String.fromCharCode(parseInt(text.slice(i + 2, i + 6), 16));
					i += 6;
				} else {
					throw new SyntaxProblem('Invalid escape in string.', i);
				}
				continue;
			}
			if (ch < ' ') throw new SyntaxProblem('Control character in string (use \\n, \\t …).', i);
			out += ch;
			i++;
		}
	};

	const number = () => {
		const m = /^-?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?/.exec(text.slice(i, i + 400));
		if (!m || !m[0] || m[0] === '-') fail('a value');
		i += m![0].length;
	};

	const value = (ptr: string, depth: number) => {
		if (depth > MAX_DEPTH) throw new SyntaxProblem('Nested too deeply.', i);
		skip();
		const from = i;
		const ch = text[i];
		if (ch === '{') {
			i++;
			skip();
			if (text[i] === '}') i++;
			else {
				for (;;) {
					skip();
					const keyFrom = i;
					const key = string();
					skip();
					if (text[i] !== ':') fail('":"');
					i++;
					const child = `${ptr}/${escapeSegment(key)}`;
					value(child, depth + 1);
					// A member's span starts at its key, so the whole `"key": value` is marked.
					const v = spans.get(child);
					if (v) spans.set(child, { from: keyFrom, to: v.to });
					skip();
					if (text[i] === ',') {
						i++;
						continue;
					}
					if (text[i] === '}') {
						i++;
						break;
					}
					fail('"," or "}"');
				}
			}
		} else if (ch === '[') {
			i++;
			skip();
			if (text[i] === ']') i++;
			else {
				for (let n = 0; ; n++) {
					value(`${ptr}/${n}`, depth + 1);
					skip();
					if (text[i] === ',') {
						i++;
						continue;
					}
					if (text[i] === ']') {
						i++;
						break;
					}
					fail('"," or "]"');
				}
			}
		} else if (ch === '"') {
			string();
		} else if (ch === '-' || (ch >= '0' && ch <= '9')) {
			number();
		} else if (text.startsWith('true', i)) i += 4;
		else if (text.startsWith('false', i)) i += 5;
		else if (text.startsWith('null', i)) i += 4;
		else fail('a value');
		spans.set(ptr, { from, to: i });
	};

	value('', 0);
	skip();
	if (i < text.length) throw new SyntaxProblem(`Unexpected ${describe(text[i])} after the JSON value.`, i);
	return spans;
}

/** 1-based line and column of an offset. */
export function positionAt(text: string, offset: number): Position {
	const o = Math.max(0, Math.min(offset, text.length));
	let line = 1;
	let lineStart = 0;
	for (let k = 0; k < o; k++) {
		if (text.charCodeAt(k) === 10) {
			line++;
			lineStart = k + 1;
		}
	}
	return { line, col: o - lineStart + 1 };
}

/** Parse JSON text. A syntax error comes back with its position, never as an exception. */
export function parseJson(text: string): ParseResult {
	try {
		const spans = scan(text);
		return { ok: true, value: JSON.parse(text), spans };
	} catch (e) {
		const offset = e instanceof SyntaxProblem ? e.offset : 0;
		const message = e instanceof Error ? e.message : 'Invalid JSON.';
		return { ok: false, message, offset, position: positionAt(text, offset) };
	}
}

/**
 * Where a pointer is in the text: its own span, else the nearest ancestor's (a diagnostic
 * about a missing member points at the object that lacks it). Undefined only when the
 * text is not valid JSON.
 */
export function locate(spans: Map<string, Span>, pointer: string): Span | undefined {
	let p = pointer;
	for (;;) {
		const s = spans.get(p);
		if (s) return s;
		if (!p) return undefined;
		p = p.slice(0, p.lastIndexOf('/'));
	}
}

/** The survey as the JSON view shows it. */
export function formatJson(value: unknown): string {
	return JSON.stringify(value ?? null, null, 2) + '\n';
}
