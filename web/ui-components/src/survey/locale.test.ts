import { describe, expect, it } from 'vitest';
import {
	checkDate,
	dateOrder,
	decimalSeparator,
	dirFor,
	fill,
	formatDecimal,
	isoToFields,
	parseDecimal,
	parseInteger,
	plainText,
	safeId
} from './locale';

describe('numbers', () => {
	it('parses integers to a canonical string', () => {
		expect(parseInteger('')).toBeNull();
		expect(parseInteger('  ')).toBeNull();
		expect(parseInteger('42')).toBe('42');
		expect(parseInteger('007')).toBe('7');
		expect(parseInteger('-12')).toBe('-12');
		expect(parseInteger('−12')).toBe('-12'); // U+2212 minus
		expect(parseInteger('-0')).toBe('0');
		expect(parseInteger('+3')).toBe('3');
		expect(parseInteger('١٢')).toBe('12'); // Arabic-Indic digits
		expect(parseInteger('1.5')).toBeUndefined();
		expect(parseInteger('12a')).toBeUndefined();
		expect(parseInteger('1e3')).toBeUndefined();
	});

	it('knows the locale decimal separator', () => {
		expect(decimalSeparator('en')).toBe('.');
		expect(decimalSeparator('de')).toBe(',');
		expect(decimalSeparator(undefined)).toMatch(/^[.,٫]$/);
		expect(decimalSeparator('not a tag!!')).toMatch(/^[.,٫]$/);
	});

	it('parses decimals exactly, never via a float', () => {
		expect(parseDecimal('3.50', 'en')).toBe('3.50');
		expect(parseDecimal('0.1', 'en')).toBe('0.1');
		expect(parseDecimal('12345678901234567890.123456789', 'en')).toBe(
			'12345678901234567890.123456789'
		);
		expect(parseDecimal('.5', 'en')).toBe('0.5');
		expect(parseDecimal('5.', 'en')).toBe('5');
		expect(parseDecimal('-0.0', 'en')).toBe('0.0');
		expect(parseDecimal('3,5', 'en')).toBe('3.5'); // a lone comma is a decimal comma
		expect(parseDecimal('3,5', 'de')).toBe('3.5');
		expect(parseDecimal('3.5', 'de')).toBe('3.5');
		expect(parseDecimal('٣٫٥', 'ar')).toBe('3.5');
		expect(parseDecimal('1.000,5', 'de')).toBeUndefined(); // no grouping
		expect(parseDecimal('1,000.5', 'en')).toBeUndefined();
		expect(parseDecimal('.', 'en')).toBeUndefined();
		expect(parseDecimal('abc', 'en')).toBeUndefined();
		expect(parseDecimal('', 'en')).toBeNull();
	});

	it('shows canonical decimals with the locale separator', () => {
		expect(formatDecimal('3.50', 'de')).toBe('3,50');
		expect(formatDecimal('3.50', 'en')).toBe('3.50');
		expect(formatDecimal(null, 'de')).toBe('');
	});
});

describe('dates', () => {
	it('orders fields by locale', () => {
		expect(dateOrder('en-GB')).toEqual(['day', 'month', 'year']);
		expect(dateOrder('en-US')).toEqual(['month', 'day', 'year']);
		expect(dateOrder('de')).toEqual(['day', 'month', 'year']);
		expect(dateOrder('ja')).toEqual(['year', 'month', 'day']);
		expect(dateOrder('???')).toHaveLength(3);
	});

	it('validates strictly', () => {
		const f = (day: string, month: string, year: string) => checkDate({ day, month, year });
		expect(f('', '', '')).toEqual({ kind: 'empty' });
		expect(f('1', '', '2020')).toEqual({ kind: 'incomplete' });
		expect(f('29', '2', '2024')).toEqual({ kind: 'valid', iso: '2024-02-29' });
		expect(f('29', '2', '2023')).toEqual({ kind: 'invalid' });
		expect(f('31', '4', '2020')).toEqual({ kind: 'invalid' });
		expect(f('0', '1', '2020')).toEqual({ kind: 'invalid' });
		expect(f('1', '13', '2020')).toEqual({ kind: 'invalid' });
		expect(f('1', '1', '20')).toEqual({ kind: 'invalid' }); // 4-digit year only
		expect(f('1.', '1', '2020')).toEqual({ kind: 'invalid' });
		expect(f('٥', '٦', '٢٠٢٠')).toEqual({ kind: 'valid', iso: '2020-06-05' });
	});

	it('splits ISO dates for editing', () => {
		expect(isoToFields('2024-02-09')).toEqual({ day: '9', month: '2', year: '2024' });
		expect(isoToFields(null)).toEqual({ day: '', month: '', year: '' });
		expect(isoToFields('garbage')).toEqual({ day: '', month: '', year: '' });
	});
});

describe('text', () => {
	it('derives direction from the language tag', () => {
		expect(dirFor(undefined)).toBeUndefined();
		expect(dirFor('ar')).toBe('rtl');
		expect(dirFor('he-IL')).toBe('rtl');
		expect(dirFor('az-Arab')).toBe('rtl');
		expect(dirFor('de')).toBe('ltr');
		expect(dirFor('ku-Latn')).toBe('ltr');
	});

	it('flattens segments and fills templates', () => {
		expect(plainText([{ text: 'How ' }, { text: 'often', strong: true }, { text: '?' }])).toBe(
			'How often?'
		);
		expect(fill('From {min} to {max} {x}', { min: 1, max: 9 })).toBe('From 1 to 9 {x}');
	});

	it('makes ids safe and keeps them distinct', () => {
		expect(safeId('a b')).not.toBe(safeId('a_b'));
		expect(safeId('x"><script>')).toMatch(/^[A-Za-z0-9_-]+$/);
	});
});
