<script lang="ts">
	import PipedText from '../cards/PipedText.svelte';
	import type { Outcome } from '../sync/survey-store.svelte';
	import type { Invocation } from '../sync/transport';
	import { endingAnchor, endingOp, endingsOf, endingWith, outcomesInUse, type OutcomeUse } from './endings';
	import { languagesOf, setText, textExact } from './model';

	/**
	 * Endings per outcome (end-of-survey plan §4.1, task EN1) through `set_ending`: for each
	 * outcome a session can end with, the screen participants see. Title and body per
	 * language, with `${id}` piping in both; the app's own status line can be hidden for
	 * recorded responses, never for a consent decline. An outcome without an ending shows the
	 * app's default screen. Texts are saved when a field loses focus.
	 */
	let {
		survey,
		defaultLanguage,
		diagnostics,
		submit
	}: {
		survey: unknown;
		defaultLanguage: string;
		diagnostics: readonly { severity: string; code: string; message: string; pointer: string }[];
		submit: (ops: Invocation[]) => Promise<Outcome>;
	} = $props();

	type Obj = Record<string, unknown>;
	const endings = $derived(endingsOf(survey));
	const languages = $derived(languagesOf(survey));
	let lang = $state('');
	const editLang = $derived(languages.includes(lang) ? lang : defaultLanguage);
	const rows = $derived.by((): OutcomeUse[] => {
		const used = outcomesInUse(survey);
		const extra = Object.keys(endings)
			.filter((o) => !used.some((u) => u.outcome === o))
			.map((outcome) => ({ outcome, sources: [], declined: false }));
		return [...used, ...extra];
	});
	let problem = $state<Record<string, string | null>>({});

	// One `set_ending` sends the whole ending, so an edit made while another is in flight
	// must build on what was last sent (as the consent editor does).
	// Plain bookkeeping, not state: nothing renders from it.
	const sent: Record<string, { value: Obj | null; n: number }> = {};
	const latest = (o: string): Obj | null => {
		const s = sent[o];
		return s && s.n > 0 ? s.value : (endings[o] ?? null);
	};

	async function send(outcome: string, next: Obj | null) {
		problem[outcome] = null;
		const s = (sent[outcome] ??= { value: null, n: 0 });
		s.value = next;
		s.n++;
		try {
			const out = await submit([endingOp(outcome, next)]);
			if (out.status === 'rejected') problem[outcome] = out.diagnostics[0]?.message ?? out.message;
		} finally {
			s.n--;
		}
	}

	function commit(outcome: string, field: 'title' | 'body', value: string) {
		const base = latest(outcome) ?? {};
		if (value === textExact(base[field], editLang, defaultLanguage)) return;
		void send(outcome, endingWith(base, field, setText(base[field], editLang, defaultLanguage, value)));
	}

	const shown = (o: string, field: 'title' | 'body') => textExact(endings[o]?.[field], editLang, defaultLanguage);
	// `ending.unreachable` is said in words above (no "Used by"); the rest are listed as is.
	const diagsFor = (o: string) =>
		diagnostics.filter(
			(d) =>
				d.code !== 'ending.unreachable' &&
				(d.pointer === `/settings/endings/${o}` || d.pointer.startsWith(`/settings/endings/${o}/`))
		);
</script>

