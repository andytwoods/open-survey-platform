// Dev-only gallery entry `dev-properties` (Property panel); not in the production build.
import { autoMount, definePage } from '#lib/host/mount.js';
import Page from '../../dev/properties/Page.svelte';

export const mount = definePage({ name: 'dev-properties', component: Page, identity: false });

autoMount(mount, { name: 'dev-properties' });
