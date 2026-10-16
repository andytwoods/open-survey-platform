/**
 * The local copy (runtime-design §5.2): one record per survey slug in IndexedDB, written on
 * every change. When IndexedDB is blocked (private browsing, disabled storage) the app
 * falls back to {@link MemoryStore}: nothing survives a refresh, and the UI says so.
 */
import type { Plan, ResponseRecord, Snapshot } from '@osp/engine';
import type { SaveMode } from './api';

export interface LocalRecord {
	slug: string;
	sessionId: string;
	resumeToken: string;
	sessionSeed: number;
	assigned: Record<string, string | number>;
	planUrl: string;
	planChecksum: string;
	saveMode: SaveMode;
	/** The plan itself, so a refresh while offline still renders. */
	plan: Plan | null;
	/** The newest local engine snapshot (null only before the engine has started). */
	snapshot: Snapshot | null;
	/** Last server revision that acknowledged a write (or that we reconciled to). */
	serverRevision: number;
	/** Engine revision of the snapshot the server holds at `serverRevision`. */
	syncedEngineRev: number;
	/**
	 * A save that was sent but not acknowledged. It is resent unchanged (the server treats
	 * an identical retry as a replay), so a lost reply never turns into a false conflict.
	 */
	inflight: { base: number; snapshot: Snapshot } | null;
	/** Local copies that lost to the server copy (two devices); kept for the conflict record. */
	conflicts: Array<{ at: number; serverRevision: number; snapshot: Snapshot }>;
	/** The ResponseRecord being submitted: resent unchanged until the server acknowledges. */
	submitting: ResponseRecord | null;
	createdAt: number;
	updatedAt: number;
}

export interface LocalStore {
	readonly kind: 'indexeddb' | 'memory';
	get(slug: string): Promise<LocalRecord | undefined>;
	put(rec: LocalRecord): Promise<void>;
	delete(slug: string): Promise<void>;
	/** Delete records not touched since `before` (ms). Returns how many went. */
	purge(before: number): Promise<number>;
}

/** Plain JSON copy: no Svelte proxies or shared references reach IndexedDB. */
function plain<T>(x: T): T {
	return JSON.parse(JSON.stringify(x)) as T;
}

export class MemoryStore implements LocalStore {
	readonly kind = 'memory' as const;
	private recs = new Map<string, LocalRecord>();
	async get(slug: string) {
		const r = this.recs.get(slug);
		return r ? plain(r) : undefined;
	}
	async put(rec: LocalRecord) {
		this.recs.set(rec.slug, plain(rec));
	}
	async delete(slug: string) {
		this.recs.delete(slug);
	}
	async purge(before: number) {
		let n = 0;
		for (const [k, r] of this.recs) if (r.updatedAt < before && this.recs.delete(k)) n++;
		return n;
	}
}

const DB = 'osp-runtime';
const STORE = 'sessions';

function req<T>(r: IDBRequest<T>): Promise<T> {
	return new Promise((resolve, reject) => {
		r.onsuccess = () => resolve(r.result);
		r.onerror = () => reject(r.error);
	});
}

class IdbStore implements LocalStore {
	readonly kind = 'indexeddb' as const;
	constructor(private db: IDBDatabase) {}

	private tx(mode: IDBTransactionMode) {
		return this.db.transaction(STORE, mode).objectStore(STORE);
	}
	private done(t: IDBTransaction): Promise<void> {
		return new Promise((resolve, reject) => {
			t.oncomplete = () => resolve();
			t.onerror = () => reject(t.error);
			t.onabort = () => reject(t.error ?? new Error('aborted'));
		});
	}
	async get(slug: string) {
		return (await req(this.tx('readonly').get(slug))) as LocalRecord | undefined;
	}
	async put(rec: LocalRecord) {
		// Transactions on one store complete in the order they were created, so the last
		// put always wins. `durability: strict` asks the browser to flush to disk.
		const t = this.db.transaction(STORE, 'readwrite', { durability: 'strict' });
		t.objectStore(STORE).put(plain(rec));
		await this.done(t);
	}
	async delete(slug: string) {
		const t = this.db.transaction(STORE, 'readwrite', { durability: 'strict' });
		t.objectStore(STORE).delete(slug);
		await this.done(t);
	}
	async purge(before: number) {
		const all = (await req(this.tx('readonly').getAll())) as LocalRecord[];
		const old = all.filter((r) => !(r.updatedAt >= before));
		for (const r of old) await this.delete(r.slug);
		return old.length;
	}
}

/**
 * Open IndexedDB and prove it works with a test write. Resolves to null when storage is
 * blocked or broken (private mode, quota 0, disabled), or when it does not answer in time.
 */
export async function openIndexedDb(idb: IDBFactory | undefined = globalThis.indexedDB, timeoutMs = 3000): Promise<LocalStore | null> {
	if (!idb) return null;
	const attempt = (async () => {
		const open = idb.open(DB, 1);
		open.onupgradeneeded = () => {
			if (!open.result.objectStoreNames.contains(STORE)) open.result.createObjectStore(STORE, { keyPath: 'slug' });
		};
		const db = await req(open);
		const store = new IdbStore(db);
		const probe = { slug: '\u0000probe', updatedAt: 0 } as unknown as LocalRecord;
		await store.put(probe);
		await store.delete(probe.slug);
		return store as LocalStore;
	})();
	const timeout = new Promise<null>((r) => setTimeout(() => r(null), timeoutMs));
	try {
		return await Promise.race([attempt, timeout]);
	} catch {
		return null;
	}
}
