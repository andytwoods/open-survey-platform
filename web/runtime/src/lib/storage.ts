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
	/** Where an end-only session keeps its copy, as the server said at start/resume. */
	localCopy?: 'browser' | 'memory';
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

/**
 * A synchronous last-moment copy for `pagehide`: IndexedDB writes are asynchronous, so a
 * refresh within milliseconds of an answer can beat them; localStorage is synchronous.
 * Read once on the next load (used only if it extends the IndexedDB copy), then removed.
 */
export interface SyncBackup {
	write(slug: string, sessionId: string, snapshot: Snapshot): void;
	take(slug: string, sessionId: string): Snapshot | null;
}

export function localStorageBackup(ls?: Storage): SyncBackup | undefined {
	let store: Storage | undefined = ls;
	try {
		store ??= globalThis.localStorage;
	} catch {
		return undefined; // access itself throws when storage is blocked
	}
	if (!store) return undefined;
	const s = store;
	const key = (slug: string) => `osp-runtime:last:${slug}`;
	return {
		write(slug, sessionId, snapshot) {
			try {
				s.setItem(key(slug), JSON.stringify({ sessionId, snapshot }));
			} catch {
				/* blocked or full: the IndexedDB copy still stands */
			}
		},
		take(slug, sessionId) {
			try {
				const raw = s.getItem(key(slug));
				s.removeItem(key(slug));
				if (!raw) return null;
				const v = JSON.parse(raw) as { sessionId?: string; snapshot?: Snapshot };
				return v.sessionId === sessionId && v.snapshot ? v.snapshot : null;
			} catch {
				return null;
			}
		}
	};
}

/**
 * Where the session is, when there is no local copy to say so (IndexedDB blocked, or an
 * `end-only` survey kept in memory): the session id and resume token, so a refresh asks the
 * server instead of starting a new session (runtime-design §5 step 7, R4-3). Never answers:
 * in `end-only` mode at most the session's start event (seed, conditions, language, device,
 * URL parameters, all of them already in this tab), so a refresh can `restart()` it (R6-5).
 *
 * Kept in `sessionStorage` (this tab only, gone when it closes), or, when that is blocked
 * too, in the URL fragment (never sent to the server; the address bar then holds the token,
 * as a resume link does). An `every-page` session, whose answers are on the server anyway,
 * may also be found from another tab later (`localStorage`, the device pointer), as its
 * IndexedDB record would be; an `end-only` one never: closing the window loses it (§5.0).
 */
export interface PointerRecord {
	sessionId: string;
	resumeToken: string;
	/** The engine's start event (end-only memory sessions), for `restart()`. */
	start?: unknown;
	/**
	 * every-page, no durable copy (R9-1): the engine revision of the newest snapshot the
	 * page sent with `keepalive` as it was hidden, not yet acknowledged. A number only,
	 * never answers. The reloaded page waits briefly for the server to reach it, since its
	 * resume can overtake the dead page's last save. Not kept in the URL fragment.
	 */
	pending?: number;
}

export interface SessionPointer {
	readonly kind: 'localStorage' | 'sessionStorage' | 'fragment';
	get(slug: string): PointerRecord | null;
	set(slug: string, p: PointerRecord): void;
	clear(slug: string): void;
}

const POINTER_KEY = (slug: string) => `osp-runtime:session:${slug}`;
const FRAGMENT_KEY = 'osp-session';

function asPointer(x: unknown): PointerRecord | null {
	if (!x || typeof x !== 'object') return null;
	const p = x as PointerRecord;
	return typeof p.sessionId === 'string' && typeof p.resumeToken === 'string' && p.resumeToken ? p : null;
}

export function sessionStoragePointer(ss?: Storage): SessionPointer | null {
	return storagePointer('sessionStorage', ss);
}

/** The device pointer (every-page sessions only, see above). */
export function localStoragePointer(ls?: Storage): SessionPointer | null {
	return storagePointer('localStorage', ls);
}

function storagePointer(kind: 'localStorage' | 'sessionStorage', given?: Storage): SessionPointer | null {
	let s: Storage | undefined = given;
	try {
		s ??= kind === 'localStorage' ? globalThis.localStorage : globalThis.sessionStorage;
		if (!s) return null;
		const probe = 'osp-runtime:probe';
		s.setItem(probe, '1');
		s.removeItem(probe);
	} catch {
		return null; // blocked, or quota 0
	}
	const store = s;
	return {
		kind,
		get(slug) {
			try {
				const raw = store.getItem(POINTER_KEY(slug));
				return raw ? asPointer(JSON.parse(raw)) : null;
			} catch {
				return null;
			}
		},
		set(slug, p) {
			try {
				store.setItem(POINTER_KEY(slug), JSON.stringify(p));
			} catch {
				/* full: a refresh then starts again, as before */
			}
		},
		clear(slug) {
			try {
				store.removeItem(POINTER_KEY(slug));
			} catch {
				/* ignore */
			}
		}
	};
}

/** The URL fragment as the last resort (`#osp-session=<sessionId>.<token>`). */
export function fragmentPointer(
	loc: { hash: string; pathname: string; search: string } = globalThis.location,
	replace: (url: string) => void = (url) => globalThis.history?.replaceState(globalThis.history.state, '', url)
): SessionPointer {
	const read = () => new URLSearchParams(loc.hash.replace(/^#/, ''));
	const write = (h: URLSearchParams) => {
		const hash = h.toString();
		replace(loc.pathname + loc.search + (hash ? `#${hash}` : ''));
	};
	return {
		kind: 'fragment',
		get() {
			const v = read().get(FRAGMENT_KEY);
			const dot = v ? v.indexOf('.') : -1;
			if (!v || dot <= 0) return null;
			return asPointer({ sessionId: v.slice(0, dot), resumeToken: v.slice(dot + 1) });
		},
		set(_slug, p) {
			const h = read();
			h.set(FRAGMENT_KEY, `${p.sessionId}.${p.resumeToken}`);
			write(h);
		},
		clear() {
			const h = read();
			if (!h.has(FRAGMENT_KEY)) return;
			h.delete(FRAGMENT_KEY);
			write(h);
		}
	};
}

/** sessionStorage if it works, else the URL fragment. */
export function sessionPointer(): SessionPointer {
	return sessionStoragePointer() ?? fragmentPointer();
}
