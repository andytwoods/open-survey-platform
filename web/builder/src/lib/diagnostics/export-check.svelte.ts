/**
 * The selected export target and its latest export check (task B10). The check is fetched
 * from `GET /api/surveys/{id}/export-check` when the target or the draft revision changes
 * (debounced); an answer for an older revision than one already shown is ignored.
 */
import type { ExportDiagnostic, TargetChoice, TargetId } from './model';

export interface CheckResult {
	target: TargetId;
	revision: number;
	diagnostics: ExportDiagnostic[];
}

export type CheckFetcher = (
	surveyId: string,
	target: TargetId
) => Promise<{ ok: true; data: CheckResult } | { ok: false; message: string }>;

export class ExportCheckState {
	target = $state<TargetChoice>('none');
	result = $state.raw<CheckResult | null>(null);
	loading = $state(false);
	error = $state<string | null>(null);

	readonly #fetch: CheckFetcher;
	readonly #delay: number;
	#timer: ReturnType<typeof setTimeout> | null = null;
	#seq = 0;

	constructor(fetcher: CheckFetcher, { delay = 300 }: { delay?: number } = {}) {
		this.#fetch = fetcher;
		this.#delay = delay;
	}

	/** Export diagnostics for the selected target (none when no target is picked). */
	get diagnostics(): ExportDiagnostic[] {
		const r = this.result;
		return r && this.target !== 'none' && r.target === this.target ? r.diagnostics : [];
	}

	setTarget(t: TargetChoice) {
		this.target = t;
		if (t === 'none') {
			this.result = null;
			this.error = null;
			this.#cancel();
		}
	}

	#cancel() {
		if (this.#timer) clearTimeout(this.#timer);
		this.#timer = null;
		this.#seq++;
		this.loading = false;
	}

	/** Ask for a check of `surveyId` at `revision` (call when either input changes). */
	request(surveyId: string, revision: number) {
		const target = this.target;
		if (target === 'none' || !surveyId) return;
		const r = this.result;
		if (r && r.target === target && r.revision === revision) return;
		if (this.#timer) clearTimeout(this.#timer);
		const seq = ++this.#seq;
		this.loading = true;
		this.#timer = setTimeout(async () => {
			this.#timer = null;
			const out = await this.#fetch(surveyId, target);
			if (seq !== this.#seq || this.target !== target) return;
			this.loading = false;
			if (!out.ok) {
				this.error = out.message;
				return;
			}
			this.error = null;
			const cur = this.result;
			if (cur && cur.target === target && cur.revision > out.data.revision) return;
			this.result = out.data;
		}, this.#delay);
	}

	dispose() {
		this.#cancel();
	}
}
