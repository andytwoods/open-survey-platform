// Page entry `results`: one survey's results, a card per question (task V2,
// planning/results-viewer.md). The results view itself is a lazily loaded chunk, so the
// editor's pages never carry it (and the chart library V3 adds stays out of them too).
// Exports `mount(el, config)` and auto-mounts from the config tag (src/lib/host/mount.ts).
import { autoMount, definePage } from '#lib/host/mount.js';
import SurveyEditor from '#lib/shell/SurveyEditor.svelte';

export const mount = definePage({
	name: 'results',
	component: SurveyEditor,
	survey: true,
	props: (c) => ({ surveyId: c.surveyId, view: 'results' })
});

autoMount(mount, { name: 'results' });
