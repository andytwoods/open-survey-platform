/**
 * Pure helpers for the question widgets: text, direction, number and date formats.
 * No DOM access, so they are unit-tested directly (locale.test.ts).
 */
import type { Text, WidgetMessages } from './types';

export const defaultMessages: WidgetMessages = {
	required: 'Required',
	day: 'Day',
	month: 'Month',
	year: 'Year',
	notAnswered: 'Not answered',
	sliderValue: 'Value',
	sliderTypeValue: 'Or type a number',
	invalidInteger: 'Enter a whole number, like 12.',
	invalidDecimal: 'Enter a number, like {example}.',
	outOfRange: 'Enter a number from {min} to {max}.',
	incompleteDate: 'Enter a day, month and year.',
	invalidDate: 'Enter a real date.',
	revealed: 'New question: {label}'
};

export function messagesFor(overrides?: Partial<WidgetMessages>): WidgetMessages {
	return { ...defaultMessages, ...overrides };
}

/** Replace `{name}` placeholders. Unknown names are left as they are. */
export function fill(template: string, values: Record<string, string | number>): string {
	return template.replace(/\{(\w+)\}/g, (m, k: string) => (k in values ? String(values[k]) : m));
}

/** Plain text of a label (for announcements and ids, never for rendering markup). */
export function plainText(text: Text | undefined): string {
	if (text === undefined) return '';
	if (typeof text === 'string') return text;
	return text.map((s) => s.text).join('');
}

export function isEmptyText(text: Text | undefined): boolean {
	return plainText(text).trim() === '';
}

/** A choice value made safe for use inside a DOM id (distinct values stay distinct). */
export function safeId(value: string): string {
	return value.replace(/[^A-Za-z0-9_-]/g, (c) => `_${c.codePointAt(0)!.toString(16)}_`);
}

const RTL_LANGS = new Set(['ar', 'arc', 'ckb', 'dv', 'fa', 'he', 'iw', 'ks', 'ps', 'sd', 'ug', 'ur', 'yi']);

/** Writing direction for a BCP 47 tag; undefined when no language is given. */
export function dirFor(lang: string | undefined): 'ltr' | 'rtl' | undefined {
	if (!lang) return undefined;
	const [primary, ...rest] = lang.toLowerCase().split(/[-_]/);
	if (rest.includes('arab') || rest.includes('hebr')) return 'rtl';
	if (rest.includes('latn') || rest.includes('cyrl')) return 'ltr';
	return RTL_LANGS.has(primary) ? 'rtl' : 'ltr';
}

function safeLocale(lang: string | undefined): string | undefined {
	if (!lang) return undefined;
	try {
		return Intl.getCanonicalLocales(lang)[0];
	} catch {
		return undefined;
	}
}

/** The decimal separator participants of `lang` expect ("." or "," or "٫"). */
export function decimalSeparator(lang: string | undefined): string {
	const parts = new Intl.NumberFormat(safeLocale(lang)).formatToParts(1.5);
	return parts.find((p) => p.type === 'decimal')?.value ?? '.';
}

/** Arabic-Indic and Extended Arabic-Indic digits, and the Arabic decimal separator, to ASCII. */
function asciiDigits(s: string): string {
	return s.replace(/[٠-٩۰-۹]/g, (d) =>
		String((d.charCodeAt(0) & 0xf) % 10)
	);
}

function normaliseSigns(s: string): string {
	return asciiDigits(s)
		.replace(/[\s\u00a0\u202f]/g, '')
		.replace(/[−‒–]/g, '-');
}

function stripLeadingZeros(intPart: string): string {
	const s = intPart.replace(/^0+(?=\d)/, '');
	return s === '' ? '0' : s;
}

/**
 * Parse a typed integer. Returns the canonical string ("-12"), `null` for empty input,
 * or `undefined` when the text is not a whole number.
 */
