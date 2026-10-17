<script lang="ts">
	/**
	 * Inside a device frame (the previewFrame page): the participant app (`web/runtime`) in
	 * preview mode, on the plan the builder hands over by `postMessage`. Every engine change
	 * goes back the same way. Only messages from the parent window, from the builder origin
	 * named in `?origin=`, in our schema, are used (bridge.ts, D10). Researcher hooks run in the
	 * participant app's own sandbox (task R10); its diagnostics go back as `log` messages.
	 */
	import { snapshot, type Plan, type Snapshot } from '@osp/engine';
	import { previewEnv, RuntimeApp, type PreviewMount, type Session } from '@osp/runtime/preview';
	import { onMount } from 'svelte';
	import { isFrameId, logText, parseHostMessage, PROTOCOL, type FrameConfig, type FrameMessage } from './bridge';

	let mount = $state.raw<PreviewMount | null>(null);
	let key = $state(0);
	let missing = $state(false);
	let current: Session | null = null;
	let frameId = '';
	let builderOrigin = '';

	function send(msg: FrameMessage) {
		window.parent.postMessage(msg, builderOrigin);
	}

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
			log: (msg, detail) => send({ protocol: PROTOCOL, v: 1, type: 'log', frameId, key: cfg.key, message: logText(msg, detail) }),
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
					send({
						protocol: PROTOCOL,
						v: 1,
						type: 'changed',
						frameId,
						key: cfg.key,
						snapshotJson: JSON.stringify(snapNow),
						phase: s.phase
					});
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
		const q = new URLSearchParams(location.search);
		const id = q.get('frame') ?? 'frame';
		let origin: string;
		try {
			origin = new URL(q.get('origin') ?? '').origin;
		} catch {
			origin = '';
		}
		if (window.parent === window || !isFrameId(id) || !origin || origin === 'null') {
			missing = true;
			return;
		}
		frameId = id;
		builderOrigin = origin;
		const onMessage = (e: MessageEvent) => {
			if (e.source !== window.parent || e.origin !== builderOrigin) return;
			const msg = parseHostMessage(e.data);
			if (msg) void load(msg.cfg);
		};
		const detach = () => send({ protocol: PROTOCOL, v: 1, type: 'detach', frameId });
		window.addEventListener('message', onMessage);
		window.addEventListener('pagehide', detach);
		send({ protocol: PROTOCOL, v: 1, type: 'attach', frameId });
		return () => {
			window.removeEventListener('message', onMessage);
			window.removeEventListener('pagehide', detach);
			current?.dispose();
			detach();
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
