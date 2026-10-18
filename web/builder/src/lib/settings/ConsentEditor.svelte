<script lang="ts">
	import { RichTextEditor, RichView, type RichValue } from '../richtext';
	import type { Outcome } from '../sync/survey-store.svelte';
	import type { Invocation } from '../sync/transport';
	import { EditingLanguageSelect, editLanguageOf } from '../translations';
	import {
		CONSENT_DEFAULTS,
		consentOf,
		consentOp,
		consentWith,
		languagesOf,
		missingConsentLanguages,
		richExact,
		sameText,
		setText,
		type ConsentTextField
	} from './model';

	/**
	 * The consent page (survey.consent, semantics.md §11) through `set_consent`: text and
	 * button labels per language, decline counting, and a preview of what participants see
	 * first. The text is rich at block level, the button labels inline (planning/rich-text.md
	 * RT-D5); nothing can be piped into them, so the editors offer no chips. Texts are saved
	 * after a pause or when a field loses focus. The editing language is the page's shared
	 * one (planning/rich-text.md §5, RT6); a translation shows the default text as reference.
	 */
	let {
		survey,
		defaultLanguage,
		submit
	}: { survey: unknown; defaultLanguage: string; submit: (ops: Invocation[]) => Promise<Outcome> } = $props();

	const consent = $derived(consentOf(survey));
	const languages = $derived(languagesOf(survey));
	const editLang = $derived(editLanguageOf(survey));
	const translating = $derived(editLang !== defaultLanguage);
	const missing = $derived(missingConsentLanguages(consent, languages, defaultLanguage));
	let problem = $state<string | null>(null);

	// The store applies an edit only when the server answers, so while a `set_consent` is in
	// flight `consent` is still the old object. Each op sends the whole consent object, so the
	// next edit must build on what was last sent, or it would undo the edit still in flight
	// (typing the text, then the agree label, lost the text).
	let sent: Record<string, unknown> | null = null;
	let inFlight = 0;
	const latest = () => (inFlight > 0 ? sent : consent);

	const shown = (field: ConsentTextField): RichValue => richExact(consent?.[field], editLang, defaultLanguage);
	/** The default language's value, as the reference above a translation. */
	const reference = (field: ConsentTextField) =>
		translating ? { value: richExact(consent?.[field], defaultLanguage, defaultLanguage), language: defaultLanguage } : null;
	const preview = (field: ConsentTextField): RichValue => {
		const own = shown(field);
		if (own) return own;
		const v = consent?.[field];
		const fallback = richExact(v, defaultLanguage, defaultLanguage);
		if (fallback) return fallback;
		return field === 'text' ? '' : CONSENT_DEFAULTS[field];
	};

	async function send(next: Record<string, unknown> | null) {
		problem = null;
		sent = next;
		inFlight++;
		try {
			const out = await submit([consentOp(next)]);
			if (out.status === 'rejected') problem = out.diagnostics[0]?.message ?? out.message;
		} finally {
			if (--inFlight === 0) sent = null;
		}
	}

	function enable(on: boolean) {
		void send(on ? { text: { [defaultLanguage]: '' } } : null);
	}

	function commit(field: ConsentTextField, value: RichValue) {
		const base = latest();
		if (!base || sameText(value, richExact(base[field], editLang, defaultLanguage))) return;
		const next = setText(base[field], editLang, defaultLanguage, value);
		if (field === 'text' && next === undefined) {
			void send(consentWith(base, 'text', { [defaultLanguage]: '' }));
			return;
		}
		void send(consentWith(base, field, next));
	}
</script>

