<script lang="ts">
	import { javascript } from '@codemirror/lang-javascript';
	import { Button } from '@osp/ui-components';
	import TextEditor from '../conditions/TextEditor.svelte';
	import type { Outcome } from '../sync/survey-store.svelte';
	import type { Diagnostic, Invocation } from '../sync/transport';
	import {
		ACTIONS,
		CTX_FIELDS,
		DEFAULT_TIMEOUT_MS,
		HOOK_EVENTS,
		MAX_TIMEOUT_MS,
		advancedParts,
		draftOf,
		hookDiagnostics,
		hooksOf,
		hooksOp,
		manifestOf,
		sameManifest,
		starterManifest,
		staticProblems,
		type DraftProblem,
		type HooksDraft
	} from './hooks';

	/**
	 * Researcher hooks (survey.hooks, runtime-design.md §7a) through `set_hooks`: the script
	 * (CodeMirror, JavaScript), which events it handles and what each handler reads, with
	 * the sandbox's event list, `ctx` and action reference. Problems come from three places:
	 * this editor's own checks (a declared event the script never registers), the server's
	 * validation of the saved manifest (`hooks.*` diagnostics with pointers), and the
	 * Preview, which runs the hooks in the participant sandbox and lists every call, error
	 * and refused action in its debugger. Nothing runs researcher code on this page.
	 */
	let {
		survey,
		diagnostics = [],
		submit,
		onpreview
	}: {
		survey: unknown;
		diagnostics?: readonly Diagnostic[];
		submit: (ops: Invocation[]) => Promise<Outcome>;
		/** Opens the Preview (the dry run) once the draft is saved. */
		onpreview?: () => void;
	} = $props();

	const PLACEHOLDER = "osp.on('onPageShown', function (ctx, data, act) { … });";
	const saved = $derived(hooksOf(survey));
	const serverProblems = $derived(hookDiagnostics(diagnostics));
	const advanced = $derived(advancedParts(saved));

	let draft = $state<HooksDraft>(draftOf(null));
	// Follow the survey when it changes (a save echo, undo, another tab), not while typing.
	let lastSaved = '';
	$effect(() => {
		const key = JSON.stringify(saved);
		if (key !== lastSaved) {
			lastSaved = key;
			draft = draftOf(saved);
		}
	});

	const built = $derived(manifestOf(draft, saved));
	const dirty = $derived(!!saved && !sameManifest(built.manifest, saved));
	const problems = $derived<DraftProblem[]>([...built.problems, ...staticProblems(built.manifest)]);
	const canSave = $derived(dirty && built.problems.length === 0);

	let busy = $state(false);
	let problem = $state<string | null>(null);
	let status = $state<string | null>(null);

	async function send(ops: Invocation[]): Promise<boolean> {
		problem = null;
		status = null;
		busy = true;
		try {
			const out = await submit(ops);
			if (out.status === 'rejected') {
				problem = out.diagnostics[0]?.message ?? out.message;
				return false;
			}
			if (out.status !== 'applied') problem = out.message;
			return out.status === 'applied';
		} finally {
			busy = false;
		}
	}

	async function enable(on: boolean) {
		if (!on && saved && !confirm('Remove the hooks from this survey? Undo brings them back.')) return;
		await send([hooksOp(on ? starterManifest() : null)]);
	}

	async function save(): Promise<boolean> {
		if (!canSave) return !dirty;
		const ok = await send([hooksOp(built.manifest)]);
		if (ok) status = 'Hooks saved.';
		return ok;
	}

	function discard() {
		draft = draftOf(saved);
		problem = null;
	}

	async function preview() {
		if (dirty && !(await save())) return;
		onpreview?.();
	}
</script>

