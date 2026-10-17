// Dev-only gallery entry `dev-choices` (Choice list editor); not in the production build.
import { autoMount, definePage } from '#lib/host/mount.js';
import Page from '../../dev/choices/Page.svelte';

export const mount = definePage({ name: 'dev-choices', component: Page, identity: false });

autoMount(mount, { name: 'dev-choices' });
