/**
 * The demo's survey "server" (task DEMO2): the draft in memory, behind the save protocol
 * of planning/client-edits.md §3 (CE5). The builder applies every edit itself with @osp/ops
 * and sends `PUT …/draft` with the JSON Patch; this answers it as osp-api does (sync/
 * memory-transport.ts: conflict on a stale base, a patch that doesn't apply or an invalid
 * result refused with nothing saved, replay by transaction id). Undo and redo are the
 * builder's own (they arrive as ordinary saves), and so are Preview and condition parsing.
 *
 * Nothing leaves the page. `onChange` lets the demo keep the draft across its own page
 * navigations (state.ts).
 */
import { validate } from '@osp/spec';
import { memoryTransport, type MemoryTransport } from '../sync/memory-transport';
import type { Diagnostic, LoadedSurvey, Result, SaveRequest, SaveResult, SurveyDoc, SurveyTransport } from '../sync/transport';

export interface DemoDraft {
	id: string;
	title: string;
	revision: number;
	survey: SurveyDoc;
}

export interface MemoryTransportOptions {
	/** Called after every change of the draft (not on reads). */
	onChange?: (draft: DemoDraft) => void;
}

const notFound = (): Result<never> => ({ kind: 'error', status: 404, code: 'not_found', message: 'Survey not found.' });
const copy = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

export class MemorySurveyTransport implements SurveyTransport {
	readonly #mem: MemoryTransport;
	readonly #opts: MemoryTransportOptions;

	constructor(draft: DemoDraft, opts: MemoryTransportOptions = {}) {
		this.#mem = memoryTransport(copy(draft));
		this.#opts = opts;
	}

	/** The draft as it is now (a copy). */
	get draft(): DemoDraft {
		const d = this.#mem.draft;
		return { id: d.id, title: d.title, revision: d.revision, survey: copy(d.survey) };
	}

	diagnostics(): Diagnostic[] {
		return validate(this.#mem.draft.survey) as Diagnostic[];
	}

	async load(surveyId: string): Promise<Result<LoadedSurvey>> {
		if (surveyId !== this.#mem.draft.id) return notFound();
		return this.#mem.load(surveyId);
	}

	async saveDraft(surveyId: string, body: SaveRequest): Promise<Result<SaveResult>> {
		if (surveyId !== this.#mem.draft.id) return notFound();
		const before = this.#mem.draft.revision;
		const r = await this.#mem.saveDraft(surveyId, body);
		if (this.#mem.draft.revision !== before) this.#opts.onChange?.(this.draft);
		return r;
	}
}
