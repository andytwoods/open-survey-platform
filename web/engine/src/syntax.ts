/**
 * Expression text syntax: tokenizer, recursive-descent parser and printer, exactly as
 * `osp_expr.syntax` (python/osp-expr/src/osp_expr/syntax.py is the reference; parity
 * vectors from web/engine/scripts/build_syntax_vectors.py check the AST JSON, the printed
 * text and every diagnostic's code, message and position).
 *
 * Grammar (lowest precedence first):
 *
 *     expr     := or
 *     or       := and ("or" and)*                 n-ary Or
 *     and      := not ("and" not)*                n-ary And
 *     not      := "not" not | compare
 *     compare  := sum (CMP sum)?                  CMP: == != < <= > >=  (no chaining)
 *     sum      := product (("+" | "-") product)*  left-associative
 *     product  := unary (("*" | "/") unary)*      left-associative
 *     unary    := "-" NUMBER | primary            minus only on numeric literals
 *     primary  := NUMBER | STRING | "null" | "true" | "false" | IDENT
 *               | "answered" "(" IDENT ")" | "contains" "(" IDENT "," expr ")"
 *               | "if" "(" expr "," expr "," expr ")" | "(" expr ")"
 *
 * `exprToText(parseExpr(s).expr)` is the canonical form of `s` (single spaces, minimal
 * parentheses, `"`-quoted strings). `parseExpr` never throws: problems come back as
 * diagnostics.
 *
 * Positions (`start`, `end`) are 0-based **code point** offsets into the source, as in
 * Python (an emoji counts once); `codePointToUtf16` converts one for a JS string index.
 *
 * The AST is plan JSON (`Expr` in plan.ts): an integer literal beyond ±(2^53 − 1) has its
 * value as decimal text, a decimal literal's value is Python's `str(Decimal)`.
 */

import type { ArithOp, CompareOp, Expr, RefExpr } from './plan.ts';

/** Deepest AST the parser builds; deeper input gets a `too-deep` diagnostic. */
export const EXPR_MAX_DEPTH = 64;
/** Longest integer literal accepted. */
export const EXPR_MAX_INT_DIGITS = 1000;
export const EXPR_FUNCTIONS = ['answered', 'contains', 'if'] as const;
/** Words that cannot be question ids, because the text syntax uses them. */
export const EXPR_KEYWORDS: ReadonlySet<string> = new Set(['and', 'or', 'not', 'null', 'true', 'false']);

/** One problem in expression text (osp_expr.Diagnostic as the parser sets it). */
export interface SyntaxDiagnostic {
	code: string;
	message: string;
	severity: 'error';
	start: number | null;
	end: number | null;
}

/** `expr` is set iff there are no diagnostics. */
export interface ParseResult {
	ok: boolean;
	expr: Expr | null;
	diagnostics: SyntaxDiagnostic[];
}

// --- Lexer ------------------------------------------------------------------------

type TokKind = 'int' | 'dec' | 'str' | 'ident' | 'kw' | 'op' | 'eof';
interface Tok {
	kind: TokKind;
	text: string; // source text (for str: the decoded value)
	start: number;
	end: number;
}

class ExprSyntaxError extends Error {
	readonly diag: SyntaxDiagnostic;
	constructor(code: string, message: string, start: number, end: number) {
		super(message);
		this.diag = { code, message, severity: 'error', start, end };
	}
}

const TWO_CHAR_OPS = new Set(['==', '!=', '<=', '>=']);
const ONE_CHAR_OPS = '<>+-*/(),';
const HEX = '0123456789abcdefABCDEF';
const ESCAPES: Record<string, string> = { '"': '"', '\\': '\\', n: '\n', r: '\r', t: '\t' };
const HINTS: Record<string, string> = {
	'=': "use '==' to test equality",
	'!': "use '!=' or 'not'",
	'&&': "use 'and'",
	'||': "use 'or'",
	'&': "use 'and'",
	'|': "use 'or'",
	"'": 'text literals use double quotes'
};

