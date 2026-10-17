// Dev-only gallery entry `dev-components` (Components); not in the production build.
import { autoMount, definePage } from '#lib/host/mount.js';
import Page from '../../dev/components/Page.svelte';

export const mount = definePage({ name: 'dev-components', component: Page, identity: false });

autoMount(mount, { name: 'dev-components' });