export function parseInteger(raw: string): string | null | undefined {
	const s = normaliseSigns(raw);
	if (s === '') return null;
	const m = /^([+-]?)(\d+)$/.exec(s);
	if (!m) return undefined;
	const digits = stripLeadingZeros(m[2]);
	return m[1] === '-' && digits !== '0' ? `-${digits}` : digits;
}

/**
 * Parse a typed decimal, keeping it exact. Accepts the locale's separator or ".", or
 * "٫" (Arabic), but only one of them, and no grouping. Returns the canonical string with
 * "." ("3.50", "-0.5"), `null` for empty input, or `undefined` when it is not a number.
 */
export function parseDecimal(raw: string, lang?: string): string | null | undefined {
	let s = normaliseSigns(raw);
	if (s === '') return null;
	const sep = decimalSeparator(lang);
	s = s.replace(/٫/g, '.');
	if (sep !== '.') s = s.split(sep).join('.');
	else if (/^[+-]?\d*,\d+$/.test(s)) s = s.replace(',', '.');
	const m = /^([+-]?)(\d*)(?:\.(\d*))?$/.exec(s);
	if (!m || (m[2] === '' && (m[3] ?? '') === '')) return undefined;
	const intPart = stripLeadingZeros(m[2] || '0');
	const frac = m[3] ?? '';
	const body = frac === '' ? intPart : `${intPart}.${frac}`;
	const zero = /^0(\.0*)?$/.test(body);
	return m[1] === '-' && !zero ? `-${body}` : body;
}

/** Show a canonical decimal with the participant's separator. */
export function formatDecimal(value: string | null | undefined, lang?: string): string {
	if (value === null || value === undefined) return '';
	const sep = decimalSeparator(lang);
	return sep === '.' ? value : value.replace('.', sep);
}

export type DatePart = 'day' | 'month' | 'year';

/** The order of day / month / year fields for `lang` (e.g. en-US: month, day, year). */
export function dateOrder(lang: string | undefined): DatePart[] {
	const parts = new Intl.DateTimeFormat(safeLocale(lang), {
		day: 'numeric',
		month: 'numeric',
		year: 'numeric'
	}).formatToParts(new Date(2000, 10, 22));
	const order = parts
		.map((p) => p.type)
		.filter((t): t is DatePart => t === 'day' || t === 'month' || t === 'year');
	return order.length === 3 && new Set(order).size === 3 ? order : ['day', 'month', 'year'];
}

export interface DateFields {
	day: string;
	month: string;
	year: string;
}

export type DateCheck =
	| { kind: 'empty' }
	| { kind: 'incomplete' }
	| { kind: 'invalid' }
	| { kind: 'valid'; iso: string };

const pad = (n: number, w: number) => String(n).padStart(w, '0');

/** Strict check of three typed fields: digits only, a 4-digit year, a real calendar date. */
export function checkDate(fields: DateFields): DateCheck {
	const d = asciiDigits(fields.day.trim());
	const m = asciiDigits(fields.month.trim());
	const y = asciiDigits(fields.year.trim());
	if (d === '' && m === '' && y === '') return { kind: 'empty' };
	if (d === '' || m === '' || y === '') return { kind: 'incomplete' };
	if (!/^\d{1,2}$/.test(d) || !/^\d{1,2}$/.test(m) || !/^\d{4}$/.test(y)) {
		return { kind: 'invalid' };
	}
	const day = Number(d);
	const month = Number(m);
	const year = Number(y);
	if (month < 1 || month > 12 || day < 1) return { kind: 'invalid' };
	const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
	if (day > daysInMonth || year < 1) return { kind: 'invalid' };
	const iso = `${pad(year, 4)}-${pad(month, 2)}-${pad(day, 2)}`;
	return { kind: 'valid', iso };
}

/** Split an ISO date into fields (no padding is added for display). */
export function isoToFields(iso: string | null | undefined): DateFields {
	const m = iso ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso) : null;
	if (!m) return { day: '', month: '', year: '' };
	return { year: m[1], month: String(Number(m[2])), day: String(Number(m[3])) };
}