const isIdentStart = (c: string) => c === '_' || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z');
const isDigit = (c: string) => c.length === 1 && c >= '0' && c <= '9';
const isIdentChar = (c: string) => isIdentStart(c) || isDigit(c);

const NOT_PRINTABLE = /^[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}\p{Zs}]$/u;

/** Python's `repr()` of a one-character string. */
function pyReprChar(c: string): string {
	if (c === "'") return `"'"`;
	if (c === '\\') return "'\\\\'";
	if (c === '\t') return "'\\t'";
	if (c === '\n') return "'\\n'";
	if (c === '\r') return "'\\r'";
	if (c !== ' ' && NOT_PRINTABLE.test(c)) {
		const cp = c.codePointAt(0)!;
		const hex = cp.toString(16);
		if (cp < 0x100) return `'\\x${hex.padStart(2, '0')}'`;
		if (cp < 0x10000) return `'\\u${hex.padStart(4, '0')}'`;
		return `'\\U${hex.padStart(8, '0')}'`;
	}
	return `'${c}'`;
}

function lex(src: readonly string[]): Tok[] {
	const toks: Tok[] = [];
	const n = src.length;
	const at = (k: number) => (k < n ? src[k]! : '');
	const slice = (a: number, b: number) => src.slice(a, Math.min(b, n)).join('');
	let i = 0;
	while (i < n) {
		const c = src[i]!;
		if (c === ' ' || c === '\t' || c === '\r' || c === '\n') {
			i++;
			continue;
		}
		const start = i;
		if (isDigit(c)) {
			while (i < n && isDigit(src[i]!)) i++;
			let kind: TokKind = 'int';
			if (at(i) === '.') {
				if (i + 1 < n && isDigit(src[i + 1]!)) {
					i++;
					while (i < n && isDigit(src[i]!)) i++;
					kind = 'dec';
				} else {
					throw new ExprSyntaxError('bad-number', 'a decimal point must be followed by digits', start, i + 1);
				}
			}
			if (i < n && (isIdentChar(src[i]!) || src[i] === '.')) {
				let j = i;
				while (j < n && (isIdentChar(src[j]!) || src[j] === '.')) j++;
				throw new ExprSyntaxError('bad-number', 'malformed number', start, j);
			}
			if (kind === 'int' && i - start > EXPR_MAX_INT_DIGITS) {
				throw new ExprSyntaxError(
					'bad-number',
					`integer literal longer than ${EXPR_MAX_INT_DIGITS} digits`,
					start,
					i
				);
			}
			toks.push({ kind, text: slice(start, i), start, end: i });
			continue;
		}
		if (isIdentStart(c)) {
			while (i < n && isIdentChar(src[i]!)) i++;
			const word = slice(start, i);
			toks.push({ kind: EXPR_KEYWORDS.has(word) ? 'kw' : 'ident', text: word, start, end: i });
			continue;
		}
		if (c === '"') {
			i++;
			let out = '';
			for (;;) {
				if (i >= n) throw new ExprSyntaxError('unterminated-text', 'text literal is not closed', start, n);
				const ch = src[i]!;
				if (ch === '"') {
					i++;
					break;
				}
				if (ch === '\\') {
					if (i + 1 >= n) throw new ExprSyntaxError('bad-escape', 'unfinished escape', i, n);
					const e = src[i + 1]!;
					if (Object.hasOwn(ESCAPES, e)) {
						out += ESCAPES[e];
						i += 2;
						continue;
					}
					if (e === 'u') {
						const hexpart = src.slice(i + 2, i + 6);
						if (hexpart.length === 4 && hexpart.every((h) => h.length === 1 && HEX.includes(h))) {
							out += String.fromCharCode(parseInt(hexpart.join(''), 16));
							i += 6;
							continue;
						}
						throw new ExprSyntaxError(
							'bad-escape',
							'\\u must be followed by 4 hex digits',
							i,
							Math.min(i + 6, n)
						);
					}
					throw new ExprSyntaxError('bad-escape', `unknown escape '\\${e}'`, i, i + 2);
				}
				out += ch;
				i++;
			}
			toks.push({ kind: 'str', text: out, start, end: i });
			continue;
		}
		const two = slice(i, i + 2);
		if (TWO_CHAR_OPS.has(two)) {
			toks.push({ kind: 'op', text: two, start: i, end: i + 2 });
			i += 2;
			continue;
		}
		if (i + 1 < n && Object.hasOwn(HINTS, two)) {
			throw new ExprSyntaxError('unexpected-char', `unexpected '${two}': ${HINTS[two]}`, i, i + 2);
		}
		if (ONE_CHAR_OPS.includes(c) && c.length === 1) {
			toks.push({ kind: 'op', text: c, start: i, end: i + 1 });
			i++;
			continue;
		}
		const hint = Object.hasOwn(HINTS, c) ? `: ${HINTS[c]}` : '';
		throw new ExprSyntaxError('unexpected-char', `unexpected character ${pyReprChar(c)}${hint}`, i, i + 1);
	}
	toks.push({ kind: 'eof', text: '', start: n, end: n });
	return toks;
}

