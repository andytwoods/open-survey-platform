<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { appTitle } from '#lib';
	import { auth, safeNext } from '#lib/auth.svelte.js';
	import { Button, Input, theme, Wordmark } from '@osp/ui-components';
	import { onMount, tick } from 'svelte';

	let step = $state<'password' | 'totp'>('password');
	let email = $state('');
	let password = $state('');
	let code = $state('');
	let recovery = $state(false);
	let busy = $state(false);
	let error = $state('');
	let codeInput = $state<HTMLInputElement | null>(null);

	const next = $derived(safeNext(page.url.searchParams.get('next')));

	onMount(() => theme.init());

	async function done() {
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- `next` is a checked same-app path
		await goto(next, { replaceState: true });
	}

	function message(r: 'failed' | 'offline' | 'mfa' | 'ok') {
		return r === 'offline'
			? 'Cannot reach the server. Check your connection and try again.'
			: 'Sign-in failed. Check your details and try again.';
	}

	async function submitPassword(e: SubmitEvent) {
		e.preventDefault();
		busy = true;
		error = '';
		const r = await auth.login(email.trim(), password);
		busy = false;
		if (r === 'ok') return done();
		if (r === 'mfa') {
			step = 'totp';
			password = '';
			await tick();
			codeInput?.focus();
			return;
		}
		error = message(r);
	}

	async function submitCode(e: SubmitEvent) {
		e.preventDefault();
		busy = true;
		error = '';
		const r = await auth.loginTotp(code.replace(/\s+/g, ''), recovery);
		busy = false;
		if (r === 'ok') return done();
		code = '';
		error =
			r === 'failed'
				? 'That code did not work. Codes expire quickly: sign in again if this keeps happening.'
				: message(r);
	}

	function restart() {
		step = 'password';
		code = '';
		error = '';
	}
</script>

<svelte:head>
	<title>Sign in · {appTitle}</title>
</svelte:head>

<main class="login">
	<div class="card">
		<Wordmark />
		{#if step === 'password'}
			<h2>Sign in</h2>
			<form onsubmit={submitPassword} novalidate>
				<Input label="Email" type="email" autocomplete="username" required bind:value={email} />
				<Input
					label="Password"
					type="password"
					autocomplete="current-password"
					required
					bind:value={password}
				/>
				{#if error}<p class="error" role="alert">{error}</p>{/if}
				<Button variant="primary" type="submit" disabled={busy || !email || !password}>
					{busy ? 'Signing in…' : 'Sign in'}
				</Button>
			</form>
		{:else}
			<h2>Two-step verification</h2>
			<p class="hint">
				{recovery
					? 'Enter one of your recovery codes.'
					: 'Enter the 6-digit code from your authenticator app.'}
			</p>
			<form onsubmit={submitCode} novalidate>
				<Input
					label={recovery ? 'Recovery code' : 'Authentication code'}
					autocomplete="one-time-code"
					inputmode={recovery ? 'text' : 'numeric'}
					required
					bind:ref={codeInput}
					bind:value={code}
				/>
				{#if error}<p class="error" role="alert">{error}</p>{/if}
				<Button variant="primary" type="submit" disabled={busy || !code.trim()}>
					{busy ? 'Checking…' : 'Verify'}
				</Button>
			</form>
			<div class="links">
				<Button variant="ghost" size="sm" onclick={() => (recovery = !recovery)}>
					{recovery ? 'Use an authenticator code' : 'Use a recovery code'}
				</Button>
				<Button variant="ghost" size="sm" onclick={restart}>Start again</Button>
			</div>
		{/if}
	</div>
</main>

<style>
	.login {
		display: grid;
		place-items: center;
		min-height: 100dvh;
		padding: var(--space-4);
		background: var(--color-bg);
		color: var(--color-text);
	}
	.card {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		width: min(24rem, 100%);
		padding: var(--space-6);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		background: var(--color-surface-raised);
		box-shadow: var(--shadow-sm);
	}
	.card :global(.wordmark) {
		margin: 0;
		font-size: var(--text-lg);
	}
	h2 {
		margin: 0;
		font-size: var(--text-md);
	}
	form {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.hint {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.error {
		margin: 0;
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
	.links {
		display: flex;
		justify-content: space-between;
		gap: var(--space-2);
	}
</style>
