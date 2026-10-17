import { Wordmark } from '@osp/ui-components';
import { afterEach, describe, expect, it } from 'vitest';
import { DEFAULT_LINKS } from './config';
import { pageConfig } from './links';
import { autoMount, defineFramePage, definePage, OspConfigError, type MountedPage } from './mount';

const CONFIG = { version: 1, apiBase: '/api', links: DEFAULT_LINKS };
let mounted: MountedPage | null = null;

function hostPage(config: string | null) {
	document.body.innerHTML = `<div id="osp"></div>${
		config === null ? '' : `<script type="application/json" id="osp-config">${config}</script>`
	}`;
	return document.getElementById('osp')!;
}

afterEach(() => {
	mounted?.unmount();
	mounted = null;
	document.body.innerHTML = '';
});

describe('page mount', () => {
	const page = definePage({ name: 'test', component: Wordmark, identity: false });

	it('auto-mounts from the config tag and sets the page config', () => {
		const el = hostPage(JSON.stringify(CONFIG));
		mounted = autoMount(page, { name: 'test' });
		expect(mounted).not.toBeNull();
		expect(el.textContent).toContain('Open Survey');
		expect(pageConfig()?.apiBase).toBe('/api');
	});

	it('does nothing without a config tag', () => {
		hostPage(null);
		expect(autoMount(page, { name: 'test' })).toBeNull();
	});

	it('rejects a bad config: nothing runs, the page says why', () => {
		const el = hostPage(JSON.stringify({ ...CONFIG, apiBase: 'https://evil.example/api' }));
		expect(() => page(el, JSON.parse(el.nextElementSibling!.textContent!))).toThrow(OspConfigError);
		expect(el.querySelector('[role="alert"]')?.textContent).toContain('apiBase: must be same-origin');
		expect(pageConfig()).toBeNull();
	});

	it('rejects a config tag that is not JSON', () => {
		const el = hostPage('{nope');
		expect(autoMount(page, { name: 'test' })).toBeNull();
		expect(el.textContent).toContain('config tag: not valid JSON');
	});

	it('a survey page needs surveyId', () => {
		const survey = definePage({ name: 'editor', component: Wordmark, identity: false, survey: true });
		const el = hostPage(null);
		expect(() => survey(el, CONFIG)).toThrow(/surveyId: required/);
		mounted = survey(el, { ...CONFIG, surveyId: 's1' });
		expect(pageConfig()?.surveyId).toBe('s1');
	});

	it('the preview frame mounts without a config tag and refuses an API base', () => {
		const frame = defineFramePage('preview-frame', Wordmark);
		const el = hostPage(null);
		mounted = autoMount(frame, { name: 'preview-frame', frame: true });
		expect(el.textContent).toContain('Open Survey');
		mounted?.unmount();
		mounted = null;
		expect(() => frame(el, { version: 1, apiBase: '/api' })).toThrow(OspConfigError);
	});
});