<div class="consent">
	<label class="check">
		<input type="checkbox" checked={!!consent} onchange={(e) => enable(e.currentTarget.checked)} />
		<span>Show a consent page before the first question</span>
	</label>
	{#if !consent}
		<p class="help">
			Without a consent page, publishing shows a warning when the survey asks questions. Leave it off only if
			consent is taken elsewhere (for example on the recruitment platform).
		</p>
	{:else}
		{#if languages.length > 1}
			<EditingLanguageSelect {survey} id="consent-editing-language" />
			{#if missing.length}
				<p class="warn" data-testid="consent-missing">Not translated yet: {missing.join(', ')}.</p>
			{/if}
		{/if}
		{#key editLang}
			<div class="field">
				<span id="consent-text-label">Consent text</span>
				<RichTextEditor
					id="consent-text"
					value={shown('text')}
					level="block"
					pipes={null}
					reference={reference('text')}
					labelledBy="consent-text-label"
					describedBy="consent-text-help"
					lang={editLang}
					onCommit={(v) => commit('text', v)}
				/>
			</div>
			<p class="help" id="consent-text-help">
				The study information and consent statement. Answers can't be piped in, because this page comes first.
			</p>
			<div class="pair">
				<div class="field">
					<span id="consent-agree-label">Agree button</span>
					<RichTextEditor
						id="consent-agree"
						value={shown('agreeLabel')}
						level="inline"
						pipes={null}
						reference={reference('agreeLabel')}
						labelledBy="consent-agree-label"
						placeholder={CONSENT_DEFAULTS.agreeLabel}
						lang={editLang}
						onCommit={(v) => commit('agreeLabel', v)}
					/>
				</div>
				<div class="field">
					<span id="consent-decline-label">Decline button</span>
					<RichTextEditor
						id="consent-decline"
						value={shown('declineLabel')}
						level="inline"
						pipes={null}
						reference={reference('declineLabel')}
						labelledBy="consent-decline-label"
						placeholder={CONSENT_DEFAULTS.declineLabel}
						lang={editLang}
						onCommit={(v) => commit('declineLabel', v)}
					/>
				</div>
			</div>
		{/key}
		<label class="check">
			<input
				type="checkbox"
				checked={consent.countDeclines === true}
				onchange={(e) => void send(consentWith(latest(), 'countDeclines', e.currentTarget.checked))}
			/>
			<span>Count declines</span>
		</label>
		<p class="help">
			A decline records no response. With this on, the server keeps only an anonymous count of declines.
		</p>

		<section class="preview" aria-labelledby="consent-preview-h">
			<h4 id="consent-preview-h">Preview</h4>
			<div class="page" lang={editLang} data-testid="consent-preview">
				<div class="text">
					{#if preview('text')}<RichView value={preview('text')} />{:else}<p class="empty">Your consent text appears here.</p>{/if}
				</div>
				<div class="buttons" aria-hidden="true">
					<span class="btn primary"><RichView value={preview('agreeLabel')} inline /></span>
					<span class="btn"><RichView value={preview('declineLabel')} inline /></span>
				</div>
			</div>
		</section>
	{/if}
	{#if problem}<p class="problem" role="alert">{problem}</p>{/if}
</div>

<style>
	.consent {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.check {
		display: flex;
		gap: var(--space-2);
		align-items: center;
		min-block-size: 2rem;
		font-weight: var(--weight-medium);
		cursor: pointer;
	}
	.check input {
		inline-size: 1.1rem;
		block-size: 1.1rem;
	}
	.help,
	.warn {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.warn {
		color: var(--color-warning);
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		font-size: var(--text-sm);
		flex: 1;
		min-width: 0;
	}
	.pair {
		display: flex;
		gap: var(--space-3);
		flex-wrap: wrap;
	}
	.preview h4 {
		margin: 0 0 var(--space-2);
		font-size: var(--text-sm);
	}
	.page {
		padding: var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg, var(--radius-md));
		background: var(--color-bg);
		max-width: 42rem;
	}
	.text {
		margin: 0 0 var(--space-4);
	}
	.empty {
		margin: 0;
		color: var(--color-text-muted);
	}
	.buttons {
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
	}
	.btn {
		padding: var(--space-2) var(--space-4);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		font-size: var(--text-sm);
	}
	.btn.primary {
		background: var(--color-accent);
		border-color: var(--color-accent);
		color: var(--color-on-accent, #fff);
	}
	.problem {
		margin: 0;
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
</style>
