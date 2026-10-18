/**
 * What the provenance lines need to know about the bank items a survey's `source` records
 * point at (question-bank.md §6): each item's title and current version, fetched once per
 * id and kept for the page. A deleted or unreadable item shows as its id with "not found".
 */
import { SvelteMap, SvelteSet } from 'svelte/reactivity';
import { bank } from './library.svelte';
import { ownSources, provenanceLabel, type SourceRef } from './logic';

export interface ProvenanceInfo {
	label: string;
	title: string | null;
	/** The item's current version, when it could be read. */
	current: number | null;
	licenceClass: string | null;
	/** The item exists and is newer than what was inserted. */
	newer: boolean;
	missing: boolean;
}

export class ProvenanceIndex {
	#items = new SvelteMap<string, { title: string; version: number; licenceClass: string } | null>();
	#pending = new SvelteSet<string>();

	/** Fetch what is missing for every source in `survey` (idempotent). */
	refresh(survey: unknown) {
		for (const s of ownSources(survey)) void this.#load(s.source.bank);
	}

	async #load(id: string) {
		if (this.#items.has(id) || this.#pending.has(id)) return;
		this.#pending.add(id);
		const r = await bank.get(id);
		this.#pending.delete(id);
		this.#items.set(id, r.ok ? { title: r.data.summary.title, version: r.data.summary.version, licenceClass: r.data.summary.licenceClass } : null);
	}

	/** Forget an item (after a new version was saved), so the next refresh re-reads it. */
	invalidate(id: string) {
		this.#items.delete(id);
		bank.forget(id);
	}

	info(source: SourceRef): ProvenanceInfo {
		const known = this.#items.get(source.bank);
		const title = known?.title ?? null;
		return {
			label: provenanceLabel(source, title) + (known === null ? ' (not found)' : ''),
			title,
			current: known?.version ?? null,
			licenceClass: known?.licenceClass ?? null,
			newer: !!known && known.version > source.version,
			missing: known === null
		};
	}
}
