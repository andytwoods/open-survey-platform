<script lang="ts">
	import Copy from '@lucide/svelte/icons/copy';
	import Download from '@lucide/svelte/icons/download';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import { Button, Dialog, announce } from '@osp/ui-components';
	import { api } from '../api';
	import type { SurveyStore } from '../sync/survey-store.svelte';
	import {
		exportLinks,
		participantLink,
		problemsOf,
		reproLink,
		type PublishDiagnostic,
		type PublishProblem
	} from './model';

	/**
	 * Publish (task B12). Opening the dialog sends pending edits, then publishes: the server
	 * validates (errors, missing retention, theme contrast) and either refuses with the
	 * problems, listed here with links to where each is fixed, or freezes a new version.
	 */
	let {
		store,
		open = $bindable(false),
		ongo
	}: { store: SurveyStore; open?: boolean; ongo: (p: PublishProblem) => void } = $props();

	type Phase =
		| { kind: 'idle' }
		| { kind: 'publishing' }
		| { kind: 'blocked'; message: string; errors: PublishProblem[]; warnings: PublishProblem[] }
		| { kind: 'failed'; message: string }
		| {
				kind: 'published';
				number: number;
				link: string;
				warnings: PublishProblem[];
				repro: string;
		  };

	let phase = $state<Phase>({ kind: 'idle' });
	let copied = $state(false);
	let wasOpen = false;

	$effect(() => {
		if (open && !wasOpen) void publish();
		wasOpen = open;
	});

	async function publish() {
		phase = { kind: 'publishing' };
		copied = false;
		store.flushBuffers();
		await store.settled();
		try {
			const { data, error, response } = await api.POST('/api/surveys/{survey_id}/publish', {
				params: { path: { survey_id: store.surveyId } },
				body: { baseRevision: store.revision }
			});
			if (data) {
				const { warnings } = problemsOf(data.diagnostics as PublishDiagnostic[]);
				phase = {
					kind: 'published',
					number: data.number,
					link: participantLink(location.origin, data.slug),
					warnings,
					repro: reproLink(store.surveyId, data.number)
				};
				announce(`Published version ${data.number}.`);
				return;
			}
			const body = (error ?? {}) as { message?: string; diagnostics?: PublishDiagnostic[] };
			if (response.status === 422 && Array.isArray(body.diagnostics)) {
				phase = { kind: 'blocked', message: body.message ?? "Can't publish yet.", ...problemsOf(body.diagnostics) };
				announce("Can't publish yet: fix the problems listed.");
				return;
			}
			if (response.status === 409) void store.reload();
			phase = {
				kind: 'failed',
				message:
					response.status === 409
						? 'The survey changed meanwhile. It has been reloaded: publish again.'
						: (body.message ?? `Publishing failed (${response.status}).`)
			};
		} catch (e) {
			phase = { kind: 'failed', message: (e as Error)?.message || 'Network error.' };
		}
	}

	async function copyLink(link: string) {
		try {
			await navigator.clipboard.writeText(link);
			copied = true;
			announce('Participant link copied.');
		} catch {
			announce('Copy failed: select the link and copy it.');
		}
	}

	function go(p: PublishProblem) {
		open = false;
		ongo(p);
	}
</script>

<Dialog bind:open title="Publish" size="md" description="Publishing freezes a new version that participants can take.">
	{#if phase.kind === 'publishing' || phase.kind === 'idle'}
		<p role="status">Checking and publishing…</p>
	{:else if phase.kind === 'failed'}
		<p role="alert" class="bad">{phase.message}</p>
	{:else if phase.kind === 'blocked'}
		<div class="blocked" data-testid="publish-problems">
			<p role="alert"><strong>{phase.message}</strong></p>
			<ul class="problems">
				{#each phase.errors as p, i (i)}
					<li data-code={p.code}>
						<span class="sev">Error</span>
						<span class="msg">{p.message}</span>
						<button type="button" class="link" onclick={() => go(p)}>{p.action}</button>
					</li>
				{/each}
				{#each phase.warnings as p, i (`w${i}`)}
					<li data-code={p.code}>
						<span class="sev warn">Warning</span>
						<span class="msg">{p.message}</span>
						<button type="button" class="link" onclick={() => go(p)}>{p.action}</button>
					</li>
				{/each}
			</ul>
		</div>
	{:else}
		{@const s = phase}
		<div class="published" data-testid="publish-result">
			<p role="status"><strong>Published version {s.number}.</strong> Participants can start now.</p>
			<label class="field" for="participant-link">Participant link</label>
			<div class="link-row">
				<input id="participant-link" type="text" readonly value={s.link} onfocus={(e) => e.currentTarget.select()} />
				<Button size="sm" onclick={() => void copyLink(s.link)}>
					<Copy size={14} aria-hidden="true" />{copied ? 'Copied' : 'Copy link'}
				</Button>
				<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- participant app, not a builder route -->
				<a class="open" href={s.link} target="_blank" rel="noopener">
					<ExternalLink size={14} aria-hidden="true" />Open
				</a>
			</div>
			{#if s.warnings.length}
				<ul class="problems">
					{#each s.warnings as p, i (i)}
						<li data-code={p.code}>
							<span class="sev warn">Warning</span>
							<span class="msg">{p.message}</span>
							<button type="button" class="link" onclick={() => go(p)}>{p.action}</button>
						</li>
					{/each}
				</ul>
			{/if}
			<h3>Exports and records</h3>
			<ul class="exports">
				{#each exportLinks(store.surveyId) as x (x.href)}
					<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- API download -->
					<li><a href={x.href} download><Download size={14} aria-hidden="true" />{x.label}</a> <span>{x.description}</span></li>
				{/each}
				<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- API download -->
				<li><a href={s.repro} download><Download size={14} aria-hidden="true" />Reproducibility package</a> <span>Version {s.number}</span></li>
			</ul>
		</div>
	{/if}
	{#snippet footer()}
		{#if phase.kind === 'blocked' || phase.kind === 'failed'}
			<Button onclick={() => void publish()}>Try again</Button>
		{/if}
		<Button variant="primary" onclick={() => (open = false)}>{phase.kind === 'published' ? 'Done' : 'Close'}</Button>
	{/snippet}
</Dialog>

<style>
	.bad {
		color: var(--color-danger);
	}
	p {
		margin: 0 0 var(--space-3);
	}
	.problems,
	.exports {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin: 0 0 var(--space-3);
		padding: 0;
		list-style: none;
		font-size: var(--text-sm);
	}
	.problems li {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1) var(--space-2);
		align-items: baseline;
		padding: var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
	}
	.sev {
		font-weight: var(--weight-bold);
		color: var(--color-danger);
	}
	.sev.warn {
		color: var(--color-warning);
	}
	.msg {
		flex: 1 1 12rem;
	}
	.link {
		padding: 0;
		border: 0;
		background: none;
		color: var(--color-accent);
		font: inherit;
		text-decoration: underline;
		cursor: pointer;
		min-block-size: 1.5rem;
	}
	.link:focus-visible,
	a:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}
	.field {
		display: block;
		margin-bottom: var(--space-1);
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}
	.link-row {
		display: flex;
		gap: var(--space-2);
		align-items: center;
		flex-wrap: wrap;
		margin-bottom: var(--space-3);
	}
	.link-row input {
		flex: 1 1 16rem;
		min-block-size: 2.25rem;
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
	}
	a {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		color: var(--color-accent);
		min-block-size: 1.5rem;
	}
	h3 {
		margin: 0 0 var(--space-2);
		font-size: var(--text-sm);
	}
	.exports span {
		color: var(--color-text-muted);
	}
</style>
