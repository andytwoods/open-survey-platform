<script lang="ts">
	import PipedText from '../cards/PipedText.svelte';
	import type { Outcome } from '../sync/survey-store.svelte';
	import type { Invocation } from '../sync/transport';
	import {
		DEFAULT_PARAM_PATTERN,
		DEFAULT_REDIRECT_DELAY,
		endingAnchor,
		endingOp,
		endingsOf,
		endingWith,
		MAX_REDIRECT_DELAY,
		newRedirect,
		outcomesInUse,
		placeholdersOf,
		previewUrl,
		redirectOf,
		redirectParams,
		redirectTemplateOp,
		templateProblem,
		templatesOf,
		type OutcomeUse
	} from './endings';
	import { languagesOf, setText, textExact } from './model';

	/**
	 * Endings per outcome (end-of-survey plan §4.1, task EN1) through `set_ending`: for each
	 * outcome a session can end with, the screen participants see. Title and body per
	 * language, with `${id}` piping in both; the app's own status line can be hidden for
	 * recorded responses, never for a consent decline. An outcome without an ending shows the
	 * app's default screen. Texts are saved when a field loses focus.
	 *
	 * Redirects (§4.2, task EN2): an ending may send participants on afterwards, to one of
	 * the survey's **redirect templates** (edited at the bottom through
	 * `set_redirect_template`): per placeholder a fixed value or a `${…}` pipe, the mode
	 * (automatic after a countdown, or a link), the delay and the button label. The URL
	 * preview keeps pipes as tokens; the server's `redirect.*` diagnostics are shown inline,
	 * including the data-export warning for a piped answer.
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

	// -- redirects (EN2) ----------------------------------------------------------------------
	const templates = $derived(templatesOf(survey));
	const templateDiags = $derived(diagnostics.filter((d) => d.pointer.startsWith('/settings/redirectTemplates')));

	/** The ending with its redirect replaced (`null` removes it). */
	function setRedirect(outcome: string, redirect: Obj | null) {
		void send(outcome, endingWith(latest(outcome), 'redirect', redirect ?? undefined));
	}
	function chooseTemplate(outcome: string, name: string) {
		const t = templates.find((x) => x.name === name);
		setRedirect(outcome, t ? newRedirect(t) : null);
	}
	function redirectWith(outcome: string, field: string, value: unknown): Obj {
		const r = { ...(redirectOf(latest(outcome)) ?? {}) };
		if (value === undefined) delete r[field];
		else r[field] = value;
		return r;
	}
	function commitParam(outcome: string, name: string, value: string) {
		const r = redirectOf(latest(outcome));
		const params = { ...redirectParams(r), [name]: value };
		if (params[name] === redirectParams(r)[name]) return;
		setRedirect(outcome, redirectWith(outcome, 'params', params));
	}
	function commitDelay(outcome: string, raw: string) {
		const n = Number(raw);
		if (!Number.isInteger(n) || n < 0 || n > MAX_REDIRECT_DELAY) return;
		setRedirect(outcome, redirectWith(outcome, 'delay', n === DEFAULT_REDIRECT_DELAY ? undefined : n));
	}
	function commitLabel(outcome: string, value: string) {
		const r = redirectOf(latest(outcome));
		if (value === textExact(r?.label, editLang, defaultLanguage)) return;
		setRedirect(outcome, redirectWith(outcome, 'label', setText(r?.label, editLang, defaultLanguage, value)));
	}
	const modeOf = (r: Obj | null) => (r?.mode === 'link' ? 'link' : 'auto');
	const delayOf = (r: Obj | null) => (typeof r?.delay === 'number' ? r.delay : DEFAULT_REDIRECT_DELAY);

	// A new template: name, address, and a pattern per placeholder the address declares.
	let newName = $state('');
	let newUrl = $state('');
	let newPatterns = $state<Record<string, string>>({});
	let templateProblemText = $state<string | null>(null);
	const newPlaceholders = $derived(placeholdersOf(newUrl));
	const nameOk = $derived(/^[A-Za-z_][A-Za-z0-9_-]{0,63}$/.test(newName));

	async function addTemplate() {
		templateProblemText = templateProblem(newUrl);
		if (!nameOk) templateProblemText = 'Give the template a short name: letters, digits, _ or -.';
		if (templateProblemText) return;
		const params = Object.fromEntries(
			newPlaceholders.map((n) => [n, newPatterns[n]?.trim() ? { pattern: newPatterns[n]!.trim() } : {}])
		);
		const out = await submit([redirectTemplateOp(newName, { url: newUrl.trim(), params })]);
		if (out.status === 'rejected') {
			templateProblemText = out.diagnostics[0]?.message ?? out.message;
			return;
		}
		newName = '';
		newUrl = '';
		newPatterns = {};
	}
	async function removeTemplate(name: string) {
		templateProblemText = null;
		const out = await submit([redirectTemplateOp(name, null)]);
		if (out.status === 'rejected') templateProblemText = out.diagnostics[0]?.message ?? out.message;
	}
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
				{@const r = redirectOf(ending)}
				{@const tpl = r ? templates.find((t) => t.name === r.template) : undefined}
				{@const params = redirectParams(r)}
				<fieldset class="redirect" data-testid="redirect-{row.outcome}">
					<legend>Afterwards</legend>
					<label class="field narrow">
						<span>Send participants to</span>
						<select value={r && typeof r.template === 'string' ? r.template : ''} onchange={(e) => chooseTemplate(row.outcome, e.currentTarget.value)}>
							<option value="">Nowhere: they stay on this screen</option>
							{#each templates as t (t.name)}<option value={t.name}>{t.name} ({t.host})</option>{/each}
							{#if r && typeof r.template === 'string' && !tpl}<option value={r.template}>{r.template} (not declared)</option>{/if}
						</select>
					</label>
					{#if templates.length === 0}
						<p class="help">Add a redirect template below first (for example your Prolific completion URL).</p>
					{/if}
					{#if r && tpl}
						{#each tpl.placeholders as name (name)}
							<label class="field">
								<span>Value for <code>{'{' + name + '}'}</code></span>
								<input
									type="text"
									value={params[name] ?? ''}
									placeholder={tpl.params[name]?.pattern ?? DEFAULT_PARAM_PATTERN}
									onchange={(e) => commitParam(row.outcome, name, e.currentTarget.value)}
								/>
							</label>
						{/each}
						<p class="help">
							A fixed value, or <code>&#36;&#123;id&#125;</code> to send an answer or a variable; also
							<code>&#36;&#123;$response.id&#125;</code>, <code>&#36;&#123;$session.id&#125;</code> and <code>&#36;&#123;$outcome&#125;</code>.
							Each value must match its placeholder's pattern or no redirect happens. Sending an <strong>answer</strong> is a data
							export: it is listed in the codebook and recorded in the audit log.
						</p>
						<div class="row">
							<label class="field narrow">
								<span>Go there</span>
								<select value={modeOf(r)} onchange={(e) => setRedirect(row.outcome, redirectWith(row.outcome, 'mode', e.currentTarget.value === 'link' ? 'link' : undefined))}>
									<option value="auto">automatically, after a countdown</option>
									<option value="link">only when the participant clicks</option>
								</select>
							</label>
							{#if modeOf(r) === 'auto'}
								<label class="field narrow">
									<span>Countdown (seconds, 0–{MAX_REDIRECT_DELAY})</span>
									<input type="number" min="0" max={MAX_REDIRECT_DELAY} step="1" value={delayOf(r)} onchange={(e) => commitDelay(row.outcome, e.currentTarget.value)} />
								</label>
							{/if}
						</div>
						{#if modeOf(r) === 'auto'}
							<p class="help">
								Participants hear one announcement, see the countdown, and can go now or <em>Stay on this page</em>.
								{#if delayOf(r) === 0}
									<strong class="warn">With 0 seconds this screen is never seen.</strong> Keep a few seconds, or choose the click-only mode (WCAG 2.2.1).
								{/if}
							</p>
						{/if}
						{#key editLang}
							<label class="field">
								<span>Button label</span>
								<input
									type="text"
									lang={editLang}
									value={textExact(r.label, editLang, defaultLanguage)}
									placeholder="Continue to {tpl.host}"
									onchange={(e) => commitLabel(row.outcome, e.currentTarget.value)}
								/>
							</label>
						{/key}
						<p class="help url">
							Preview URL: <code data-testid="redirect-url-{row.outcome}">{previewUrl(tpl, params)}</code>
						</p>
					{/if}
				</fieldset>
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

	<section class="ending" id="settings-redirect-templates" tabindex="-1" aria-labelledby="redirect-templates-h" data-testid="redirect-templates">
		<h4 id="redirect-templates-h">Redirect templates</h4>
		<p class="help">
			Where an ending may send participants: an <code>https://</code> address with <code>&#123;name&#125;</code> placeholders after the
			site, such as <code>https://app.prolific.com/submissions/complete?cc=&#123;cc&#125;</code>. A placeholder's value must match its
			pattern (default <code>{DEFAULT_PARAM_PATTERN}</code>) and is URL-encoded, so a value can never change the site. Hook code may
			use these templates too.
		</p>
		{#each templates as t (t.name)}
			<div class="template" data-template={t.name}>
				<div class="tline">
					<code class="tname">{t.name}</code>
					<code class="turl">{t.url}</code>
					{#if t.source === 'hooks'}
						<span class="help">declared by the hooks manifest</span>
					{:else}
						<button type="button" class="btn" onclick={() => void removeTemplate(t.name)}>Remove {t.name}</button>
					{/if}
				</div>
				{#if t.placeholders.length}
					<p class="help">
						{#each t.placeholders as p, i (p)}{i ? ' · ' : ''}<code>{p}</code>: <code>{t.params[p]?.pattern ?? DEFAULT_PARAM_PATTERN}</code>{/each}
					</p>
				{/if}
			</div>
		{/each}
		<form
			class="new-template"
			onsubmit={(e) => {
				e.preventDefault();
				void addTemplate();
			}}
		>
			<label class="field narrow">
				<span>Template name</span>
				<input type="text" bind:value={newName} placeholder="prolific" />
			</label>
			<label class="field">
				<span>Address</span>
				<input type="text" inputmode="url" bind:value={newUrl} placeholder="https://app.prolific.com/submissions/complete?cc=&#123;cc&#125;" />
			</label>
			{#each newPlaceholders as p (p)}
				<label class="field narrow">
					<span>Pattern for <code>{'{' + p + '}'}</code> (optional)</span>
					<input type="text" value={newPatterns[p] ?? ''} placeholder={DEFAULT_PARAM_PATTERN} oninput={(e) => (newPatterns = { ...newPatterns, [p]: e.currentTarget.value })} />
				</label>
			{/each}
			<div>
				<button type="submit" class="btn" disabled={!newName.trim() || !newUrl.trim()}>Add template</button>
			</div>
		</form>
		{#each templateDiags as d (d.code + d.pointer + d.message)}
			<p class={d.severity === 'error' ? 'problem' : 'warn'} data-code={d.code}>{d.message}</p>
		{/each}
		{#if templateProblemText}<p class="problem" role="alert">{templateProblemText}</p>{/if}
	</section>
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
	.btn:disabled {
		opacity: 0.6;
		cursor: default;
	}
	.redirect {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin: 0;
		padding: var(--space-2) var(--space-3) var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
	}
	.redirect legend {
		padding-inline: var(--space-1);
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
	}
	.url {
		overflow-wrap: anywhere;
	}
	.template {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		padding-block: var(--space-1);
		border-block-end: 1px solid var(--color-border);
	}
	.tline {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
	}
	.tname {
		font-weight: var(--weight-semibold, 600);
	}
	.turl {
		overflow-wrap: anywhere;
	}
	.new-template {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
</style>