<div class="hooks">
	<label class="check">
		<input type="checkbox" checked={!!saved} disabled={busy} onchange={(e) => void enable(e.currentTarget.checked)} />
		<span>This survey runs custom code (researcher hooks)</span>
	</label>
	{#if !saved}
		<p class="help">
			Hooks are small JavaScript handlers that run on key events of a participant's session (page shown, Next
			pressed, submit…) in a sandbox: no network, no page access, deterministic time and randomness. They can
			record paradata and reject a page with a custom message. The code is published with the survey and is part
			of its version checksum.
		</p>
	{:else}
		<p class="help" id="hooks-source-help">
			Register handlers with <code>osp.on(event, function (ctx, data, act) &#123; … &#125;)</code>. The code is
			published with the survey; changing it is recorded in the audit log. Exports to other platforms leave it out.
		</p>
		<div class="source">
			<TextEditor
				value={draft.source}
				label="Hook script"
				describedBy="hooks-source-help"
				language={javascript()}
				placeholder={PLACEHOLDER}
				testid="hooks-source"
				onchange={(text) => (draft = { ...draft, source: text })}
			/>
		</div>

		<table class="events" aria-label="Handled events">
			<thead>
				<tr>
					<th scope="col">Handle</th>
					<th scope="col">Event</th>
					<th scope="col">Reads (question and variable ids)</th>
					<th scope="col">Timeout (ms)</th>
				</tr>
			</thead>
			<tbody>
				{#each HOOK_EVENTS as ev (ev.id)}
					{@const h = draft.handlers[ev.id]!}
					<tr data-testid="hooks-event" data-event={ev.id} data-on={h.on}>
						<td>
							<input
								type="checkbox"
								aria-label="Handle {ev.id}"
								checked={h.on}
								onchange={(e) =>
									(draft = { ...draft, handlers: { ...draft.handlers, [ev.id]: { ...h, on: e.currentTarget.checked } } })}
							/>
						</td>
						<td>
							<code>{ev.id}</code>
							<span class="when">{ev.when}. Data: {ev.data}.</span>
						</td>
						<td>
							<input
								type="text"
								aria-label="Reads for {ev.id}"
								placeholder="e.g. age, group"
								disabled={!h.on}
								value={h.reads}
								onchange={(e) =>
									(draft = { ...draft, handlers: { ...draft.handlers, [ev.id]: { ...h, reads: e.currentTarget.value } } })}
							/>
						</td>
						<td>
							<input
								type="number"
								class="timeout"
								aria-label="Timeout for {ev.id} in milliseconds"
								min="1"
								max={MAX_TIMEOUT_MS}
								placeholder={String(DEFAULT_TIMEOUT_MS)}
								disabled={!h.on}
								value={h.timeoutMs}
								onchange={(e) =>
									(draft = { ...draft, handlers: { ...draft.handlers, [ev.id]: { ...h, timeoutMs: e.currentTarget.value } } })}
							/>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
		<p class="help">
			A handler sees only what it reads (<code>ctx.results</code>, <code>ctx.vars</code>). A hook that is slower
			than its timeout fails: it is skipped unless a condition depends on it, in which case the participant is
			asked to retry.
		</p>
		{#if advanced.length}
			<p class="help" data-testid="hooks-advanced">
				Also declared (edit in the JSON view): {advanced.join('; ')}.
			</p>
		{/if}

		<div class="actions">
			<Button variant="primary" onclick={() => void save()} disabled={!canSave || busy} data-testid="hooks-save">Save hooks</Button>
			<Button variant="secondary" onclick={discard} disabled={!dirty || busy}>Discard changes</Button>
			<Button variant="secondary" onclick={() => void preview()} disabled={busy || built.problems.length > 0} data-testid="hooks-preview">
				{dirty ? 'Save and run in Preview' : 'Run in Preview'}
			</Button>
			{#if status}<span class="status" role="status" data-testid="hooks-status">{status}</span>{/if}
		</div>
		<p class="help">
			The Preview runs the hooks in the participant sandbox and its debugger lists every call with its actions,
			errors and refused actions.
		</p>

		{#if problem}<p class="problem" role="alert">{problem}</p>{/if}
		{#if problems.length || serverProblems.length}
			<ul class="problems" data-testid="hooks-problems" aria-label="Hook problems">
				{#each problems as p (p.pointer + p.message)}
					<li data-severity={p.severity}><strong>{p.severity}</strong> {p.message}</li>
				{/each}
				{#each serverProblems as d (d.code + d.pointer + d.message)}
					<li data-severity={d.severity} data-code={d.code}>
						<strong>{d.severity}</strong> {d.message} <span class="pointer">({d.pointer})</span>
					</li>
				{/each}
			</ul>
		{/if}

		<details class="reference">
			<summary>Reference: events, <code>ctx</code> and actions</summary>
			<h4>Events</h4>
			<dl>
				{#each HOOK_EVENTS as ev (ev.id)}
					<dt><code>{ev.id}</code></dt>
					<dd>{ev.when}. Data: {ev.data}.</dd>
				{/each}
			</dl>
			<h4><code>ctx</code> (read-only)</h4>
			<dl>
				{#each CTX_FIELDS as c (c.field)}
					<dt><code>{c.field}</code></dt>
					<dd>{c.meaning}</dd>
				{/each}
			</dl>
			<h4>Actions</h4>
			<dl>
				{#each ACTIONS as a (a.call)}
					<dt><code>{a.call}</code></dt>
					<dd>{a.meaning}</dd>
				{/each}
			</dl>
			<p class="help">
				Hooks never decide flow directly, cannot touch the page, and have no network: data leaves the platform
				only through declared redirects and parent messages, which an owner confirms.
			</p>
		</details>
	{/if}
</div>

<style>
	.hooks {
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
	.help {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	code {
		font-family: var(--font-mono);
		font-size: 0.95em;
	}
	.source :global(.cm-editor) {
		min-height: 12rem;
	}
	.events {
		border-collapse: collapse;
		font-size: var(--text-sm);
		inline-size: 100%;
	}
	.events th,
	.events td {
		padding: var(--space-1) var(--space-2);
		border-block-end: 1px solid var(--color-border);
		text-align: start;
		vertical-align: top;
	}
	.events input[type='text'],
	.events input[type='number'] {
		inline-size: 100%;
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
	}
	.events .timeout {
		max-inline-size: 7rem;
	}
	.when {
		display: block;
		color: var(--color-text-muted);
	}
	.actions {
		display: flex;
		gap: var(--space-2);
		align-items: center;
		flex-wrap: wrap;
	}
	.status {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.problem {
		margin: 0;
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
	.problems {
		margin: 0;
		padding-inline-start: var(--space-4);
		font-size: var(--text-sm);
	}
	.problems li[data-severity='error'] {
		color: var(--color-danger);
	}
	.problems li[data-severity='warning'] {
		color: var(--color-warning);
	}
	.pointer {
		color: var(--color-text-muted);
	}
	.reference {
		font-size: var(--text-sm);
	}
	.reference summary {
		cursor: pointer;
	}
	.reference h4 {
		margin: var(--space-3) 0 var(--space-1);
		font-size: var(--text-sm);
	}
	.reference dl {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: var(--space-1) var(--space-3);
		margin: 0;
	}
	.reference dd {
		margin: 0;
	}
</style>
