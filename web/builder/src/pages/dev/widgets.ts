// Dev-only gallery entry `dev-widgets` (Widgets); not in the production build.
import { autoMount, definePage } from '#lib/host/mount.js';
import Page from '../../dev/widgets/Page.svelte';

export const mount = definePage({ name: 'dev-widgets', component: Page, identity: false });

autoMount(mount, { name: 'dev-widgets' });
