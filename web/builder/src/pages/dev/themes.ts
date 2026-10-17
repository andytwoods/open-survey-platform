// Dev-only gallery entry `dev-themes` (Themes); not in the production build.
import { autoMount, definePage } from '#lib/host/mount.js';
import Page from '../../dev/themes/Page.svelte';

export const mount = definePage({ name: 'dev-themes', component: Page, identity: false });

autoMount(mount, { name: 'dev-themes' });
