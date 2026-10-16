import { IDBFactory } from 'fake-indexeddb';
import { describe, expect, it } from 'vitest';
import { openIndexedDb, type LocalRecord } from '../src/lib/storage';

const rec = (slug: string, updatedAt: number) => ({ slug, updatedAt, sessionId: 's1' }) as unknown as LocalRecord;

describe('IndexedDB store', () => {
	it('round-trips, overwrites, deletes and purges old copies', async () => {
		const store = await openIndexedDb(new IDBFactory());
		expect(store?.kind).toBe('indexeddb');
		await store!.put(rec('a', 10));
		await store!.put({ ...rec('a', 20), sessionId: 's2' });
		await store!.put(rec('b', 1));
		expect((await store!.get('a'))?.sessionId).toBe('s2');
		expect(await store!.purge(5)).toBe(1);
		expect(await store!.get('b')).toBeUndefined();
		await store!.delete('a');
		expect(await store!.get('a')).toBeUndefined();
	});

	it('reports blocked storage as null instead of throwing', async () => {
		const broken = {
			open() {
				throw new DOMException('blocked', 'SecurityError');
			}
		} as unknown as IDBFactory;
		expect(await openIndexedDb(broken)).toBeNull();
		expect(await openIndexedDb(undefined)).toBeNull();
	});
});
