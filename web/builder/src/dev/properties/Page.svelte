<script lang="ts">
	import { theme } from '@osp/ui-components';
	import fixture from '#lib/properties/fixtures/property-schemas.json';
	import PropertyPanel from '#lib/properties/PropertyPanel.svelte';
	import type { OpenEditorRequest, PanelDiagnostic, PropertySchemasDoc, SetPropertyOp } from '#lib/properties/types.js';
	import { onMount } from 'svelte';

	// Developer page for the property panel (task B4): every schema from the committed
	// fixture (what GET /api/meta/property-schemas serves), a fake server that echoes each
	// set_property back after a short delay (like a patch), an op log and a diagnostic.
	// Checked by e2e/properties.spec.ts.
	onMount(() => theme.init());

	const doc = fixture as unknown as PropertySchemasDoc;
	const ECHO_MS = 150;

	let type = $state('single');
	let language = $state('en');
	const schema = $derived(doc.schemas.find((s) => s.type === type)!);

	// Sample objects; content invented. Not a survey model: just enough for the panel.
	const initial = (): Record<string, Record<string, unknown>> => ({
		question: { id: 'q_sleep', label: { en: 'How many hours do you sleep?' } },
		page: { id: 'p_habits', title: { en: 'Habits' } },
		block: { id: 'b_sleep', title: 'Sleep' },
		survey: {
			metadata: { title: { en: 'Sleep and study habits' }, languages: ['en', 'de'] },
			settings: {}
		}
	});
	let objects = $state(initial());
	const target = $derived(
		schema.entity === 'question' ? { ...objects.question, type } : objects[schema.entity]
	);

	let log = $state<string[]>([]);
	let panel = $state<PropertyPanel | null>(null);

	const diagnostics: PanelDiagnostic[] = [
		{
			severity: 'error',
			code: 'expr.unknown_ref',
			message: 'The constraint refers to q_missing, which does not exist.',
			pointer: '/constraint'
		}
	];

	function onOp(op: SetPropertyOp) {
		log = [...log, JSON.stringify(op)];
		const { target: id, property, value, unset } = op.params;
		const key = id === '/metadata' || id === '/settings' ? 'survey' : schema.entity;
		setTimeout(() => {
			// The "server" echoes the edit back as a new object, like a patch would.
			const next: Record<string, unknown> = structuredClone($state.snapshot(objects[key]));
			const holder = (id.startsWith('/') ? (next[id.slice(1)] ??= {}) : next) as Record<string, unknown>;
			if (unset) delete holder[property];
			else holder[property] = value;
			objects = { ...objects, [key]: next };
		}, ECHO_MS);
	}

	function onOpenEditor(r: OpenEditorRequest) {
		log = [...log, `openEditor ${r.kind} ${r.path} on ${r.target}`];
	}
</script>


<main class="page">
	<h1>Property panel</h1>
	<div class="controls">
		<label>
			Type
			<select bind:value={type} data-testid="type">
				{#each doc.schemas as s (s.type)}<option value={s.type}>{s.type}</option>{/each}
			</select>
		</label>
		<label>
			Language
			<select bind:value={language} data-testid="language">
				<option value="en">en</option>
				<option value="de">de</option>
			</select>
		</label>
		<button type="button" onclick={() => panel?.focusProperty('constraint')} data-testid="diagnostic-link">
			Error: constraint refers to a missing question
		</button>
	</div>

	<div class="layout">
		<section class="panel" aria-labelledby="panel-h">
			<h2 id="panel-h">Properties</h2>
			<PropertyPanel
				bind:this={panel}
				{schema}
				{target}
				{language}
				defaultLanguage="en"
				{diagnostics}
				pointer=""
				survey={objects.survey}
				groups={doc.groups}
				{onOp}
				{onOpenEditor}
			/>
		</section>
		<section aria-labelledby="log-h">
			<h2 id="log-h">Ops</h2>
			<ol class="log" data-testid="op-log">
				{#each log as line, i (i)}<li><code>{line}</code></li>{/each}
			</ol>
		</section>
	</div>
</main>

<style>
	.page {
		max-width: 60rem;
		margin: 0 auto;
		padding: var(--space-5);
		color: var(--color-text);
	}
	h1 {
		font-size: var(--text-xl);
	}
	h2 {
		font-size: var(--text-md);
		color: var(--color-text-muted);
	}
	.controls {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-4);
		align-items: end;
		margin-block-end: var(--space-4);
		font-size: var(--text-sm);
	}
	.controls label {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.controls select,
	.controls button {
		height: var(--control-height);
		font: inherit;
		color: var(--color-text);
		background: var(--color-surface-raised);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		padding: 0 var(--space-2);
	}
	.layout {
		display: grid;
		grid-template-columns: minmax(0, 22rem) minmax(0, 1fr);
		gap: var(--space-5);
	}
	@media (max-width: 40rem) {
		.layout {
			grid-template-columns: minmax(0, 1fr);
		}
	}
	.panel {
		padding: var(--space-3) var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		background: var(--color-surface);
	}
	.log {
		margin: 0;
		padding-left: var(--space-5);
		font-size: var(--text-xs);
		overflow-wrap: anywhere;
	}
	.log code {
		font-family: var(--font-mono);
	}
</style>
