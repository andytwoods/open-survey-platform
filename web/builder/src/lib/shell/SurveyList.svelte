<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import type { components } from '@osp/api-client';
	import { Button, Input, theme, Wordmark } from '@osp/ui-components';
	import { onMount } from 'svelte';
	import { api } from '../api';
	import { auth } from '../auth.svelte';

	type Summary = components['schemas']['SurveySummary'];

	let surveys = $state.raw<Summary[] | null>(null);
	let loadError = $state('');
	let title = $state('');
	let creating = $state(false);
	let createError = $state('');

	const dateFmt = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' });

	async function load() {
		loadError = '';
		try {
			const { data, response } = await api.GET('/api/surveys');
			if (response.status === 401) return auth.expired();
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
			const { data, error, response } = await api.POST('/api/surveys', { body: { title: t } });
			if (response.status === 401) return auth.expired();
			if (!data) {
				createError = (error as { message?: string } | undefined)?.message ?? 'Could not create the survey.';
				return;
			}
			await goto(resolve('/surveys/[id]', { id: data.id }));
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
		<div class="who">
			<span class="email">{auth.me?.email}</span>
			<Button variant="ghost" size="sm" onclick={() => void auth.logout()}>Sign out</Button>
		</div>
	</header>

	<main class="content">
		<h2>Your surveys</h2>

		<form class="create" onsubmit={create}>
			<Input label="New survey title" bind:value={title} maxlength={500} required />
			<Button variant="primary" type="submit" disabled={creating || !title.trim()}>
				{creating ? 'Creating…' : 'Create survey'}
			</Button>
		</form>
		{#if createError}<p class="error" role="alert">{createError}</p>{/if}

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
						<a href={resolve('/surveys/[id]', { id: s.id })}>{s.title}</a>
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
