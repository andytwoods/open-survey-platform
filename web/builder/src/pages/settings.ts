// Page entry `settings`: One survey's settings (saving, retention, consent, languages).
// Exports `mount(el, config)` and auto-mounts from the config tag (src/lib/host/mount.ts).
import { autoMount, definePage } from '#lib/host/mount.js';
import SurveyEditor from '#lib/shell/SurveyEditor.svelte';

export const mount = definePage({
	name: 'settings',
	component: SurveyEditor,
	survey: true,
	props: (c) => ({ surveyId: c.surveyId, view: 'settings' })
});

autoMount(mount, { name: 'settings' });
