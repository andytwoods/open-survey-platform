<script lang="ts">
	/**
	 * Inside a device frame (`/preview-frame`): the participant app (`web/runtime`) in preview
	 * mode, on the plan the host hands over. Every engine change goes back to the host.
	 */
	import { snapshot, type Plan, type Snapshot } from '@osp/engine';
	import { previewEnv, RuntimeApp, type PreviewMount, type Session } from '@osp/runtime/preview';
	import { onMount } from 'svelte';
	import { findHost, type FrameConfig, type PreviewBridge } from './bridge';

	let mount = $state.raw<PreviewMount | null>(null);
	let key = $state(0);
	let missing = $state(false);
	let host: PreviewBridge | null = null;
	let current: Session | null = null;
	let frameId = '';

	async function load(cfg: FrameConfig) {
		current?.dispose();
		current = null;
		const plan = JSON.parse(cfg.planJson) as Plan;
		const snap = cfg.snapshotJson ? (JSON.parse(cfg.snapshotJson) as Snapshot) : null;
		const m = await previewEnv({
			plan,
			sessionSeed: cfg.sessionSeed,
			assigned: JSON.parse(JSON.stringify(cfg.assigned)),
			quotas: JSON.parse(JSON.stringify(cfg.quotas)),
			snapshot: snap,
			language: cfg.language,
			onSession: (s) => {
				current = s;
				let last = -1;
				let lastPhase = '';
				const report = () => {
					if (current !== s) return;
					const snapNow = snapshot(s.state);
					if (snapNow.revision === last && s.phase === lastPhase) return;
					last = snapNow.revision;
					lastPhase = s.phase;
					host?.changed(frameId, cfg.key, JSON.stringify(snapNow), s.phase);
				};
				s.subscribe(report);
				report();
			}
		});
		key = cfg.key;
		mount = m;
	}

	onMount(() => {
		// The builder's own light/dark choice must not leak into the participant page.
		delete document.documentElement.dataset.theme;
		frameId = new URLSearchParams(location.search).get('frame') ?? 'frame';
		host = findHost(window);
		if (!host) {
			missing = true;
			return;
		}
		const cfg = host.attach(frameId, { load: (c) => void load(c) });
		if (cfg) void load(cfg);
		return () => {
			current?.dispose();
			host?.detach(frameId);
		};
	});
</script>

{#if missing}
	<main><p>This page shows a survey preview inside the builder. Open Preview from the editor.</p></main>
{:else if mount}
	{#key key}
		<RuntimeApp preview={mount} />
	{/key}
{/if}
