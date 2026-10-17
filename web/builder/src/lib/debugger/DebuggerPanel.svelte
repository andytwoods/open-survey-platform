<script lang="ts">
	/**
	 * The debugger (task B11, builder-design §5): the run the preview shows, explained. The
	 * engine decides everything; this panel reads `@osp/engine` and the preview host.
	 */
	import { Button } from '@osp/ui-components';
	import { context, result, view } from '@osp/engine';
	import type { PreviewHost } from '../preview/host.svelte';
	import { DebuggerState } from './debugger.svelte';
	import { branches, explainPage, show } from './explain';
	import { blockOfPage } from './script';
	import SimulationPanel from './SimulationPanel.svelte';

	let { host, surveyId }: { host: PreviewHost; surveyId: string } = $props();

	// The host lives as long as this panel.
	// svelte-ignore state_referenced_locally
	const dbg = new DebuggerState(host);

	const run = $derived.by(() => {
		void host.version;
		return host.state;
	});
	const v = $derived(run ? view(run) : null);
	const ctx = $derived(run ? context(run) : null);
	const res = $derived(run ? result(run) : null);
	const items = $derived(run ? explainPage(run, host.texts) : []);
	const flowBranches = $derived(run ? branches(run, host.texts) : []);
	const path = $derived(run ? run.data.history.map((h) => blockOfPage(run.plan, h.page) ?? h.page) : []);
	const trace = $derived.by(() => {
		void host.version;
		void dbg.cursor;
		return dbg.trace();
	});
	const diffs = $derived.by(() => {
		void host.version;
		void dbg.cursor;
		void dbg.expected;
		return dbg.diffs();
	});
	const following = $derived.by(() => {
		void host.version;
		void dbg.script;
		return dbg.following();
	});

	/** Answers typed for the next step, by question id (raw text). */
	let typed = $state<Record<string, string>>({});
	let lastPage = '';
	$effect(() => {
		const key = v ? `${v.page}#${v.trial}` : '';
		if (key === lastPage) return;
		lastPage = key;
		const out: Record<string, string> = {};
		for (const it of v?.items ?? []) {
			if (it.rows) for (const r of it.rows) out[r.id] = r.value === null ? '' : JSON.stringify(r.value);
			else if (it.type !== 'note') out[it.id] = it.value === null ? '' : JSON.stringify(it.value);
		}
		typed = out;
	});

	let scriptText = $state('');
	let expectedText = $state('');
	let exported = $state('');
	const exportHref = $derived(exported ? `data:application/json;charset=utf-8,${encodeURIComponent(exported)}` : '');

	async function readFile(e: Event, into: 'script' | 'expected') {
		const f = (e.currentTarget as HTMLInputElement).files?.[0];
		if (!f) return;
		const text = await f.text();
		if (into === 'script') {
			scriptText = text;
			dbg.loadScript(text);
		} else {
			expectedText = text;
			dbg.loadExpected(text);
		}
	}

	const eventText = (e: Record<string, unknown>) => {
		const { seq: _s, t: _t, rev: _r, type: _ty, ...rest } = e;
		void _s;
		void _t;
		void _r;
		void _ty;
		return JSON.stringify(rest);
	};
</script>

