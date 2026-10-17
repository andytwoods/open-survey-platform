<script lang="ts">
	/**
	 * Preview + debugger (task B11, builder-design §5, runtime-design §9). The draft is
	 * compiled to a plan (`POST /preview-plan`) and shown in device frames that run the real
	 * participant app (`web/runtime`) in preview mode: nothing is saved, storage is memory
	 * only. The debugger next to it steps the same run.
	 */
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import { Button } from '@osp/ui-components';
	import { onMount } from 'svelte';
	import DebuggerPanel from '../debugger/DebuggerPanel.svelte';
	import { link } from '../host/links';
	import { frameUrl } from './bridge';
	import { DEVICES, PreviewHost, randomSeed, type Device } from './host.svelte';

	let { surveyId, revision, onclose }: { surveyId: string; revision: number; onclose: () => void } = $props();

	const host = new PreviewHost(1);
	let device = $state<Device>('phone');
	let sideBySide = $state(false);
	let seedText = $state('1');
	let stageWidth = $state(800);
	let closeButton = $state<HTMLElement | null>(null);

	const shown = $derived(sideBySide ? DEVICES : DEVICES.filter((d) => d.id === device));
	const GAP = 24;
	const scale = $derived.by(() => {
		const need = shown.reduce((s, d) => s + d.width, 0) + GAP * (shown.length - 1) + 48;
		return Math.min(1, stageWidth / need);
	});
	// The frame page is the host's previewFrame link; it gets our origin to answer to (D10).
	const frameTemplate = link('previewFrame');
	const frameOrigin = new URL(frameTemplate, location.href).origin;
	const frameSrc = (id: string) => frameUrl(frameTemplate, id, location.origin);
	const iframes: Record<string, HTMLIFrameElement | null> = {};
	// Frames no longer shown (side by side switched off) stop receiving the run.
	$effect(() => {
		const ids = new Set(shown.map((d) => d.id));
		for (const d of DEVICES) if (!ids.has(d.id)) host.detach(d.id);
	});
	const errors = $derived(host.diagnostics.filter((d) => d.severity === 'error'));
	const stale = $derived(host.revision !== null && host.revision !== revision);

	function applySeed() {
		const n = Number(seedText);
		if (!Number.isSafeInteger(n) || n < 1) {
			seedText = String(host.seed);
			return;
		}
		host.seed = n;
		host.restart();
	}

	onMount(() => {
		const off = host.install(window, frameOrigin, (id) => iframes[id]?.contentWindow ?? null);
		void host.fetch(surveyId);
		closeButton?.focus();
		return off;
	});
</script>

