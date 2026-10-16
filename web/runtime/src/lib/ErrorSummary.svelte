<script lang="ts">
	import { ui } from './messages';

	/**
	 * Errors at the top of the page after a failed Next (runtime-design §6). Focus moves
	 * here; each link moves focus to its question's control. Not a live region: the focus
	 * move is the announcement, so nothing is read twice.
	 */
	type Props = {
		errors: Array<{ id: string; domId: string; label: string; message: string }>;
		el?: HTMLElement | null;
	};
	let { errors, el = $bindable(null) }: Props = $props();

	const FOCUSABLE =
		'input:not([type=hidden]):not([disabled]), textarea:not([disabled]), select:not([disabled]), [role=radio][tabindex="0"], [role=checkbox], button:not([disabled])';

	function go(e: MouseEvent, domId: string) {
		const q = document.querySelector(`[data-question="${CSS.escape(domId)}"]`);
		const target = q?.querySelector<HTMLElement>(FOCUSABLE);
		if (!q || !target) return;
		e.preventDefault();
		q.scrollIntoView({ block: 'start' });
		target.focus({ preventScroll: true });
	}
</script>

<section class="summary" tabindex="-1" aria-labelledby="error-summary-title" bind:this={el} data-testid="error-summary">
	<h2 id="error-summary-title">{ui.errorSummaryTitle}</h2>
	<ul>
		{#each errors as err (err.id)}
			<li>
				<a href={`#${err.domId}-label`} onclick={(e) => go(e, err.domId)}>{err.label} – {err.message}</a>
			</li>
		{/each}
	</ul>
</section>

<style>
	.summary {
		padding: var(--space-4);
		border: 3px solid var(--color-danger);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
	}
	.summary:focus-visible,
	.summary:focus {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 3px;
	}
	h2 {
		margin: 0 0 var(--space-2);
		font-size: var(--text-lg);
	}
	ul {
		margin: 0;
		padding-inline-start: var(--space-5);
	}
	li + li {
		margin-block-start: var(--space-2);
	}
	a {
		color: var(--color-danger);
		font-weight: var(--weight-medium);
		text-underline-offset: 0.15em;
	}
	a:focus-visible {
		outline: var(--focus-ring-width) solid var(--color-focus);
		outline-offset: 2px;
	}
</style>
