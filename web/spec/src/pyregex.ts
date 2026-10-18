/**
 * Researcher-supplied redirect param patterns are Python `re` patterns (osp_spec.hooks
 * `_pattern_ok`, `re.fullmatch`). This translates the Python dialect (str patterns, no
 * flags) to a JavaScript `v`-flag RegExp with the same meaning, following sre_parse: its
 * escapes (`\d`, `\w`, `\s` and `\b` Unicode-aware; octal escapes and group references by
 * its rules), `.` not matching `\n`, `$` also matching before a final `\n`, literal `{`
 * where no repeat follows, `]` first in a class, comments, atomic groups and possessive
 * repeats (as lookahead + backreference), `(?P<name>…)` and `(?P=name)`, scoped flags
 * (`i`, `m`, `s`, `x`, `a`, `u`), and the errors Python raises (unbalanced parentheses,
 * nothing to repeat, multiple repeat, bad escapes, bad ranges, unknown or open group
 * references, global flags not at the start, repeat counts over MAXREPEAT). Not translated
 * (README, "Differences"): `\N{name}`, conditionals `(?(1)…)` and Python's fixed-width
 * look-behind rule.
 */

import { DIGIT_CLASS, PY_SPACE_CLASS } from './py.ts';

const MAX_REPEAT = 4294967295;
const WORD = '\\p{L}\\p{N}_';
const OCT = /[0-7]/;
const DIGIT = /[0-9]/;
const HEX = /^[0-9A-Fa-f]+$/;
const QUANT = /^\{([0-9]*)(,([0-9]*))?\}/;

class Invalid extends Error {}

const cpEscape = (cp: number): string => `\\u{${cp.toString(16)}}`;

interface Flags {
	i: boolean;
	m: boolean;
	s: boolean;
	x: boolean;
	a: boolean;
}

interface Group {
	kind: 'capture' | 'other' | 'atomic';
	num: number;
	start: number; // out index of the group's first character
	jsName?: string;
	flags: Flags; // the flags outside the group, restored at its end
}

const START = '(?<![\\s\\S])';
const END_ = '(?![\\s\\S])';
const PY_WS = new Set(' \t\n\r\v\f');

class Translator {
	private readonly cps: string[];
	private i = 0;
	private out = '';
	private readonly stack: Group[] = [];
	private opened = 0; // capture groups opened so far
	private readonly closed = new Set<number>();
	private readonly names = new Map<string, number>();
	private readonly jsNames = new Map<number, string>();
	private atomics = 0;
	private lastAtom = -1; // out index where the last repeatable item starts; -1: none
	private afterRepeat = false;
	private flags: Flags = { i: false, m: false, s: false, x: false, a: false };

	constructor(source: string) {
		this.cps = Array.from(source);
	}

	private peek(k = 0): string | undefined {
		return this.cps[this.i + k];
	}

	private next(): string {
		const c = this.cps[this.i++];
		if (c === undefined) throw new Invalid();
		return c;
	}

	run(): string {
		while (this.i < this.cps.length) this.item();
		if (this.stack.length) throw new Invalid(); // missing ), unterminated subpattern
		return this.out;
	}

	private atom(js: string): void {
		this.lastAtom = this.out.length;
		this.out += js;
		this.afterRepeat = false;
	}

	private noAtom(js: string): void {
		this.out += js;
		this.lastAtom = -1;
		this.afterRepeat = false;
	}

	private word(): string {
		return this.flags.a ? 'A-Za-z0-9_' : WORD;
	}

	private item(): void {
		const c = this.next();
		if (this.flags.x && PY_WS.has(c)) return;
		if (this.flags.x && c === '#') {
			while (this.i < this.cps.length && this.next() !== '\n');
			return;
		}
		if (c === '\\') return this.escape();
		if (c === '[') return this.atom(this.charClass());
		if (c === '(') return this.open();
		if (c === ')') return this.close();
		if (c === '|') return this.noAtom('|');
		if (c === '^') return this.noAtom(this.flags.m ? `(?:${START}|(?<=\\n))` : START);
		if (c === '$') return this.noAtom(this.flags.m ? `(?=\\n|${END_})` : `(?=\\n?${END_})`);
		if (c === '.') return this.atom(this.flags.s ? '[\\s\\S]' : '[^\\n]');
		if (c === '*' || c === '+' || c === '?') return this.repeat(c);
		if (c === '{') {
			const m = QUANT.exec(this.cps.slice(this.i - 1, this.i + 40).join(''));
			if (m && m[0] !== '{}') {
				this.i += m[0].length - 1;
				const lo = m[1]!;
				const hi = m[2] === undefined ? lo : m[3]!;
				if ((lo && Number(lo) >= MAX_REPEAT) || (hi && Number(hi) >= MAX_REPEAT)) throw new Invalid();
				if (lo && hi && Number(hi) < Number(lo)) throw new Invalid();
				return this.repeat('{' + (lo || '0') + (m[2] === undefined ? '' : ',' + hi) + '}');
			}
			return this.atom('\\{');
		}
		return this.atom(cpEscape(c.codePointAt(0)!));
	}