// --- Numbers ----------------------------------------------------------------------

const MAX_SAFE = String(Number.MAX_SAFE_INTEGER);

/** An integer literal's plan JSON value: a number, or decimal text beyond ±(2^53 − 1). */
function intValue(digits: string, negative: boolean): number | string {
	const d = digits.replace(/^0+/, '') || '0';
	if (d === '0') return 0;
	const safe = d.length < MAX_SAFE.length || (d.length === MAX_SAFE.length && d <= MAX_SAFE);
	if (safe) return negative ? -Number(d) : Number(d);
	return negative ? '-' + d : d;
}

/** Python's `str(Decimal)` (to-sci-string) of sign, coefficient digits and exponent. */
function decimalStr(negative: boolean, coeff: string, exp: number): string {
	const leftdigits = exp + coeff.length;
	const dotplace = exp <= 0 && leftdigits > -6 ? leftdigits : 1;
	let intpart: string;
	let fracpart: string;
	if (dotplace <= 0) {
		intpart = '0';
		fracpart = '.' + '0'.repeat(-dotplace) + coeff;
	} else if (dotplace >= coeff.length) {
		intpart = coeff + '0'.repeat(dotplace - coeff.length);
		fracpart = '';
	} else {
		intpart = coeff.slice(0, dotplace);
		fracpart = '.' + coeff.slice(dotplace);
	}
	const e = leftdigits - dotplace;
	const expPart = e === 0 ? '' : 'E' + (e > 0 ? '+' : '-') + Math.abs(e);
	return (negative ? '-' : '') + intpart + fracpart + expPart;
}

function decValue(text: string, negative: boolean): string {
	const [ip = '', fp = ''] = text.split('.');
	const coeff = (ip + fp).replace(/^0+/, '') || '0';
	return decimalStr(negative, coeff, -fp.length);
}

function numberNode(tok: Tok, negative: boolean): Expr {
	if (tok.kind === 'int') return { kind: 'int', value: intValue(tok.text, negative) };
	return { kind: 'decimal', value: decValue(tok.text, negative) };
}

// --- Parser -----------------------------------------------------------------------

const CMP_OPS = new Set(['==', '!=', '<', '<=', '>', '>=']);
type Node = [Expr, number]; // (node, depth)

function describe(tok: Tok): string {
	if (tok.kind === 'eof') return 'end of input';
	if (tok.kind === 'str') return 'text literal';
	return `'${tok.text}'`;
}

class Parser {
	pos = 0;
	nesting = 0;
	constructor(readonly toks: Tok[]) {}

