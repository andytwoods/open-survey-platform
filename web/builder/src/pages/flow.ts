// Page entry `flow`: One survey's flow (blocks, branching, randomisation).
// Exports `mount(el, config)` and auto-mounts from the config tag (src/lib/host/mount.ts).
import { autoMount, definePage } from '#lib/host/mount.js';
import SurveyEditor from '#lib/shell/SurveyEditor.svelte';

export const mount = definePage({
	name: 'flow',
	component: SurveyEditor,
	survey: true,
	props: (c) => ({ surveyId: c.surveyId, view: 'flow' })
});

autoMount(mount, { name: 'flow' });
