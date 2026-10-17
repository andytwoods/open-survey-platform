<script lang="ts">
	import type { Outcome } from '../sync/survey-store.svelte';
	import type { Invocation } from '../sync/transport';
	import {
		CONSENT_DEFAULTS,
		consentOf,
		consentOp,
		consentWith,
		languagesOf,
		missingConsentLanguages,
		setText,
		textExact,
		type ConsentTextField
	} from './model';

	/**
	 * The consent page (survey.consent, semantics.md §11) through `set_consent`: text and
	 * button labels per language, decline counting, and a preview of what participants see
	 * first. Texts are saved when a field loses focus. Nothing can be piped into them.
	 */
	let {
		survey,
		defaultLanguage,
		submit
	}: { survey: unknown; defaultLanguage: string; submit: (ops: Invocation[]) => Promise<Outcome> } = $props();

	const consent = $derived(consentOf(survey));
	const languages = $derived(languagesOf(survey));
	let lang = $state('');
	const editLang = $derived(languages.includes(lang) ? lang : defaultLanguage);
	const missing = $derived(missingConsentLanguages(consent, languages, defaultLanguage));
	let problem = $state<string | null>(null);

	const shown = (field: ConsentTextField) => textExact(consent?.[field], editLang, defaultLanguage);
	const preview = (field: ConsentTextField) => {
		const own = shown(field);
		if (own) return own;
		const v = consent?.[field];
		if (typeof v === 'string') return v;
		if (v && typeof v === 'object') return (v as Record<string, string>)[defaultLanguage] ?? '';
		return field === 'text' ? '' : CONSENT_DEFAULTS[field];
	};

	async function send(next: Record<string, unknown> | null) {
		problem = null;
		const out = await submit([consentOp(next)]);
		if (out.status === 'rejected') problem = out.diagnostics[0]?.message ?? out.message;
	}

	function enable(on: boolean) {
		void send(on ? { text: { [defaultLanguage]: '' } } : null);
	}

	function commit(field: ConsentTextField, value: string) {
		if (!consent || value === shown(field)) return;
		const next = setText(consent[field], editLang, defaultLanguage, value);
		if (field === 'text' && next === undefined) {
			void send(consentWith(consent, 'text', { [defaultLanguage]: '' }));
			return;
		}
		void send(consentWith(consent, field, next));
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
			<label class="field">
				<span>Editing language</span>
				<select bind:value={lang}>
					{#each languages as l (l)}<option value={l}>{l}{l === defaultLanguage ? ' (default)' : ''}</option>{/each}
				</select>
			</label>
			{#if missing.length}
				<p class="warn" data-testid="consent-missing">Not translated yet: {missing.join(', ')}.</p>
			{/if}
		{/if}
		{#key editLang}
			<label class="field">
				<span>Consent text</span>
				<textarea
					rows="6"
					lang={editLang}
					value={shown('text')}
					onchange={(e) => commit('text', e.currentTarget.value)}
					aria-describedby="consent-text-help"
				></textarea>
			</label>
			<p class="help" id="consent-text-help">
				The study information and consent statement. Plain text; answers can't be piped in, because this page
				comes first.
			</p>
			<div class="pair">
				<label class="field">
					<span>Agree button</span>
					<input
						type="text"
						lang={editLang}
						value={shown('agreeLabel')}
						placeholder={CONSENT_DEFAULTS.agreeLabel}
						onchange={(e) => commit('agreeLabel', e.currentTarget.value)}
					/>
				</label>
				<label class="field">
					<span>Decline button</span>
					<input
						type="text"
						lang={editLang}
						value={shown('declineLabel')}
						placeholder={CONSENT_DEFAULTS.declineLabel}
						onchange={(e) => commit('declineLabel', e.currentTarget.value)}
					/>
				</label>
			</div>
		{/key}
		<label class="check">
			<input
				type="checkbox"
				checked={consent.countDeclines === true}
				onchange={(e) => void send(consentWith(consent, 'countDeclines', e.currentTarget.checked))}
			/>
			<span>Count declines</span>
		</label>
		<p class="help">
			A decline records no response. With this on, the server keeps only an anonymous count of declines.
		</p>

		<section class="preview" aria-labelledby="consent-preview-h">
			<h4 id="consent-preview-h">Preview</h4>
			<div class="page" lang={editLang} data-testid="consent-preview">
				<p class="text">{preview('text') || 'Your consent text appears here.'}</p>
				<div class="buttons" aria-hidden="true">
					<span class="btn primary">{preview('agreeLabel')}</span>
					<span class="btn">{preview('declineLabel')}</span>
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
	}
	.field input,
	.field select,
	.field textarea {
		padding: var(--space-1) var(--space-2);
		min-block-size: 2.25rem;
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-md);
	}
	.field select {
		max-width: 16rem;
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
		white-space: pre-wrap;
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
