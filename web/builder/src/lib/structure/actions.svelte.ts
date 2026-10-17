/**
 * Add, rename, duplicate and delete pages and blocks (and questions) in the editor (task
 * B20). Each gesture is one transaction through the store, so one undo reverses it. A
 * delete the server refuses because conditions or piping still refer to what is deleted
 * asks first (`deleteRequest`), then retries with `force`.
 */
import { announce, toast } from '@osp/ui-components';
import type { OutlineNode } from '../model/outline';
import { referencingSites } from '../rows/model';
import type { SurveyStore } from '../sync/survey-store.svelte';
import { addBlockPlan, addPagePlan, deletePlan, duplicatePlan, neighbourOf, placeOf, type StructureType } from './ops';

export interface DeleteRequest {
	id: string;
	type: StructureType;
	name: string;
	sites: string[];
}

export interface StructureDeps {
	store: () => SurveyStore | null;
	roots: () => OutlineNode[];
	/** Select an item and focus one of its properties (e.g. a page's title field). */
	edit: (id: string, type: StructureType, properties: string[]) => Promise<void> | void;
	/** Select an item and put focus on it (its outline row, else its card). */
	focus: (id: string) => Promise<void> | void;
	language: () => string;
}

const TITLE: Record<StructureType, string[]> = { block: ['title'], page: ['title'], question: ['label'] };
const NAME: Record<StructureType, string> = { block: 'Block', page: 'Page', question: 'Question' };

export class StructureActions {
	deleteRequest = $state<DeleteRequest | null>(null);
	readonly #d: StructureDeps;

	constructor(deps: StructureDeps) {
		this.#d = deps;
	}

	typeOf(id: string | null | undefined): StructureType | undefined {
		return placeOf(this.#d.roots(), id)?.type;
	}

	async addPage(nearId?: string | null) {
		const store = this.#d.store();
		if (!store) return;
		const plan = addPagePlan(store.survey, this.#d.roots(), nearId);
		if (!plan) return toast('Add a block first.');
		const out = await store.submit(plan.ops);
		if (out.status !== 'applied') return;
		announce('Page added.');
		await this.#d.edit(plan.id, 'page', ['title']);
	}

	async addBlock(nearId?: string | null) {
		const store = this.#d.store();
		if (!store) return;
		const plan = addBlockPlan(store.survey, this.#d.roots(), nearId);
		const out = await store.submit(plan.ops);
		if (out.status !== 'applied') return;
		announce('Block added, with one page.');
		await this.#d.edit(plan.id, 'block', ['title']);
	}

	rename(id: string) {
		const type = this.typeOf(id);
		if (type) void this.#d.edit(id, type, TITLE[type]);
	}

	async duplicate(id: string) {
		const store = this.#d.store();
		const type = this.typeOf(id);
		if (!store || !type) return;
		const plan = duplicatePlan(store.survey, this.#d.roots(), id);
		if (!plan) return;
		const out = await store.submit(plan.ops);
		if (out.status !== 'applied') return;
		announce(`${NAME[type]} duplicated.`);
		await this.#d.focus(plan.id);
	}

	async remove(id: string, force = false) {
		const store = this.#d.store();
		const roots = this.#d.roots();
		const at = placeOf(roots, id);
		if (!store || !at) return;
		const plan = deletePlan(store.survey, roots, id, force);
		if (!plan) return;
		if ('refused' in plan) return toast(plan.refused);
		const next = neighbourOf(roots, id);
		const out = await store.submit(plan.ops, { quiet: force ? [] : ['op.dangling_ref'] });
		if (out.status === 'applied') {
			announce(`Deleted ${at.node.label}. Undo brings it back.`);
			if (next) await this.#d.focus(next);
			return;
		}
		if (out.status === 'rejected' && out.diagnostics[0]?.code === 'op.dangling_ref') {
			const sites = referencingSites(store.survey, out.diagnostics, this.#d.language());
			this.deleteRequest = { id, type: at.type, name: at.node.label, sites };
		}
	}

	/** The answer to `deleteRequest`: Keep (false) or Delete anyway (true). */
	resolveDelete(ok: boolean) {
		const r = this.deleteRequest;
		this.deleteRequest = null;
		if (!r) return;
		if (ok) void this.remove(r.id, true);
		else announce(`Kept ${r.name}.`);
	}
}
