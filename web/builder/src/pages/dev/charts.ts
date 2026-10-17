// Dev-only gallery entry `dev-charts` (Results charts); not in the production build.
import { autoMount, definePage } from '#lib/host/mount.js';
import Page from '../../dev/charts/Page.svelte';

export const mount = definePage({ name: 'dev-charts', component: Page, identity: false });

autoMount(mount, { name: 'dev-charts' });