<div class="endings">
	<p class="help">
		What participants see when the survey ends, for each outcome. End nodes, full quotas and the consent decline all end
		with an outcome; every node with the same outcome shares its ending, and an End node's own message is shown above it.
		Without an ending, participants see “Thank you” and the status line.
	</p>
	{#if languages.length > 1}
		<label class="field narrow">
			<span>Editing language</span>
			<select bind:value={lang}>
				{#each languages as l (l)}<option value={l}>{l}{l === defaultLanguage ? ' (default)' : ''}</option>{/each}
			</select>
		</label>
	{/if}
	{#each rows as row (row.outcome)}
		{@const ending = endings[row.outcome] ?? null}
		{@const uid = `ending-${row.outcome}`}
		<section class="ending" id="settings-{endingAnchor(row.outcome)}" tabindex="-1" aria-labelledby="{uid}-h" data-outcome={row.outcome}>
			<h4 id="{uid}-h">Outcome <code>{row.outcome}</code></h4>
			{#if row.sources.length}
				<p class="help">Used by: {row.sources.join(', ')}.</p>
			{:else}
				<p class="warn">Nothing in the survey ends with this outcome, so this ending is never shown.</p>
			{/if}
			{#if !ending}
				<p class="help">Uses the default screen.</p>
				<div>
					<button type="button" class="btn" onclick={() => void send(row.outcome, {})}>Customise ending for {row.outcome}</button>
				</div>
			{:else}
				{#key editLang}
					<label class="field">
						<span>Title</span>
						<input
							type="text"
							lang={editLang}
							value={shown(row.outcome, 'title')}
							placeholder="Thank you"
							onchange={(e) => commit(row.outcome, 'title', e.currentTarget.value)}
						/>
					</label>
					<label class="field">
						<span>Text</span>
						<textarea
							rows="4"
							lang={editLang}
							value={shown(row.outcome, 'body')}
							onchange={(e) => commit(row.outcome, 'body', e.currentTarget.value)}
							aria-describedby="{uid}-body-help"
						></textarea>
					</label>
					<p class="help" id="{uid}-body-help">
						Pipe answers and variables with <code>&#36;&#123;id&#125;</code>; a blank line starts a new paragraph. Shown as
						plain text, never as HTML.
					</p>
				{/key}
				<label class="check">
					<input
						type="checkbox"
						checked={row.declined || ending.status !== 'none'}
						disabled={row.declined}
						onchange={(e) => void send(row.outcome, endingWith(latest(row.outcome), 'status', e.currentTarget.checked ? undefined : 'none'))}
					/>
					<span>Show the status line</span>
				</label>
				<p class="help">
					{#if row.declined}
						A decline records nothing, and participants are always told so.
					{:else}
						The app's own line, “Your answers have been sent.”, shown once the response is stored.
					{/if}
				</p>
				<div class="preview" lang={editLang} data-testid="ending-preview-{row.outcome}">
					<p class="ptitle"><PipedText text={shown(row.outcome, 'title') || 'Thank you'} /></p>
					{#if shown(row.outcome, 'body')}<p class="pbody"><PipedText text={shown(row.outcome, 'body')} /></p>{/if}
				</div>
				<div>
					<button type="button" class="btn" onclick={() => void send(row.outcome, null)}>Use the default screen</button>
				</div>
			{/if}
			{#each diagsFor(row.outcome) as d (d.code + d.pointer + d.message)}
				<p class={d.severity === 'error' ? 'problem' : 'warn'} data-code={d.code}>{d.message}</p>
			{/each}
			{#if problem[row.outcome]}<p class="problem" role="alert">{problem[row.outcome]}</p>{/if}
		</section>
	{/each}
</div>

<style>
	.endings {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.ending {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
	}
	.ending:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}
	h4 {
		margin: 0;
		font-size: var(--text-sm);
	}
	.help,
	.warn,
	.problem {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.warn {
		color: var(--color-warning);
	}
	.problem {
		color: var(--color-danger);
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		font-size: var(--text-sm);
	}
	.field.narrow {
		max-width: 16rem;
	}
	.field input,
	.field select,
	.field textarea {
		padding: var(--space-1) var(--space-2);
		min-block-size: 2.25rem;
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-md);
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
	.preview {
		padding: var(--space-3);
		border: 1px dashed var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-bg);
	}
	.preview p {
		margin: 0;
		white-space: pre-line;
	}
	.ptitle {
		font-weight: var(--weight-semibold, 600);
	}
	.pbody {
		margin-top: var(--space-2) !important;
	}
	.btn {
		padding: var(--space-1) var(--space-3);
		min-block-size: 2.25rem;
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
		cursor: pointer;
	}
	.btn:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}
</style>