	peek(): Tok {
		return this.toks[this.pos]!;
	}
	advance(): Tok {
		const tok = this.toks[this.pos]!;
		if (tok.kind !== 'eof') this.pos++;
		return tok;
	}
	at(kind: TokKind, text?: string): boolean {
		const tok = this.peek();
		return tok.kind === kind && (text === undefined || tok.text === text);
	}
	fail(code: string, message: string, tok: Tok): never {
		throw new ExprSyntaxError(code, message, tok.start, tok.end);
	}
	expectOp(text: string, what: string): Tok {
		const tok = this.peek();
		if (tok.kind === 'op' && tok.text === text) return this.advance();
		this.fail('expected', `expected '${text}' ${what}, found ${describe(tok)}`, tok);
	}
	checkDepth(depth: number, start: number): number {
		if (depth > EXPR_MAX_DEPTH) {
			throw new ExprSyntaxError(
				'too-deep',
				`expression is nested more than ${EXPR_MAX_DEPTH} levels deep`,
				start,
				this.peek().end
			);
		}
		return depth;
	}

	parse(): Expr {
		const [node] = this.or();
		const tok = this.peek();
		if (tok.kind !== 'eof') this.fail('unexpected', `unexpected ${describe(tok)} after expression`, tok);
		return node;
	}

	nary(kind: 'and' | 'or', next: () => Node): Node {
		const start = this.peek().start;
		const first = next();
		const args = [first];
		while (this.at('kw', kind)) {
			this.advance();
			args.push(next());
		}
		if (args.length === 1) return first;
		const depth = this.checkDepth(1 + Math.max(...args.map(([, d]) => d)), start);
		return [{ kind, args: args.map(([a]) => a) }, depth];
	}
	or(): Node {
		return this.nary('or', () => this.and());
	}
	and(): Node {
		return this.nary('and', () => this.not());
	}

	not(): Node {
		if (this.at('kw', 'not')) {
			const start = this.advance().start;
			this.nesting++;
			this.checkDepth(this.nesting, start);
			const [arg, d] = this.not();
			this.nesting--;
			return [{ kind: 'not', arg }, this.checkDepth(d + 1, start)];
		}
		return this.compare();
	}

	compare(): Node {
		const start = this.peek().start;
		const [left, ld] = this.sum();
		const tok = this.peek();
		if (tok.kind === 'op' && CMP_OPS.has(tok.text)) {
			this.advance();
			const [right, rd] = this.sum();
			const nxt = this.peek();
			if (nxt.kind === 'op' && CMP_OPS.has(nxt.text)) {
				this.fail('chained-comparison', "comparisons cannot be chained; combine them with 'and'", nxt);
			}
			const node: Expr = { kind: 'compare', op: tok.text as CompareOp, left, right };
			return [node, this.checkDepth(1 + Math.max(ld, rd), start)];
		}
		return [left, ld];
	}

	arith(ops: readonly string[], next: () => Node): Node {
		const start = this.peek().start;
		let [left, ld] = next();
		while (this.peek().kind === 'op' && ops.includes(this.peek().text)) {
			const op = this.advance().text as ArithOp;
			const [right, rd] = next();
			ld = this.checkDepth(1 + Math.max(ld, rd), start);
			left = { kind: 'arith', op, left, right };
		}
		return [left, ld];
	}
	sum(): Node {
		return this.arith(['+', '-'], () => this.product());
	}
	product(): Node {
		return this.arith(['*', '/'], () => this.unary());
	}

	unary(): Node {
		if (this.at('op', '-')) {
			const minus = this.advance();
			const tok = this.peek();
			if (tok.kind === 'int' || tok.kind === 'dec') {
				this.advance();
				return [numberNode(tok, true), 1];
			}
			throw new ExprSyntaxError(
				'unary-minus',
				"'-' can only prefix a number; write '0 - x' to negate an expression",
				minus.start,
				tok.end
			);
		}
		return this.primary();
	}

