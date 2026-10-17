// Page entry `profile`: The lab's property panel profile (no survey). Optional host link.
// Exports `mount(el, config)` and auto-mounts from the config tag (src/lib/host/mount.ts).
import { autoMount, definePage } from '#lib/host/mount.js';
import Shell from '#lib/shell/Shell.svelte';

export const mount = definePage({
	name: 'profile',
	component: Shell,
	props: () => ({ view: 'profile' })
});

autoMount(mount, { name: 'profile' });
