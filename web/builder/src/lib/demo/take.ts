/**
 * "Take the study" (task DEMO2): the participant app (web/runtime) on the demo study's plan
 * (as edited in the demo builder in this tab, if it was: state.ts),
 * compiled in the browser, in preview mode (`@osp/runtime/preview`): start, saves and the
 * submit are answered in memory and dropped, so nothing leaves the page, and the session
 * ends on the study's real ending screen. `?lang=de` picks a language (default: the
 * browser's preference, as for participants).
 */
import { mount } from 'svelte';
import { previewEnv, RuntimeApp } from '@osp/runtime/preview';
import { compileDraft } from './plan';
import { restoreDraft } from './state';
import { demoStudy } from './study';

function seed(): number {
	const a = new Uint32Array(2);
	crypto.getRandomValues(a);
	// 1 … 2^53 − 1, as a participant session's seed.
	return ((a[0] & 0x1fffff) * 2 ** 32 + a[1]) % (2 ** 53 - 1) + 1;
}

export async function bootTake(): Promise<void> {
	const el = document.getElementById('app');
	if (!el) return;
	// The draft as edited in the demo builder (this tab), else the prespecified study.
	const { plan, diagnostics } = compileDraft(restoreDraft()?.survey ?? demoStudy());
	if (!plan) {
		console.error(diagnostics);
		el.textContent = 'The demo study could not be compiled.';
		return;
	}
	const lang = new URLSearchParams(location.search).get('lang');
	const language = lang && plan.languages.includes(lang) ? lang : undefined;
	const preview = await previewEnv({ plan, sessionSeed: seed(), language });
	mount(RuntimeApp, { target: el, props: { preview } });
}