<div class="debugger" data-testid="debugger">
	<h2 id="debugger-heading">Debugger</h2>
	{#if dbg.message}<p class="message" role="status">{dbg.message}</p>{/if}

	{#if !run || !v}
		<p class="muted">Nothing to debug yet.</p>
	{:else}
		<section aria-labelledby="dbg-page">
			<h3 id="dbg-page">Current page</h3>
			<dl class="facts">
				<dt>Page</dt>
				<dd data-testid="dbg-page">{v.status === 'ended' ? `Ended (${res?.end ?? ''})` : (blockOfPage(run.plan, v.page) ?? '–')}</dd>
				<dt>Status</dt>
				<dd>{v.status}{v.status === 'pending' && v.effect?.kind === 'quota' ? `: quota check ${v.effect.nodeId}` : ''}</dd>
				<dt><code>$trial</code></dt>
				<dd data-testid="dbg-trial">{v.trial || '–'}</dd>
				<dt><code>$position</code></dt>
				<dd>{v.position ? `${v.position.index} of ${v.position.of} in ${v.position.randomiserId}` : '–'}</dd>
				<dt>Path so far</dt>
				<dd data-testid="dbg-path">{path.join(' → ') || '–'}</dd>
				<dt>Seed</dt>
				<dd>{run.data.sessionSeed}</dd>
			</dl>
		</section>

		<section aria-labelledby="dbg-questions">
			<h3 id="dbg-questions">Questions on this page</h3>
			{#if items.length === 0}
				<p class="muted">No page is shown.</p>
			{:else}
				<ul class="items">
					{#each items as it (it.id)}
						<li data-testid="dbg-item" data-id={it.id} data-visible={it.visible} data-state={it.state ?? ''}>
							<div class="item-head">
								<code>{it.id}</code>
								<span class="pill" data-on={it.visible}>{it.visible ? 'Shown' : 'Hidden'}</span>
								{#if it.state}<span class="muted">{it.state}{it.value !== null ? ` = ${show(it.value)}` : ''}</span>{/if}
							</div>
							<p class="reason">{it.reason.summary}</p>
							{#if it.reason.condition}
								<p class="cond">
									Show if <code data-testid="dbg-condition">{it.reason.condition}</code>
									{#if it.reason.evaluated !== null}→ <strong>{it.reason.evaluated ? 'true' : 'not true'}</strong>{/if}
								</p>
							{/if}
							{#if it.reason.reads.length}
								<ul class="reads">
									{#each it.reason.reads as r (r.id)}
										<li><code>{r.id}</code> = <code>{show(r.value)}</code> <span class="muted">({r.note})</span></li>
									{/each}
								</ul>
							{/if}
							{#if !it.reason.agrees}<p class="warn">The engine decided otherwise; its verdict is what participants get.</p>{/if}
						</li>
					{/each}
				</ul>
			{/if}
		</section>

		<section aria-labelledby="dbg-step">
			<h3 id="dbg-step">Step</h3>
			{#if v.status === 'page'}
				<form
					class="answers"
					onsubmit={(e) => {
						e.preventDefault();
						dbg.stepNext(typed);
					}}
				>
					{#each Object.keys(typed) as id (id)}
						<label>
							<code>{id}</code>
							<input bind:value={typed[id]} placeholder="JSON or text" data-testid="dbg-answer" data-id={id} />
						</label>
					{/each}
					<div class="row">
						<Button type="submit" variant="primary" size="sm">Next page</Button>
						<Button size="sm" disabled={!dbg.canBack()} onclick={() => dbg.back()}>Back</Button>
						<Button size="sm" onclick={() => dbg.restart()}>Restart run</Button>
					</div>
				</form>
			{:else if v.status === 'consent'}
				<p>The consent page is shown.</p>
				<div class="row">
					<Button size="sm" variant="primary" onclick={() => dbg.consent('agree')}>Agree</Button>
					<Button size="sm" onclick={() => dbg.consent('decline')}>Decline</Button>
				</div>
			{:else}
				<div class="row">
					<Button size="sm" disabled={!dbg.canBack()} onclick={() => dbg.back()}>Back</Button>
					<Button size="sm" onclick={() => dbg.restart()}>Restart run</Button>
				</div>
			{/if}
		</section>

		<section aria-labelledby="dbg-script">
			<h3 id="dbg-script">Script</h3>
			<label class="block">
				Script JSON (<code>osp-fixture-script/0</code>)
				<textarea rows="4" bind:value={scriptText} data-testid="dbg-script-text"></textarea>
			</label>
			<div class="row">
				<Button size="sm" onclick={() => dbg.loadScript(scriptText)}>Load script</Button>
				<label class="file">Or a file <input type="file" accept=".json,application/json" onchange={(e) => void readFile(e, 'script')} /></label>
			</div>
			{#if dbg.script}
				<p data-testid="dbg-script-pos">
					Step {dbg.cursor} of {dbg.script.actions.length}{following ? '' : ' (left the script: a participant step in the preview)'}
				</p>
				<div class="row">
					<Button size="sm" disabled={dbg.cursor >= dbg.script.actions.length} onclick={() => dbg.stepScript()}>Play next action</Button>
					<Button size="sm" onclick={() => dbg.jump(dbg.script!.actions.length)}>Play to the end</Button>
				</div>
				<ol class="actions" start="0" aria-label="Script steps">
					<li><button type="button" class="link" aria-current={dbg.cursor === 0 ? 'step' : undefined} onclick={() => dbg.jump(0)}>Start</button></li>
					{#each dbg.script.actions as a, i (i)}
						<li>
							<button type="button" class="link" aria-current={dbg.cursor === i + 1 ? 'step' : undefined} onclick={() => dbg.jump(i + 1)}>
								{a.do}{a.expectPage ? ` on ${a.expectPage}` : ''}{a.set ? ` with ${Object.keys(a.set).join(', ')}` : ''}
							</button>
						</li>
					{/each}
				</ol>
				<label class="block">
					Expected trace JSON (<code>osp-fixture-expected/0</code>), to compare
					<textarea rows="3" bind:value={expectedText} data-testid="dbg-expected-text"></textarea>
				</label>
				<div class="row">
					<Button size="sm" onclick={() => dbg.loadExpected(expectedText)}>Compare with expected</Button>
					<label class="file">Or a file <input type="file" accept=".json,application/json" onchange={(e) => void readFile(e, 'expected')} /></label>
				</div>
				{#if diffs}
					{#if diffs.length === 0}
						<p class="ok" data-testid="dbg-compare" data-match="true">Step {dbg.cursor} matches the expected trace.</p>
					{:else}
						<div data-testid="dbg-compare" data-match="false">
							<p class="warn">Step {dbg.cursor} differs from the expected trace:</p>
							<ul>
								{#each diffs as d (d.path)}
									<li><code>{d.path}</code>: expected <code>{show(d.expected)}</code>, got <code>{show(d.actual)}</code></li>
								{/each}
							</ul>
						</div>
					{/if}
				{/if}
			{/if}
			<div class="row">
				<Button size="sm" onclick={() => (exported = dbg.exportRun())}>Export run as script</Button>
				{#if exportHref}
					<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- a data: download -->
					<a href={exportHref} download="debugger-run.json">Download</a>
				{/if}
			</div>
			{#if exported}
				<label class="block">
					Exported script
					<textarea rows="5" readonly value={exported} data-testid="dbg-exported"></textarea>
				</label>
			{/if}
		</section>

		<section aria-labelledby="dbg-random">
			<h3 id="dbg-random">Randomisation and conditions</h3>
			{#if res}
				<dl class="facts">
					<dt>Conditions</dt>
					<dd data-testid="dbg-conditions">
						{#each Object.entries(res.conditions) as [k, val] (k)}
							<div><code>{k}</code> = <code>{show(val)}</code> <span class="muted">({res.conditionSources[k]}{run.data.assignReached[k] ? '' : ', not reached yet'})</span></div>
						{:else}none{/each}
					</dd>
					<dt>Block orders</dt>
					<dd data-testid="dbg-orders">
						{#each Object.entries(res.orders.blocks) as [k, val] (k)}
							<div><code>{k}</code>: {val.join(', ')}</div>
						{:else}none{/each}
					</dd>
					<dt>Item orders</dt>
					<dd>
						{#each Object.entries(res.orders.items) as [k, val] (k)}<div><code>{k}</code>: {val.join(', ')}</div>{:else}none{/each}
					</dd>
					<dt>Choice orders</dt>
					<dd>
						{#each Object.entries(res.orders.choices) as [k, val] (k)}<div><code>{k}</code>: {val.join(', ')}</div>{:else}none{/each}
					</dd>
					<dt>Pages done</dt>
					<dd>{ctx?.pagesDone ?? 0}</dd>
				</dl>
			{/if}
			{#if flowBranches.length}
				<h4>Branches (as they evaluate now)</h4>
				<ul class="reads">
					{#each flowBranches as b (b.id)}
						<li><code>{b.id}</code>: if <code>{b.condition ?? '…'}</code> → <strong>{b.now ? 'then' : 'else'}</strong></li>
					{/each}
				</ul>
			{/if}
		</section>

		<section aria-labelledby="dbg-events">
			<h3 id="dbg-events">Event log ({run.data.events.length})</h3>
			<ol class="events" start="0">
				{#each run.data.events as e (e.seq)}
					<li><code>{e.type}</code> <span class="muted">{eventText(e as unknown as Record<string, unknown>)}</span></li>
				{/each}
			</ol>
		</section>

		<details>
			<summary>Trace step (fixture format)</summary>
			<pre data-testid="debugger-trace">{JSON.stringify(trace, null, 1)}</pre>
		</details>
	{/if}

	<SimulationPanel {surveyId} />
</div>

<style>
	.debugger {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		padding: var(--space-3) var(--space-4) var(--space-6);
		font-size: var(--text-sm);
	}
	h2 {
		margin: 0;
		font-size: var(--text-lg);
	}
	h3 {
		margin: 0 0 var(--space-2);
		font-size: var(--text-md);
	}
	h4 {
		margin: var(--space-2) 0 var(--space-1);
		font-size: var(--text-sm);
	}
	section {
		border-top: 1px solid var(--color-border);
		padding-top: var(--space-3);
	}
	.facts {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: var(--space-1) var(--space-3);
		margin: 0;
	}
	.facts dt {
		color: var(--color-text-muted);
	}
	.facts dd {
		margin: 0;
		overflow-wrap: anywhere;
	}
	.items,
	.reads,
	.events {
		margin: 0;
		padding-inline-start: 0;
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.reads {
		gap: 0;
		padding-inline-start: var(--space-3);
	}
	.events {
		gap: 0;
		max-height: 14rem;
		overflow: auto;
		font-size: var(--text-xs);
		overflow-wrap: anywhere;
	}
	.items > li {
		padding: var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
	}
	.item-head {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		align-items: center;
	}
	.pill {
		padding: 0 var(--space-2);
		border-radius: var(--radius-full);
		background: var(--color-surface-sunken);
		font-weight: var(--weight-bold);
	}
	.pill[data-on='true'] {
		background: var(--color-accent-subtle);
	}
	.reason,
	.cond {
		margin: var(--space-1) 0 0;
	}
	.muted {
		color: var(--color-text-muted);
	}
	.warn {
		margin: var(--space-1) 0 0;
		color: var(--color-text);
		border-inline-start: 3px solid var(--color-warning);
		padding-inline-start: var(--space-2);
	}
	.ok {
		border-inline-start: 3px solid var(--color-success);
		padding-inline-start: var(--space-2);
	}
	.message {
		margin: 0;
		padding: var(--space-2);
		border-radius: var(--radius-sm);
		background: var(--color-surface-sunken);
	}
	.answers {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.answers label,
	.block {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	input:not([type='file']),
	textarea {
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-sm);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-family: var(--font-mono, monospace);
	}
	input:focus-visible,
	textarea:focus-visible,
	.link:focus-visible,
	summary:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		align-items: center;
		margin-top: var(--space-2);
	}
	.file {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.actions {
		margin: var(--space-2) 0;
		padding-inline-start: var(--space-5);
	}
	.link {
		padding: 0;
		border: 0;
		background: none;
		color: var(--color-accent);
		font: inherit;
		text-align: start;
		text-decoration: underline;
		cursor: pointer;
	}
	.link[aria-current='step'] {
		font-weight: var(--weight-bold);
		color: var(--color-text);
	}
	pre {
		max-height: 20rem;
		overflow: auto;
		font-size: var(--text-xs);
	}
	a {
		color: var(--color-accent);
	}
</style>