	primary(): Node {
		const tok = this.peek();
		if (tok.kind === 'int' || tok.kind === 'dec') {
			this.advance();
			return [numberNode(tok, false), 1];
		}
		if (tok.kind === 'str') {
			this.advance();
			return [{ kind: 'text', value: tok.text }, 1];
		}
		if (tok.kind === 'kw') {
			if (tok.text === 'null') {
				this.advance();
				return [{ kind: 'null' }, 1];
			}
			if (tok.text === 'true' || tok.text === 'false') {
				this.advance();
				return [{ kind: 'bool', value: tok.text === 'true' }, 1];
			}
			this.fail('expected', `expected a value, found ${describe(tok)}`, tok);
		}
		if (tok.kind === 'ident') {
			this.advance();
			if (this.at('op', '(')) return this.call(tok);
			return [{ kind: 'ref', id: tok.text }, 1];
		}
		if (tok.kind === 'op' && tok.text === '(') {
			this.advance();
			this.nesting++;
			this.checkDepth(this.nesting, tok.start);
			const node = this.or();
			this.nesting--;
			this.expectOp(')', "to close '('");
			return node;
		}
		this.fail('expected', `expected a value, found ${describe(tok)}`, tok);
	}

	call(name: Tok): Node {
		if (!(EXPR_FUNCTIONS as readonly string[]).includes(name.text)) {
			this.fail(
				'unknown-function',
				`unknown function '${name.text}' (known: ${EXPR_FUNCTIONS.join(', ')})`,
				name
			);
		}
		this.advance(); // "("
		if (name.text === 'if') return this.ifCall(name);
		const ref = this.refArg(name.text);
		if (name.text === 'answered') {
			this.expectOp(')', 'to close answered(');
			return [{ kind: 'answered', ref }, 2];
		}
		this.expectOp(',', 'between the arguments of contains(');
		this.nesting++;
		this.checkDepth(this.nesting, name.start);
		const [value, d] = this.or();
		this.nesting--;
		this.expectOp(')', 'to close contains(');
		return [{ kind: 'contains', ref, value }, this.checkDepth(d + 1, name.start)];
	}

	ifCall(name: Tok): Node {
		this.nesting++;
		this.checkDepth(this.nesting, name.start);
		const args: Node[] = [];
		const seps = [',', ',', ')'];
		for (let k = 0; k < 3; k++) {
			args.push(this.or());
			const sep = seps[k]!;
			this.expectOp(sep, sep === ')' ? 'to close if(' : `after argument ${k + 1} of if(`);
		}
		this.nesting--;
		const [[c, cd], [t, td], [e, ed]] = args as [Node, Node, Node];
		return [{ kind: 'if', cond: c, then: t, else: e }, this.checkDepth(1 + Math.max(cd, td, ed), name.start)];
	}

	refArg(fn: string): RefExpr {
		const tok = this.peek();
		if (tok.kind === 'ident') {
			this.advance();
			return { kind: 'ref', id: tok.text };
		}
		this.fail(
			'expected-question',
			`the first argument of ${fn}() must be a question id, found ${describe(tok)}`,
			tok
		);
	}
}

function failure(code: string, message: string, start: number | null, end: number | null): ParseResult {
	return { ok: false, expr: null, diagnostics: [{ code, message, severity: 'error', start, end }] };
}

/** Parse expression text (`osp_expr.parse`). Never throws; errors come back as diagnostics. */
export function parseExpr(src: unknown): ParseResult {
	try {
		if (typeof src !== 'string') return failure('not-text', 'expression source must be text', null, null);
		const expr = new Parser(lex(Array.from(src))).parse();
		return { ok: true, expr, diagnostics: [] };
	} catch (e) {
		if (e instanceof ExprSyntaxError) return { ok: false, expr: null, diagnostics: [e.diag] };
		const name = e instanceof Error ? e.name : typeof e;
		return failure('internal', `could not parse expression: ${name}`, 0, null);
	}
}

/** A code point offset (as in diagnostics) as a UTF-16 index into `src`. */
export function codePointToUtf16(src: string, offset: number): number {
	let units = 0;
	let k = 0;
	for (const ch of src) {
		if (k++ >= offset) break;
		units += ch.length;
	}
	return units;
}

// --- Printer ----------------------------------------------------------------------

const P_OR = 1;
const P_AND = 2;
const P_NOT = 3;
const P_CMP = 4;
const P_SUM = 5;
const P_PROD = 6;
const P_ATOM = 7;

