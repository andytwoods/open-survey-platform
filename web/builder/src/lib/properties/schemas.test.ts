import { describe, expect, it } from 'vitest';
import fixture from './fixtures/property-schemas.json';
import { PropertySchemas, schemaFor } from './schemas.svelte';
import type { PropertySchemasDoc } from './types';

const doc = fixture as unknown as PropertySchemasDoc;

describe('schemaFor', () => {
	it('picks questions by type and other objects by entity', () => {
		expect(schemaFor(doc, 'question', { id: 'q', type: 'multi' })?.type).toBe('multi');
		expect(schemaFor(doc, 'question', { id: 'q', type: 'ranking' })).toBeUndefined();
		expect(schemaFor(doc, 'question', null)).toBeUndefined();
		expect(schemaFor(doc, 'page', {})?.type).toBe('page');
		expect(schemaFor(doc, 'block', {})?.type).toBe('block');
		expect(schemaFor(doc, 'survey', {})?.type).toBe('survey');
		expect(schemaFor(null, 'page', {})).toBeUndefined();
	});
});

describe('PropertySchemas', () => {
	it('loads once and keeps the document', async () => {
		const s = new PropertySchemas();
		let calls = 0;
		const fetcher = async () => {
			calls++;
			return { data: doc };
		};
		await Promise.all([s.load(fetcher), s.load(fetcher)]);
		await s.load(fetcher);
		expect(calls).toBe(1);
		expect(s.doc?.schemas.length).toBe(doc.schemas.length);
	});

	it('reports a bad response or a network failure, and can retry', async () => {
		const s = new PropertySchemas();
		await s.load(async () => ({ data: { nope: true } }));
		expect(s.error).toMatch(/could not be loaded/);
		await s.load(() => Promise.reject(new Error('offline')));
		expect(s.doc).toBeNull();
		await s.load(async () => ({ data: doc }));
		expect(s.error).toBeNull();
		expect(s.doc).not.toBeNull();
	});
});
