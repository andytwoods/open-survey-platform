// Page entry `themes`: The lab's theme library (no survey).
// Exports `mount(el, config)` and auto-mounts from the config tag (src/lib/host/mount.ts).
import { autoMount, definePage } from '#lib/host/mount.js';
import Shell from '#lib/shell/Shell.svelte';

export const mount = definePage({
	name: 'themes',
	component: Shell,
	props: () => ({ view: 'appearance' })
});

autoMount(mount, { name: 'themes' });
