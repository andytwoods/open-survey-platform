// Dev-only gallery entry `dev-cards` (Question cards); not in the production build.
import { autoMount, definePage } from '#lib/host/mount.js';
import Page from '../../dev/cards/Page.svelte';

export const mount = definePage({ name: 'dev-cards', component: Page, identity: false });

autoMount(mount, { name: 'dev-cards' });
