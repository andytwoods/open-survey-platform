// Page entry `bank`: the lab's question bank (no survey). Optional host link (task QB5).
// Exports `mount(el, config)` and auto-mounts from the config tag (src/lib/host/mount.ts).
import { autoMount, definePage } from '#lib/host/mount.js';
import Shell from '#lib/shell/Shell.svelte';

export const mount = definePage({
	name: 'bank',
	component: Shell,
	props: () => ({ view: 'bank' })
});

autoMount(mount, { name: 'bank' });
