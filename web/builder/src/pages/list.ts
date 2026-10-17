// Page entry `list`: The survey list: create a survey, open one.
// Exports `mount(el, config)` and auto-mounts from the config tag (src/lib/host/mount.ts).
import { autoMount, definePage } from '#lib/host/mount.js';
import SurveyList from '#lib/shell/SurveyList.svelte';

export const mount = definePage({
	name: 'list',
	component: SurveyList
});

autoMount(mount, { name: 'list' });
