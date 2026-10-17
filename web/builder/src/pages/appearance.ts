// Page entry `appearance`: One survey's appearance (its theme).
// Exports `mount(el, config)` and auto-mounts from the config tag (src/lib/host/mount.ts).
import { autoMount, definePage } from '#lib/host/mount.js';
import SurveyEditor from '#lib/shell/SurveyEditor.svelte';

export const mount = definePage({
	name: 'appearance',
	component: SurveyEditor,
	survey: true,
	props: (c) => ({ surveyId: c.surveyId, view: 'appearance' })
});

autoMount(mount, { name: 'appearance' });