	private repeat(q: string): void {
		if (this.lastAtom < 0 || this.afterRepeat) throw new Invalid(); // nothing to repeat / multiple repeat
		let mod = '';
		if (this.peek() === '?') {
			this.i++;
			mod = '?';
		} else if (this.peek() === '+') {
			this.i++;
			mod = '+';
		}
		if (mod === '+') {
			const body = this.out.slice(this.lastAtom) + q;
			const name = `__osp_a${++this.atomics}`;
			this.out = this.out.slice(0, this.lastAtom) + `(?=(?<${name}>${body}))\\k<${name}>`;
		} else this.out += q + mod;
		this.afterRepeat = true;
	}

	private groupName(end: string): string {
		let name = '';
		for (;;) {
			const c = this.next();
			if (c === end) break;
			name += c;
		}
		if (!/^[\p{ID_Start}_][\p{ID_Continue}]*$/u.test(name)) throw new Invalid();
		return name;
	}

	private open(): void {
		const start = this.out.length;
		if (this.peek() !== '?') {
			const num = ++this.opened;
			const jsName = `__osp_g${num}`;
			this.jsNames.set(num, jsName);
			this.stack.push({ kind: 'capture', num, start, jsName, flags: this.flags });
			return this.noAtom(`(?<${jsName}>`);
		}
		this.i++;
		const c = this.next();
		if (c === ':') return this.push('other', start, '(?:');
		if (c === '=' || c === '!') return this.push('other', start, `(?${c}`);
		if (c === '>') {
			const name = `__osp_a${++this.atomics}`;
			this.stack.push({ kind: 'atomic', num: 0, start, jsName: name, flags: this.flags });
			return this.noAtom(`(?=(?<${name}>`);
		}
		if (c === '#') {
			while (this.next() !== ')');
			return; // a comment changes nothing (not even what the last atom is)
		}
		if (c === '<') {
			const d = this.next();
			if (d !== '=' && d !== '!') throw new Invalid();
			return this.push('other', start, `(?<${d}`);
		}
		if (c === 'P') {
			const d = this.next();
			if (d === '<') {
				const name = this.groupName('>');
				if (this.names.has(name)) throw new Invalid();
				const num = ++this.opened;
				this.names.set(name, num);
				this.jsNames.set(num, name);
				this.stack.push({ kind: 'capture', num, start, jsName: name, flags: this.flags });
				return this.noAtom(`(?<${name}>`);
			}
			if (d === '=') {
				const name = this.groupName(')');
				const num = this.names.get(name);
				if (num === undefined || !this.closed.has(num)) throw new Invalid();
				return this.atom(`\\k<${name}>`);
			}
			throw new Invalid();
		}
		if (c === '(') {
			// A conditional: Python accepts it, JavaScript has none (README).
			throw new Invalid();
		}
		// Flags: `(?flags)` is a global flag, never at the start inside `(?:…)`: an error.
		let flags = c;
		while (this.peek() !== undefined && /[aiLmsux-]/.test(this.peek()!)) flags += this.next();
		if (!/^[aiLmsux-]+$/.test(flags)) throw new Invalid();
		const d = this.next();
		if (d !== ':') throw new Invalid();
		// sre_parse: no letter both on and off; `a`, `L` and `u` cannot be turned off, `L` is
		// for bytes patterns only, and `a` and `u` exclude each other.
		const [on, off = ''] = flags.split('-') as [string, string | undefined];
		if (flags.split('-').length > 2 || (flags.includes('-') && off === '')) throw new Invalid();
		if ([...off].some((ch) => on.includes(ch))) throw new Invalid(); // turned on and off
		if (/[aLu]/.test(off) || on.includes('L') || (on.includes('a') && on.includes('u'))) throw new Invalid();
		const outer = this.flags;
		const f: Flags = { ...outer };
		for (const k of 'imsx' as const) {
			if (on.includes(k)) f[k as keyof Flags] = true;
			if (off.includes(k)) f[k as keyof Flags] = false;
		}
		if (on.includes('a')) f.a = true;
		if (on.includes('u')) f.a = false;
		this.push('other', start, f.i ? '(?i:' : '(?-i:');
		this.flags = f;
	}

	private push(kind: 'other', start: number, js: string): void {
		this.stack.push({ kind, num: 0, start, flags: this.flags });
		this.noAtom(js);
	}

	private close(): void {
		const g = this.stack.pop();
		if (g === undefined) throw new Invalid(); // unbalanced parenthesis
		if (g.kind === 'atomic') this.out += `))\\k<${g.jsName!}>`;
		else this.out += ')';
		if (g.kind === 'capture') this.closed.add(g.num);
		this.flags = g.flags;
		this.lastAtom = g.start;
		this.afterRepeat = false;
	}

