// Dev-only gallery entry `dev-conditions` (Condition builder); not in the production build.
import { autoMount, definePage } from '#lib/host/mount.js';
import Page from '../../dev/conditions/Page.svelte';

export const mount = definePage({ name: 'dev-conditions', component: Page, identity: false });

autoMount(mount, { name: 'dev-conditions' });
