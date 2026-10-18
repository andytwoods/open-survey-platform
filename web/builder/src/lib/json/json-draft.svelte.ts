/**
 * The JSON view's local draft (builder-design §4, task B9). Edits stay here until Apply,
 * which sends one `replace_survey` op through the survey store, validated like any other
 * op. Invalid JSON is never sent; a rejected Apply (422) leaves the store's draft as it was
 * and keeps the text, with the server's diagnostics placed by their JSON pointers.
 */
import { untrack } from 'svelte';
import type { SurveyStore } from '../sync/survey-store.svelte';
import type { Diagnostic } from '../sync/transport';
import { formatJson, locate, parseJson, positionAt, type Position, type Span } from './source';

export interface PlacedDiagnostic {
	severity: Diagnostic['severity'];
	code: string;
	message: string;
	pointer: string;
	span: Span | null;
	position: Position | null;
}

export interface JsonSyntaxError {
	message: string;
	offset: number;
	position: Position;
}

export type ApplyResult = 'applied' | 'invalid' | 'rejected' | 'stale' | 'unchanged' | 'failed';

/** Structural equality for JSON values (key order ignored). */
export function jsonEqual(a: unknown, b: unknown): boolean {
	if (a === b) return true;
	if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) return false;
	if (Array.isArray(a) !== Array.isArray(b)) return false;
	if (Array.isArray(a)) {
		const bb = b as unknown[];
		return a.length === bb.length && a.every((v, i) => jsonEqual(v, bb[i]));
	}
	const ao = a as Record<string, unknown>;
	const bo = b as Record<string, unknown>;
	const ak = Object.keys(ao);
	return ak.length === Object.keys(bo).length && ak.every((k) => k in bo && jsonEqual(ao[k], bo[k]));
}

/** Place server diagnostics in `text` by pointer (nearest existing ancestor). */
export function placeDiagnostics(text: string, diagnostics: readonly Diagnostic[]): PlacedDiagnostic[] {
	const parsed = parseJson(text);
	return diagnostics.map((d) => {
		const pointer = typeof d.pointer === 'string' ? d.pointer : '';
		const span = parsed.ok ? (locate(parsed.spans, pointer) ?? null) : null;
		return {
			severity: d.severity,
			code: d.code,
			message: d.message,
			pointer,
			span,
			position: span ? positionAt(text, span.from) : null
		};
	});
}

export class JsonDraft {
	/** The editor's text. */
	text = $state('');
	/** The survey as formatted when editing started (or last synced). */
	baseText = $state('');
	/** The server revision `baseText` came from (shown in the stale notice). */
	baseRevision = $state(0);
	/** The store version `baseText` came from: any change to the survey since makes it stale. */
	baseVersion = $state(0);
	applying = $state(false);
	/** Set by Apply when the text is not valid JSON (nothing was sent). */
	syntaxError = $state.raw<JsonSyntaxError | null>(null);
	/** A rejected Apply's diagnostics, placed in `rejectedText`. */
	rejected = $state.raw<PlacedDiagnostic[]>([]);
	rejectedText = $state('');
	/** Outcome of the last Apply or Revert, for the status line. */
	message = $state('');

	readonly #store: SurveyStore;

	constructor(store: SurveyStore) {
		this.#store = store;
		// Not a dependency of whoever constructs this (e.g. a $derived).
		untrack(() => this.#take());
	}

	get dirty(): boolean {
		return this.text !== this.baseText;
	}

	/**
	 * Local edits exist and the survey changed since they began (on the server, picked up
	 * by a reload or a rebase, or by another edit in the builder).
	 */
	get stale(): boolean {
		return this.dirty && this.#store.version !== this.baseVersion;
	}

	get serverRevision(): number {
		return this.#store.revision;
	}

	/** Server diagnostics still describing the text in the editor. */
	get current(): PlacedDiagnostic[] {
		return this.rejected.length && this.rejectedText === this.text ? this.rejected : [];
	}

	#take() {
		this.baseText = formatJson(this.#store.survey);
		this.baseRevision = this.#store.revision;
		this.baseVersion = this.#store.version;
		this.text = this.baseText;
	}

	/** Follow the store while there are no local edits (call from an effect). */
	sync() {
		if (this.dirty || this.applying) return;
		if (this.baseVersion === this.#store.version && this.text === formatJson(this.#store.survey)) return;
		this.#take();
	}

	edit(text: string) {
		this.text = text;
		if (this.syntaxError) this.syntaxError = null;
	}

	/** Discard local edits: show the survey as it is now. */
	revert() {
		this.#take();
		this.syntaxError = null;
		this.rejected = [];
		this.rejectedText = '';
		this.message = 'Edits discarded.';
	}

	/**
	 * Send the text as one `replace_survey`. Invalid JSON, a non-object, or (unless `force`)
	 * a survey that changed on the server since editing began are refused locally.
	 */
	async apply({ force = false }: { force?: boolean } = {}): Promise<ApplyResult> {
		if (this.applying) return 'failed';
		const text = this.text;
		const parsed = parseJson(text);
		if (!parsed.ok) {
			this.syntaxError = { message: parsed.message, offset: parsed.offset, position: parsed.position };
			this.message = `Not applied: the JSON is invalid (line ${parsed.position.line}, column ${parsed.position.col}).`;
			return 'invalid';
		}
		const value = parsed.value;
		if (typeof value !== 'object' || value === null || Array.isArray(value)) {
			this.syntaxError = { message: 'The survey must be a JSON object.', offset: 0, position: { line: 1, col: 1 } };
			this.message = 'Not applied: the survey must be a JSON object.';
			return 'invalid';
		}
		this.syntaxError = null;
		if (this.stale && !force) {
			this.message = 'Not applied: the survey changed on the server while you were editing.';
			return 'stale';
		}
		if (jsonEqual(value, this.#store.survey)) {
			this.#take();
			this.message = 'No changes to apply.';
			return 'unchanged';
		}
		this.applying = true;
		try {
			this.#store.flushBuffers();
			const out = await this.#store.submit([
				{ op: 'replace_survey', params: { survey: value as Record<string, unknown> } }
			]);
			if (out.status === 'applied') {
				this.rejected = [];
				this.rejectedText = '';
				this.applying = false;
				this.#take();
				this.message = 'Applied.';
				return 'applied';
			}
			if (out.status === 'rejected') {
				this.rejected = placeDiagnostics(text, out.diagnostics);
				this.rejectedText = text;
				const n = out.diagnostics.length;
				this.message = `Not applied: ${n === 1 ? '1 problem' : `${n} problems`}. The survey is unchanged.`;
				return 'rejected';
			}
			this.message = `Not applied: ${out.message}`;
			return 'failed';
		} finally {
			this.applying = false;
		}
	}
}
