<script lang="ts">
	import { Button } from '@osp/ui-components';
	import { SimulationRun, unreachable } from './simulation.svelte';

	let { surveyId }: { surveyId: string } = $props();

	const sim = new SimulationRun();
	let n = $state(1000);
	let seed = $state(1);

	const r = $derived(sim.report);
	const fmt = (x: number | null | undefined, d = 3) => (x === null || x === undefined ? '–' : x.toFixed(d));
	const balanceText = (b: boolean | null) => (b === null ? 'too few to test' : b ? 'balanced' : 'imbalanced');
</script>

<section class="sim" aria-labelledby="sim-heading">
	<h3 id="sim-heading">Simulation</h3>
	<div class="row">
		<label>Participants <input type="number" min="1" max="10000" bind:value={n} /></label>
		<label>Seed <input type="number" min="0" bind:value={seed} /></label>
		<Button variant="primary" size="sm" disabled={sim.running} onclick={() => void sim.run(surveyId, n, seed)}>
			{sim.running ? 'Running…' : 'Run simulation'}
		</Button>
	</div>
	{#if sim.error}<p role="alert" class="error">{sim.error}</p>{/if}
	{#if r}
		<div data-testid="sim-report" aria-live="polite">
			<p>
				<span class="badge" data-coverage={r.coverage}>{r.coverage === 'exhaustive' ? 'Exhaustive' : 'Sampled'}</span>
				{r.participants} participants, {r.pathsSeen} distinct {r.pathsSeen === 1 ? 'path' : 'paths'}{r.pathSpace.paths !== null
					? ` (of ${r.pathSpace.paths})`
					: ''}.
			</p>
			{#if r.pathSpace.reasons.length}<p class="muted">Sampled because: {r.pathSpace.reasons.join('; ')}</p>{/if}
			<h4>Unreachable nodes</h4>
			{#if unreachable(r).length}
				<ul data-testid="sim-unreachable">
					{#each unreachable(r) as id (id)}<li><code>{id}</code></li>{/each}
				</ul>
			{:else}
				<p data-testid="sim-unreachable">None: every node was reached.</p>
			{/if}
			<h4>Balance checks</h4>
			{#if r.assignments.length || r.randomisers.length}
				<table>
					<thead><tr><th scope="col">What</th><th scope="col">Test</th><th scope="col">p</th><th scope="col">Result</th></tr></thead>
					<tbody>
						{#each r.assignments as a (a.variable)}
							<tr><td>Condition <code>{a.variable}</code></td><td>{a.test ?? '–'}</td><td>{fmt(a.pValue)}</td><td>{balanceText(a.balanced)}</td></tr>
						{/each}
						{#each r.randomisers as x (x.id)}
							<tr><td>Randomiser <code>{x.id}</code> ({x.observedOrders}/{x.possibleOrders} orders)</td><td>{x.test ?? '–'}</td><td>{fmt(x.pValue)}</td><td>{balanceText(x.balanced)}</td></tr>
						{/each}
					</tbody>
				</table>
			{:else}
				<p>No randomisers or assigned conditions to check.</p>
			{/if}
			<h4>Outcomes</h4>
			<ul>
				{#each Object.entries(r.outcomes) as [k, v] (k)}<li>{k}: {v}</li>{/each}
			</ul>
			{#if r.warnings.length}
				<h4>Warnings</h4>
				<ul>
					{#each r.warnings as w, i (i)}
						<li><strong>{w.severity}</strong> {w.message}{#if w.target} (<code>{w.target}</code>){/if}</li>
					{/each}
				</ul>
			{/if}
		</div>
	{/if}
</section>

<style>
	h3 {
		margin: 0 0 var(--space-2);
		font-size: var(--text-md);
	}
	h4 {
		margin: var(--space-3) 0 var(--space-1);
		font-size: var(--text-sm);
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		align-items: end;
	}
	label {
		display: flex;
		flex-direction: column;
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	input {
		width: 7rem;
		padding: var(--space-1);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-sm);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
	}
	.badge {
		padding: 0 var(--space-2);
		border-radius: var(--radius-full);
		background: var(--color-accent-subtle);
		color: var(--color-text);
		font-weight: var(--weight-bold);
	}
	.badge[data-coverage='sampled'] {
		background: var(--color-surface-sunken);
	}
	.muted {
		color: var(--color-text-muted);
	}
	.error {
		color: var(--color-danger, var(--color-text));
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
	}
	th,
	td {
		padding: var(--space-1);
		border-bottom: 1px solid var(--color-border);
		text-align: start;
	}
	ul {
		margin: 0;
		padding-inline-start: var(--space-4);
	}
</style>