<div class="preview" data-testid="preview">
	<div class="toolbar" role="toolbar" aria-label="Preview controls">
		<Button bind:ref={closeButton} size="sm" onclick={onclose}>
			<ArrowLeft size={16} aria-hidden="true" />
			Back to editor
		</Button>
		<h2 id="preview-heading">Preview</h2>
		<fieldset class="devices" disabled={sideBySide}>
			<legend class="osp-visually-hidden">Device</legend>
			{#each DEVICES as d (d.id)}
				<label class:on={device === d.id}>
					<input type="radio" name="preview-device" value={d.id} bind:group={device} />
					{d.label} <span class="muted">{d.width}</span>
				</label>
			{/each}
		</fieldset>
		<label class="check"><input type="checkbox" bind:checked={sideBySide} /> Side by side</label>
		<form
			class="seed"
			onsubmit={(e) => {
				e.preventDefault();
				applySeed();
			}}
		>
			<label>Seed <input type="number" min="1" bind:value={seedText} data-testid="preview-seed" /></label>
			<Button type="submit" size="sm">Use seed</Button>
			<Button
				size="sm"
				onclick={() => {
					seedText = String(randomSeed());
					applySeed();
				}}>Random seed</Button
			>
		</form>
		<Button size="sm" variant="primary" onclick={() => host.restart()}>
			<RotateCcw size={16} aria-hidden="true" />
			Restart
		</Button>
		<Button size="sm" onclick={() => void host.fetch(surveyId)}>Rebuild from draft</Button>
	</div>
	<p class="note">
		Preview mode: answers stay in this browser tab and are never saved.
		{#if stale}<strong>The draft has changed since this preview was built.</strong>{/if}
	</p>

	<div class="body">
		<!-- The frames area scrolls: focusable, so keyboard users can scroll it. -->
		<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
		<section class="stage" aria-label="Device frames" tabindex="0" bind:clientWidth={stageWidth}>
			{#if host.loading && !host.plan}
				<p role="status">Building the preview…</p>
			{:else if host.error}
				<p role="alert">{host.error}</p>
			{:else if !host.plan}
				<div role="alert">
					<p>The preview can't run until these are fixed:</p>
					<ul>
						{#each errors as d, i (i)}<li>{d.message} <code>{d.pointer}</code></li>{/each}
					</ul>
				</div>
			{:else}
				<div class="frames" style:gap={`${GAP * scale}px`}>
					{#each shown as d (d.id)}
						<figure class="frame" style:width={`${d.width * scale}px`} style:height={`${d.height * scale + 28}px`}>
							<figcaption>{d.label} · {d.width} px</figcaption>
							<div class="viewport" style:width={`${d.width * scale}px`} style:height={`${d.height * scale}px`}>
								<iframe
									bind:this={iframes[d.id]}
									title={`Survey preview, ${d.label.toLowerCase()} (${d.width} px)`}
									src={frameSrc(d.id)}
									sandbox="allow-scripts allow-same-origin allow-forms"
									width={d.width}
									height={d.height}
									style:transform={`scale(${scale})`}
									data-testid={`preview-frame-${d.id}`}
								></iframe>
							</div>
						</figure>
					{/each}
				</div>
			{/if}
		</section>
		<aside class="side" aria-labelledby="debugger-heading">
			<DebuggerPanel {host} {surveyId} />
		</aside>
	</div>
</div>

<style>
	.preview {
		display: flex;
		flex-direction: column;
		flex: 1;
		min-height: 0;
		min-width: 0;
		overflow: hidden;
		background: var(--color-bg);
	}
	.toolbar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-3);
		padding: var(--space-2) var(--space-3);
		border-bottom: 1px solid var(--color-border);
		background: var(--color-surface);
	}
	h2 {
		margin: 0;
		font-size: var(--text-md);
	}
	.devices {
		display: inline-flex;
		margin: 0;
		padding: 2px;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-sunken);
	}
	.devices label {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-sm);
		cursor: pointer;
	}
	.devices label.on {
		background: var(--color-surface-raised);
		font-weight: var(--weight-bold);
	}
	.devices input {
		margin: 0;
	}
	.devices label:focus-within {
		outline: 2px solid var(--color-focus);
	}
	.devices:disabled {
		opacity: 0.6;
	}
	.check,
	.seed label {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		font-size: var(--text-sm);
	}
	.seed {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
	}
	.seed input {
		width: 8rem;
		padding: var(--space-1);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-sm);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
	}
	.seed input:focus-visible {
		outline: 2px solid var(--color-focus);
	}
	.muted {
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.note {
		margin: 0;
		padding: var(--space-1) var(--space-3);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		border-bottom: 1px solid var(--color-border);
	}
	.body {
		display: flex;
		flex: 1;
		min-height: 0;
	}
	.stage {
		flex: 1;
		min-width: 0;
		overflow: auto;
		padding: var(--space-4);
		background: var(--color-surface-sunken);
	}
	.frames {
		display: flex;
		align-items: flex-start;
		justify-content: center;
	}
	.frame {
		margin: 0;
		flex: none;
	}
	figcaption {
		height: 28px;
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	.viewport {
		overflow: hidden;
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: #fff;
		box-shadow: var(--shadow-lg);
	}
	iframe {
		display: block;
		border: 0;
		transform-origin: 0 0;
	}
	.side {
		width: min(28rem, 45vw);
		flex: none;
		overflow: auto;
		border-inline-start: 1px solid var(--color-border);
		background: var(--color-surface);
	}
	@media (max-width: 900px) {
		.body {
			flex-direction: column;
			overflow: auto;
		}
		.side {
			width: auto;
			border-inline-start: 0;
			border-top: 1px solid var(--color-border);
		}
		.stage {
			flex: none;
		}
	}
</style>
