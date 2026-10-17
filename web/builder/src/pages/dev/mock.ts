// Dev-only entry `dev-mock` (`/?mock`): the shell over static mock data, no backend, for
// component and e2e tests. Not in the production build.
import { autoMount, definePage } from '#lib/host/mount.js';
import Shell from '#lib/shell/Shell.svelte';

export const mount = definePage({ name: 'dev-mock', component: Shell, identity: false });

autoMount(mount, { name: 'dev-mock' });
