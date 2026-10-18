/**
 * The question bank API (`/api/bank`, tasks QB4 and QB5) as the builder uses it: search,
 * one item's document (cached by id + version), save / new version / metadata / share /
 * delete / export / import / copy, the save preview, the instrument stubs and the
 * licensed-copy wizard's save. Every call returns a result for the page; nothing throws.
 */
import type { components } from '@osp/api-client';
import { SvelteMap } from 'svelte/reactivity';
import { api } from '../api';
import type { Diagnostic } from '../sync/transport';
import type { BankItemOut, BankList, BankPreviewOut, BankSummary, BankVersion, InstrumentStub } from './logic';

export type BankResult<T> = { ok: true; data: T } | { ok: false; message: string; code?: string; diagnostics?: Diagnostic[] };

export interface SearchParams {
	q?: string;
	kind?: 'question' | 'page' | 'block';
	source?: 'lab' | 'host' | 'bundled';
	lang?: string;
	licence?: string;
	tag?: string[];
	page?: number;
	pageSize?: number;
}

type SaveBody = components['schemas']['SaveBankItemRequest'];
type NewVersionBody = components['schemas']['NewVersionRequest'];
type UpdateBody = components['schemas']['UpdateBankItemRequest'];
type ComposeBody = components['schemas']['ComposeLicensedRequest'];
export type BankFile = components['schemas']['BankFile'];

function messageOf(error: unknown, status: number): string {
	const m = (error as { message?: unknown } | undefined)?.message;
	return typeof m === 'string' ? m : `Request failed (${status}).`;
}

function failure<T>(error: unknown, status: number): BankResult<T> {
	const e = error as { message?: unknown; diagnostics?: unknown } | undefined;
	const diagnostics = Array.isArray(e?.diagnostics) ? (e!.diagnostics as Diagnostic[]) : undefined;
	return { ok: false, message: messageOf(error, status), code: diagnostics?.[0]?.code, diagnostics };
}

async function call<T>(fn: () => Promise<{ data?: T; error?: unknown; response: Response }>, noContent = false): Promise<BankResult<T>> {
	try {
		const r = await fn();
		if (noContent) return r.response.ok ? { ok: true, data: undefined as T } : failure(r.error, r.response.status);
		if (r.data === undefined) return failure(r.error, r.response.status);
		return { ok: true, data: r.data };
	} catch (e) {
		return { ok: false, message: (e as Error)?.message || 'Network error' };
	}
}

export class BankLibrary {
	/** The last search's answer (the Bank section and page both show one list at a time). */
	list = $state.raw<BankList | null>(null);
	loading = $state(false);
	error = $state<string | null>(null);
	stubs = $state.raw<InstrumentStub[] | null>(null);
	#docs = new SvelteMap<string, BankItemOut>();
	#seq = 0;

	get canManage() {
		return this.list?.canManage ?? false;
	}
	get canShare() {
		return this.list?.canShare ?? false;
	}

	/** Search; a later search's answer wins over an earlier one still in flight. */
	async search(params: SearchParams = {}): Promise<BankResult<BankList>> {
		const seq = ++this.#seq;
		this.loading = true;
		const r = await call(() => api.GET('/api/bank', { params: { query: params } }));
		if (seq !== this.#seq) return r;
		this.loading = false;
		if (r.ok) {
			this.list = r.data;
			this.error = null;
		} else this.error = r.message;
		return r;
	}

	/** One item's document (the current version, or `version`); cached. */
	async get(id: string, version?: number, fresh = false): Promise<BankResult<BankItemOut>> {
		const key = `${id}@${version ?? 'current'}`;
		const hit = this.#docs.get(key);
		if (hit && !fresh) return { ok: true, data: hit };
		const r = await call(() =>
			api.GET('/api/bank/{item_id}', { params: { path: { item_id: id }, query: version ? { version } : {} } })
		);
		if (r.ok) {
			this.#docs.set(key, r.data);
			this.#docs.set(`${id}@${r.data.version}`, r.data);
		}
		return r;
	}

	forget(id: string) {
		for (const k of [...this.#docs.keys()]) if (k.startsWith(`${id}@`)) this.#docs.delete(k);
	}

	preview(surveyId: string, targetId: string): Promise<BankResult<BankPreviewOut>> {
		return call(() => api.POST('/api/bank/preview', { body: { surveyId, targetId } }));
	}

	async save(body: SaveBody): Promise<BankResult<components['schemas']['BankSaveOut']>> {
		return call(() => api.POST('/api/bank', { body }));
	}

	async newVersion(id: string, body: NewVersionBody): Promise<BankResult<components['schemas']['BankSaveOut']>> {
		const r = await call(() => api.POST('/api/bank/{item_id}/versions', { params: { path: { item_id: id } }, body }));
		if (r.ok) this.forget(id);
		return r;
	}

	versions(id: string): Promise<BankResult<BankVersion[]>> {
		return call(() => api.GET('/api/bank/{item_id}/versions', { params: { path: { item_id: id } } }));
	}

	async update(id: string, body: UpdateBody): Promise<BankResult<BankItemOut>> {
		const r = await call(() => api.PATCH('/api/bank/{item_id}', { params: { path: { item_id: id } }, body }));
		if (r.ok) this.forget(id);
		return r;
	}

	async share(id: string, visibility: 'lab' | 'host', licenceClass?: string): Promise<BankResult<BankItemOut>> {
		const r = await call(() =>
			api.POST('/api/bank/{item_id}/share', {
				params: { path: { item_id: id } },
				body: { visibility, ...(licenceClass ? { licenceClass } : {}) }
			})
		);
		if (r.ok) this.forget(id);
		return r;
	}

	async remove(id: string): Promise<BankResult<void>> {
		const r = await call<void>(() => api.DELETE('/api/bank/{item_id}', { params: { path: { item_id: id } } }) as never, true);
		if (r.ok) this.forget(id);
		return r;
	}

	exportFile(id: string, version?: number): Promise<BankResult<BankFile>> {
		return call(() =>
			api.GET('/api/bank/{item_id}/export', { params: { path: { item_id: id }, query: version ? { version } : {} } })
		);
	}

	importFile(file: Record<string, unknown>, attestLicensed = false): Promise<BankResult<components['schemas']['BankImportOut']>> {
		return call(() => api.POST('/api/bank/import', { body: { file, attestLicensed } }));
	}

	copy(id: string, version?: number): Promise<BankResult<BankItemOut>> {
		return call(() =>
			api.POST('/api/bank/{item_id}/copy', { params: { path: { item_id: id } }, body: version ? { version } : {} })
		);
	}

	async loadStubs(): Promise<BankResult<InstrumentStub[]>> {
		if (this.stubs) return { ok: true, data: this.stubs };
		const r = await call(() => api.GET('/api/bank/stubs'));
		if (r.ok) this.stubs = r.data;
		return r;
	}

	composeLicensed(body: ComposeBody): Promise<BankResult<BankItemOut>> {
		return call(() => api.POST('/api/bank/licensed', { body }));
	}

	/** A summary from the last list by id (the Bank page edits in place after a change). */
	replace(summary: BankSummary) {
		if (!this.list) return;
		const items = this.list.items.map((i) => (i.id === summary.id ? summary : i));
		this.list = { ...this.list, items };
	}

	drop(id: string) {
		if (!this.list) return;
		this.list = { ...this.list, items: this.list.items.filter((i) => i.id !== id), total: Math.max(0, this.list.total - 1) };
	}
}

/** One library per page: the Bank section, the dialogs and the provenance lines share the cache. */
export const bank = new BankLibrary();
