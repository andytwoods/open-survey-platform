<script lang="ts">
	import type { components } from '@osp/api-client';
	import { Button, Input, theme, Wordmark } from '@osp/ui-components';
	import { onMount } from 'svelte';
	import { api } from '../api';
	import { leaveTo, link, pageConfig } from '../host/links';
	import { session } from '../host/session.svelte';
	import ImportDialog from '../import/ImportDialog.svelte';

	type Summary = components['schemas']['SurveySummary'];

	// Who and which lab come from the host (GET /api/me, or the page config): no sign-in here.
	const memberships = $derived(session.identity?.memberships ?? []);
	const displayName = $derived(
		pageConfig()?.user?.displayName ?? session.identity?.displayName ?? session.identity?.userId ?? ''
	);
	const configuredLab = pageConfig()?.tenantId;
	let chosenLab = $state('');
	/** The lab a new survey goes into: the host's choice, the only lab, or the one picked. */
	const lab = $derived(configuredLab ?? (memberships.length === 1 ? memberships[0].tenantId : chosenLab));
	const chooseLab = $derived(!configuredLab && memberships.length > 1);

	let surveys = $state.raw<Summary[] | null>(null);
	let loadError = $state('');
	let title = $state('');
	let creating = $state(false);
	let createError = $state('');
	let importOpen = $state(false);

	const dateFmt = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' });

	async function load() {
		loadError = '';
		try {
			const { data, response } = await api.GET('/api/surveys');
			// The session banner explains a 401 or 403.
			if (response.status === 401 || response.status === 403) return;
			if (!data) throw new Error();
			surveys = [...data].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
		} catch {
			loadError = 'Could not load your surveys. Check your connection and reload.';
		}
	}

	async function create(e: SubmitEvent) {
		e.preventDefault();
		const t = title.trim();
		if (!t) return;
		creating = true;
		createError = '';
		try {
			const body = lab ? { title: t, tenantId: lab } : { title: t };
			const { data, error, response } = await api.POST('/api/surveys', { body });
			if (response.status === 401) return;
			if (!data) {
				createError = (error as { message?: string } | undefined)?.message ?? 'Could not create the survey.';
				return;
			}
			await leaveTo(link('editor', { id: data.id }));
		} catch {
			createError = 'Could not reach the server.';
		} finally {
			creating = false;
		}
	}

	onMount(() => {
		void load();
		return theme.init();
	});
</script>

<div class="page">
	<header class="top">
		<Wordmark />
		{#if displayName}
			<div class="who"><span class="email" data-testid="display-name">{displayName}</span></div>
		{/if}
	</header>

	<main class="content">
		<h2>Your surveys</h2>

		<form class="create" onsubmit={create}>
			<Input label="New survey title" bind:value={title} maxlength={500} required />
			{#if chooseLab}
				<label class="lab">
					<span>Lab</span>
					<select bind:value={chosenLab} required>
						<option value="" disabled>Choose a lab</option>
						{#each memberships as m (m.tenantId)}
							<option value={m.tenantId}>{m.tenantId}</option>
						{/each}
					</select>
				</label>
			{/if}
			<Button variant="primary" type="submit" disabled={creating || !title.trim() || (chooseLab && !lab)}>
				{creating ? 'Creating…' : 'Create survey'}
			</Button>
		</form>
		{#if createError}<p class="error" role="alert">{createError}</p>{/if}
		<p class="import-row">
			<span class="muted">Already have a survey elsewhere?</span>
			<Button variant="ghost" size="sm" onclick={() => (importOpen = true)} disabled={chooseLab && !lab}>
				Import from Qualtrics, LimeSurvey or SurveyJS…
			</Button>
		</p>
		<ImportDialog bind:open={importOpen} tenantId={lab || undefined} />

		{#if loadError}
			<p class="error" role="alert">{loadError}</p>
		{:else if surveys === null}
			<p class="muted" role="status">Loading…</p>
		{:else if surveys.length === 0}
			<p class="muted">No surveys yet. Create one above.</p>
		{:else}
			<ul class="list" aria-label="Surveys">
				{#each surveys as s (s.id)}
					<li>
						<a href={link('editor', { id: s.id })}>{s.title}</a>
						<span class="muted">Created {dateFmt.format(new Date(s.createdAt))}</span>
					</li>
				{/each}
			</ul>
		{/if}
	</main>
</div>

<style>
	.page {
		min-height: 100dvh;
		background: var(--color-bg);
		color: var(--color-text);
	}
	.top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-4);
		border-bottom: 1px solid var(--color-border);
		background: var(--color-surface);
	}
	.top :global(.wordmark) {
		margin: 0;
		font-size: var(--text-md);
	}
	.who {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
	}
	.email {
		color: var(--color-text-muted);
	}
	.content {
		max-width: 46rem;
		margin: 0 auto;
		padding: var(--space-6) var(--space-4);
	}
	h2 {
		margin: 0 0 var(--space-4);
		font-size: var(--text-lg);
	}
	.create {
		display: flex;
		align-items: flex-end;
		gap: var(--space-3);
		margin-bottom: var(--space-5);
	}
	.create :global(.osp-field) {
		flex: 1;
	}
	.import-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
		margin: calc(-1 * var(--space-3)) 0 var(--space-5);
	}
	.lab {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		font-size: var(--text-sm);
	}
	.lab select {
		min-height: 2.25rem;
		padding-inline: var(--space-2);
		border: 1px solid var(--color-border-strong, var(--color-border));
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: var(--color-text);
		font: inherit;
	}
	.list {
		display: flex;
		flex-direction: column;
		margin: 0;
		padding: 0;
		list-style: none;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
	}
	.list li {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
	}
	.list li + li {
		border-top: 1px solid var(--color-border);
	}
	.list a {
		color: var(--color-accent);
		font-weight: var(--weight-medium);
	}
	.muted {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.error {
		margin: 0 0 var(--space-3);
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
	@media (max-width: 480px) {
		.create {
			flex-direction: column;
			align-items: stretch;
		}
	}
</style>
