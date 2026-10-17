// Page entry `editor`: One survey's questions (outline, canvas, properties, JSON).
// Exports `mount(el, config)` and auto-mounts from the config tag (src/lib/host/mount.ts).
import { autoMount, definePage } from '#lib/host/mount.js';
import SurveyEditor from '#lib/shell/SurveyEditor.svelte';

export const mount = definePage({
	name: 'editor',
	component: SurveyEditor,
	survey: true,
	props: (c) => ({ surveyId: c.surveyId, view: 'editor' })
});

autoMount(mount, { name: 'editor' });
