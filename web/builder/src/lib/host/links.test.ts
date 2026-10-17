import { afterEach, describe, expect, it } from 'vitest';
import type { OspPageConfig } from './config';
import {
	DEFAULT_LINKS,
	leaveTo,
	LEAVE_QUESTION,
	link,
	linkFrom,
	optionalLink,
	registerSaveGuard,
	resetLeaveState,
	setPageConfig,
	type SaveGuard
} from './links';

const HOST_LINKS = {
	list: '/osp/',
	editor: '/osp/s/{id}/',
	flow: '/osp/s/{id}/flow/',
	settings: '/osp/s/{id}/settings/?tab=1',
	appearance: '/osp/s/{id}/look/',
	themes: '/osp/themes/',
	previewFrame: '/osp/frame/'
};

afterEach(() => {
	setPageConfig(null);
	resetLeaveState();
});

describe('links', () => {
	it('follow the host templates', () => {
		setPageConfig({ version: 1, apiBase: '/osp/api', links: HOST_LINKS } satisfies OspPageConfig);
		expect(link('list')).toBe('/osp/');
		expect(link('editor', { id: 's1' })).toBe('/osp/s/s1/');
		expect(link('flow', { id: 'a/b' })).toBe('/osp/s/a%2Fb/flow/');
		expect(link('appearance', { id: 's1' })).toBe('/osp/s/s1/look/');
		expect(link('settings', { id: 's1' }, { hash: 'retention' })).toBe('/osp/s/s1/settings/?tab=1#retention');
		expect(link('editor', { id: 's1' }, { hash: 'select=q 1' })).toBe('/osp/s/s1/#select=q%201');
		expect(link('themes', {}, { query: { x: '1 2' } })).toBe('/osp/themes/?x=1+2');
	});

	it('give no URL for an optional page the host does not serve (results)', () => {
		setPageConfig({ version: 1, apiBase: '/osp/api', links: HOST_LINKS } satisfies OspPageConfig);
		expect(optionalLink('results', { id: 's1' })).toBeNull();
		setPageConfig({ version: 1, apiBase: '/osp/api', links: { ...HOST_LINKS, results: '/osp/s/{id}/results/' } });
		expect(optionalLink('results', { id: 's1' })).toBe('/osp/s/s1/results/');
		setPageConfig(null);
		expect(optionalLink('results', { id: 's1' })).toBe('/surveys/s1/results');
	});

	it("default to today's URLs without a config", () => {
		expect(link('editor', { id: 's1' })).toBe('/surveys/s1');
		expect(linkFrom(DEFAULT_LINKS, 'settings', { id: 's1' }, { hash: 'retention' })).toBe('/surveys/s1/settings#retention');
		expect(linkFrom({ ...DEFAULT_LINKS, list: '/?mock#top' }, 'list', {}, { query: { a: 'b' } })).toBe('/?mock&a=b#top');
	});
});

function guard(state: { unsaved: boolean; settle: Promise<void> }): SaveGuard & { flushed: number } {
	const g = {
		flushed: 0,
		unsaved: () => state.unsaved,
		flush: () => void g.flushed++,
		settled: () => state.settle
	};
	return g;
}

describe('leaveTo (D8)', () => {
	it('leaves at once when nothing is unsaved, after flushing buffers', async () => {
		const g = guard({ unsaved: false, settle: Promise.resolve() });
		registerSaveGuard(g);
		const went: string[] = [];
		expect(await leaveTo('/next', { assign: (u) => went.push(u), confirm: () => false })).toBe(true);
		expect(went).toEqual(['/next']);
		expect(g.flushed).toBe(1);
	});

	it('waits for the save queue, then leaves without asking', async () => {
		const state = { unsaved: true, settle: Promise.resolve() };
		let release!: () => void;
		state.settle = new Promise((r) => (release = () => ((state.unsaved = false), r())));
		registerSaveGuard(guard(state));
		const went: string[] = [];
		let asked = 0;
		const p = leaveTo('/next', {
			assign: (u) => went.push(u),
			confirm: () => ++asked > 0,
			sleep: () => new Promise(() => {})
		});
		await Promise.resolve();
		expect(went).toEqual([]);
		release();
		expect(await p).toBe(true);
		expect(went).toEqual(['/next']);
		expect(asked).toBe(0);
	});

	it('asks after the timeout, and stays if the user says no', async () => {
		registerSaveGuard(guard({ unsaved: true, settle: new Promise(() => {}) }));
		const went: string[] = [];
		const questions: string[] = [];
		const waited: number[] = [];
		const out = await leaveTo('/next', {
			assign: (u) => went.push(u),
			confirm: (q) => (questions.push(q), false),
			timeoutMs: 10_000,
			sleep: async (ms) => void waited.push(ms)
		});
		expect(out).toBe(false);
		expect(went).toEqual([]);
		expect(questions).toEqual([LEAVE_QUESTION]);
		expect(waited).toEqual([10_000]);
	});

	it('leaves after the timeout if the user agrees', async () => {
		registerSaveGuard(guard({ unsaved: true, settle: Promise.resolve() }));
		const went: string[] = [];
		expect(await leaveTo('/next', { assign: (u) => went.push(u), confirm: () => true, sleep: async () => {} })).toBe(true);
		expect(went).toEqual(['/next']);
	});
});
