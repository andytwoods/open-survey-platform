import { afterEach, describe, expect, it, vi } from 'vitest';
import { answer, snapshot, tryResolve, withChecksum, type Plan, type State } from '@osp/engine';
import type { FrameConfig } from './bridge';
import { participantEvents, PreviewHost } from './host.svelte';

const t = (s: string) => ({ en: [s] });

/** p1: a (integer). */
function plan(): Plan {
	return withChecksum({
		planVersion: 'osp-runtime-plan/1',
		engineVersion: '1',
		survey: { id: 's', version: null, specVersion: 'osp-survey/0.1', seedVersion: 'draft' },
		languages: ['en'],
		defaultLanguage: 'en',
		title: t('T'),
		settings: { backNavigation: true, saveMode: 'every-page', localCopy: 'browser', resumeExpiryDays: 30 },
		items: { a: { id: 'a', page: 'p1', type: 'integer', name: 'a', required: false, label: t('a') } },
		questions: ['a'],
		pages: { p1: { id: 'p1', block: 'b1', items: ['a'], itemOrder: 'fixed' } },
		blocks: { b1: { id: 'b1', pages: ['p1'] } },
		variables: {},
		quotas: {},
		flow: [{ type: 'block', id: 'n1', block: 'b1', pages: ['p1'] }]
	} as unknown as Plan);
}

/** What a frame's hooks do on load: record one `onResume` result. */
const hooked = (s: State) =>
	tryResolve(s, { kind: 'hook', invocationId: `onResume@${s.data.revision}`, event: 'onResume', revision: s.data.revision }, { status: 'ok', actions: [], seed: 1, now: 0 })
		.state;

function setup() {
	const host = new PreviewHost(1);
	host.usePlan(plan());
	const loads: Record<string, FrameConfig[]> = { phone: [], desktop: [] };
	for (const id of ['phone', 'desktop']) {
		const cfg = host.attach(id, { load: (c) => loads[id]!.push(c) });
		loads[id]!.push(cfg!);
	}
	const key = (id: string) => loads[id]!.at(-1)!.key;
	const report = (id: string, s: State) => host.changed(id, key(id), JSON.stringify(snapshot(s)), 'page');
	return { host, loads, key, report };
}

afterEach(() => {
	vi.useRealTimers();
});

describe('preview host with researcher hooks (R10)', () => {
	it('counts participant events, not recorded hook results', () => {
		const { host } = setup();
		const s0 = host.state!;
		expect(participantEvents(hooked(s0).data.events)).toBe(participantEvents(s0.data.events));
		expect(participantEvents(answer(s0, 'a', 3).data.events)).toBe(participantEvents(s0.data.events) + 1);
	});

	it('mirrors a participant change to the other frames, but not a change only hooks made', () => {
		vi.useFakeTimers();
		const { host, loads, report } = setup();
		const s0 = host.state!;

		// The desktop frame loaded and its onResume ran: the debugger follows, nothing mirrors.
		report('desktop', hooked(s0));
		expect(host.state!.data.events.length).toBe(s0.data.events.length + 1);
		vi.advanceTimersByTime(1000);
		expect(loads.phone).toHaveLength(1);
		expect(host.source).toBe('debugger');

		// The participant answers on the phone: the desktop frame follows.
		report('phone', answer(s0, 'a', 3));
		vi.advanceTimersByTime(1000);
		expect(loads.desktop).toHaveLength(2);
		expect(loads.phone).toHaveLength(1);

		// The desktop reloads on it and its hooks run again: still no ping-pong.
		const followed = hooked(answer(s0, 'a', 3));
		report('desktop', followed);
		vi.advanceTimersByTime(1000);
		expect(loads.phone).toHaveLength(1);
		expect(host.source).toBe('frame');
	});

	it('starts frames as a new session until the run moves, so onStart hooks run', () => {
		vi.useFakeTimers();
		const { host, loads, report } = setup();
		expect(loads.phone[0]!.snapshotJson).toBeNull();
		report('phone', answer(host.state!, 'a', 3));
		vi.advanceTimersByTime(1000);
		expect(JSON.parse(loads.desktop.at(-1)!.snapshotJson!).data.values).toEqual({ a: 3 });
		host.restart();
		expect(loads.phone.at(-1)!.snapshotJson).toBeNull();
	});

	it('keeps frame diagnostics for the debugger, only from the frame as loaded now', () => {
		const { host, key } = setup();
		host.log('phone', key('phone'), 'hook manifest refused: bad');
		host.log('phone', key('phone') + 100, 'from an older load');
		host.log('tablet', 1, 'from a frame never attached');
		expect(host.logs).toEqual([{ frameId: 'phone', message: 'hook manifest refused: bad' }]);
		for (let i = 0; i < 60; i++) host.log('desktop', key('desktop'), `m${i}`);
		expect(host.logs).toHaveLength(50);
		expect(host.logs.at(-1)!.message).toBe('m59');
		host.usePlan(plan());
		expect(host.logs).toEqual([]);
	});
});