function prec(node: Expr): number {
	switch (node.kind) {
		case 'or':
			return P_OR;
		case 'and':
			return P_AND;
		case 'not':
			return P_NOT;
		case 'compare':
			return P_CMP;
		case 'arith':
			return node.op === '+' || node.op === '-' ? P_SUM : P_PROD;
		default:
			return P_ATOM;
	}
}

function textLiteral(value: string): string {
	let out = '"';
	for (const ch of value) {
		const cp = ch.codePointAt(0)!;
		if (ch === '"') out += '\\"';
		else if (ch === '\\') out += '\\\\';
		else if (ch === '\n') out += '\\n';
		else if (ch === '\r') out += '\\r';
		else if (ch === '\t') out += '\\t';
		else if (cp < 0x20 || cp === 0x7f) out += '\\u' + cp.toString(16).padStart(4, '0');
		else out += ch;
	}
	return out + '"';
}

const DECIMAL_TEXT = /^([+-])?(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/;

/** Python's `format(Decimal(value), "f")`, with ".0" added when there is no point. */
function decimalLiteral(value: string): string {
	const m = DECIMAL_TEXT.exec(value.trim());
	if (!m || (m[2] === '' && (m[3] ?? '') === '')) return value;
	const negative = m[1] === '-';
	const frac = m[3] ?? '';
	let coeff = ((m[2] ?? '') + frac).replace(/^0+/, '') || '0';
	let exp = Number(m[4] ?? 0) - frac.length;
	if (coeff === '0' && exp > 0) exp = 0;
	const dotplace = exp + coeff.length;
	let intpart: string;
	let fracpart: string;
	if (dotplace < 0) {
		intpart = '0';
		fracpart = '0'.repeat(-dotplace) + coeff;
	} else if (dotplace > coeff.length) {
		intpart = coeff + '0'.repeat(dotplace - coeff.length);
		fracpart = '';
	} else {
		intpart = coeff.slice(0, dotplace) || '0';
		fracpart = coeff.slice(dotplace);
	}
	coeff = intpart + (fracpart ? '.' + fracpart : '');
	const text = (negative ? '-' : '') + coeff;
	return text.includes('.') ? text : text + '.0';
}

function print(node: Expr, minPrec: number): string {
	let text: string;
	switch (node.kind) {
		case 'int':
			text = String(node.value);
			break;
		case 'decimal':
			text = decimalLiteral(String(node.value));
			break;
		case 'text':
			text = textLiteral(node.value);
			break;
		case 'bool':
			text = node.value ? 'true' : 'false';
			break;
		case 'null':
			text = 'null';
			break;
		case 'ref':
			text = node.id;
			break;
		case 'answered':
			text = `answered(${node.ref.id})`;
			break;
		case 'contains':
			text = `contains(${node.ref.id}, ${print(node.value, P_OR)})`;
			break;
		case 'if':
			text = `if(${print(node.cond, P_OR)}, ${print(node.then, P_OR)}, ${print(node.else, P_OR)})`;
			break;
		case 'or':
			text = node.args.map((a) => print(a, P_AND)).join(' or ');
			break;
		case 'and':
			text = node.args.map((a) => print(a, P_NOT)).join(' and ');
			break;
		case 'not':
			text = 'not ' + print(node.arg, P_NOT);
			break;
		case 'compare':
			text = `${print(node.left, P_SUM)} ${node.op} ${print(node.right, P_SUM)}`;
			break;
		case 'arith': {
			const p = prec(node);
			text = `${print(node.left, p)} ${node.op} ${print(node.right, p + 1)}`;
			break;
		}
		default:
			throw new TypeError(`not an expression node: ${JSON.stringify(node)}`);
	}
	return prec(node) < minPrec ? `(${text})` : text;
}

/** Print an expression in canonical text syntax (`osp_expr.to_text`). */
export function exprToText(expr: Expr): string {
	return print(expr, P_OR);
}