	/** An escape outside a class (sre_parse._escape). */
	private escape(): void {
		const c = this.next();
		switch (c) {
			case 'A':
				return this.noAtom(START);
			case 'Z':
				return this.noAtom(END_);
			case 'b': {
				const w = this.word();
				return this.noAtom(`(?:(?<=[${w}])(?![${w}])|(?<![${w}])(?=[${w}]))`);
			}
			case 'B': {
				const w = this.word();
				return this.noAtom(`(?:(?<=[${w}])(?=[${w}])|(?<![${w}])(?![${w}]))`);
			}
		}
		if (DIGIT.test(c) && c !== '0') {
			let digits = c;
			if (this.peek() !== undefined && DIGIT.test(this.peek()!)) {
				digits += this.next();
				if (OCT.test(digits[0]!) && OCT.test(digits[1]!) && this.peek() !== undefined && OCT.test(this.peek()!)) {
					const v = parseInt(digits + this.next(), 8);
					if (v > 0o377) throw new Invalid();
					return this.atom(cpEscape(v));
				}
			}
			const group = Number(digits);
			if (group > this.opened || !this.closed.has(group)) throw new Invalid();
			return this.atom(`\\k<${this.jsNames.get(group)!}>`);
		}
		this.atom(this.common(c, false));
	}

	/** Escapes shared by classes and the pattern body; returns a JS class item or atom. */
	private common(c: string, inClass: boolean): string {
		const ascii = this.flags.a;
		const digits = ascii ? '0-9' : DIGIT_CLASS;
		const space = ascii ? ' \\t\\n\\r\\f\\v' : PY_SPACE_CLASS;
		const word = this.word();
		switch (c) {
			case 'd':
				return inClass ? digits : `[${digits}]`;
			case 'D':
				return `[^${digits}]`;
			case 's':
				return inClass ? space : `[${space}]`;
			case 'S':
				return `[^${space}]`;
			case 'w':
				return inClass ? word : `[${word}]`;
			case 'W':
				return `[^${word}]`;
		}
		const cp = this.literalEscape(c, inClass);
		return cpEscape(cp);
	}

	/** The code point of a literal escape, or Invalid (sre_parse: bad escape). */
	private literalEscape(c: string, inClass: boolean): number {
		const simple: Record<string, number> = { a: 7, f: 12, n: 10, r: 13, t: 9, v: 11 };
		if (c in simple) return simple[c]!;
		if (inClass && c === 'b') return 8;
		if (c === 'x' || c === 'u' || c === 'U') {
			const n = c === 'x' ? 2 : c === 'u' ? 4 : 8;
			const hex = this.cps.slice(this.i, this.i + n).join('');
			if (hex.length !== n || !HEX.test(hex)) throw new Invalid();
			this.i += n;
			const v = parseInt(hex, 16);
			if (v > 0x10ffff) throw new Invalid();
			return v;
		}
		if (OCT.test(c)) {
			let digits = c;
			for (let k = 0; k < 2 && this.peek() !== undefined && OCT.test(this.peek()!); k++) digits += this.next();
			const v = parseInt(digits, 8);
			if (v > 0o377) throw new Invalid();
			return v;
		}
		if (/[0-9A-Za-z]/.test(c)) throw new Invalid(); // \N{…} included (README)
		return c.codePointAt(0)!;
	}

	/** `[…]` (sre_parse: the `]` right after `[` or `[^` is literal). */
	private charClass(): string {
		let js = '[';
		if (this.peek() === '^') {
			this.i++;
			js += '^';
		}
		let first = true;
		for (;;) {
			const c = this.next();
			if (c === ']' && !first) break;
			first = false;
			const a = this.classItem(c);
			if (this.peek() === '-') {
				this.i++;
				const d = this.next();
				if (d === ']') {
					js += a.js + cpEscape(45);
					break;
				}
				const b = this.classItem(d);
				if (a.cp === null || b.cp === null || b.cp < a.cp) throw new Invalid(); // bad character range
				js += `${cpEscape(a.cp)}-${cpEscape(b.cp)}`;
			} else js += a.js;
		}
		return js + ']';
	}

	private classItem(c: string): { js: string; cp: number | null } {
		if (c !== '\\') return { js: cpEscape(c.codePointAt(0)!), cp: c.codePointAt(0)! };
		const e = this.next();
		if ('dDsSwW'.includes(e)) return { js: this.common(e, true), cp: null };
		if (e === '8' || e === '9') throw new Invalid();
		const cp = this.literalEscape(e, true);
		return { js: cpEscape(cp), cp };
	}
}

const cache = new Map<string, RegExp | null>();

/** `re.compile(f"(?:{pattern})")` as a JavaScript RegExp that `re.fullmatch` would agree
 * with, or null where Python refuses the pattern. */
export function compileFull(pattern: string): RegExp | null {
	const hit = cache.get(pattern);
	if (hit !== undefined) return hit;
	let re: RegExp | null;
	try {
		re = new RegExp(`^${new Translator(`(?:${pattern})`).run()}$`, 'v');
	} catch {
		re = null;
	}
	if (cache.size > 1000) cache.clear();
	cache.set(pattern, re);
	return re;
}
