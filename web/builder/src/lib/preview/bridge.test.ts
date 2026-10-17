import { describe, expect, it } from 'vitest';
import {
	frameUrl,
	hostMessage,
	listenForFrames,
	parseFrameMessage,
	parseHostMessage,
	PROTOCOL,
	type FrameConfig,
	type PreviewBridge
} from './bridge';

const CFG: FrameConfig = {
	key: 1,
	planJson: '{}',
	sessionSeed: 3,
	assigned: { arm: 'a' },
	quotas: { q1: 'open' },
	snapshotJson: null
};

describe('preview messages (D10)', () => {
	it('accept only our schema', () => {
		expect(parseFrameMessage({ protocol: PROTOCOL, v: 1, type: 'attach', frameId: 'phone' })).toEqual({
			protocol: PROTOCOL,
			v: 1,
			type: 'attach',
			frameId: 'phone'
		});
		expect(parseFrameMessage({ protocol: PROTOCOL, v: 2, type: 'attach', frameId: 'phone' })).toBeNull();
		expect(parseFrameMessage({ protocol: 'other', v: 1, type: 'attach', frameId: 'phone' })).toBeNull();
		expect(parseFrameMessage({ protocol: PROTOCOL, v: 1, type: 'attach', frameId: '../x' })).toBeNull();
		expect(parseFrameMessage({ protocol: PROTOCOL, v: 1, type: 'changed', frameId: 'p', key: 1.5, snapshotJson: '{}', phase: 'page' })).toBeNull();
		expect(parseFrameMessage({ protocol: PROTOCOL, v: 1, type: 'eval', frameId: 'p' })).toBeNull();
		expect(parseFrameMessage('attach')).toBeNull();

		expect(parseHostMessage(hostMessage(CFG))?.cfg).toEqual(CFG);
		expect(parseHostMessage({ ...hostMessage(CFG), cfg: { ...CFG, quotas: { q1: 'maybe' } } })).toBeNull();
		expect(parseHostMessage({ ...hostMessage(CFG), cfg: { ...CFG, assigned: { a: {} } } })).toBeNull();
		expect(parseHostMessage({ ...hostMessage(CFG), cfg: { ...CFG, apiBase: '/api' } })?.cfg).not.toHaveProperty('apiBase');
	});

	it('the frame URL carries the frame id and builder origin, never the API base', () => {
		expect(frameUrl('/preview-frame', 'phone', 'https://lab.example.org')).toBe(
			'/preview-frame?frame=phone&origin=https%3A%2F%2Flab.example.org'
		);
		expect(frameUrl('/osp/frame/?v=2#x', 'tablet', 'https://a.b')).toBe('/osp/frame/?v=2&frame=tablet&origin=https%3A%2F%2Fa.b#x');
	});
});

describe('listenForFrames', () => {
	function setup() {
		const listeners: ((e: MessageEvent) => void)[] = [];
		const w = {
			addEventListener: (_: string, f: (e: MessageEvent) => void) => listeners.push(f),
			removeEventListener: () => {}
		} as unknown as Window;
		const posted: unknown[] = [];
		const phone = { postMessage: (m: unknown, origin: string) => posted.push([m, origin]) } as unknown as Window;
		const events: string[] = [];
		const bridge: PreviewBridge = {
			attach: (id) => (events.push(`attach ${id}`), CFG),
			detach: (id) => void events.push(`detach ${id}`),
			changed: (id, key) => void events.push(`changed ${id} ${key}`)
		};
		listenForFrames(w, 'https://lab.example.org', (id) => (id === 'phone' ? phone : null), bridge);
		const send = (data: unknown, origin = 'https://lab.example.org', source: unknown = phone) =>
			listeners.forEach((f) => f({ data, origin, source } as MessageEvent));
		return { send, events, posted, phone };
	}

	it('answers an attach from the registered frame with its config', () => {
		const t = setup();
		t.send({ protocol: PROTOCOL, v: 1, type: 'attach', frameId: 'phone' });
		t.send({ protocol: PROTOCOL, v: 1, type: 'changed', frameId: 'phone', key: 1, snapshotJson: '{}', phase: 'page' });
		expect(t.events).toEqual(['attach phone', 'changed phone 1']);
		expect(t.posted).toEqual([[hostMessage(CFG), 'https://lab.example.org']]);
	});

	it('ignores other origins, other windows and malformed messages', () => {
		const t = setup();
		t.send({ protocol: PROTOCOL, v: 1, type: 'attach', frameId: 'phone' }, 'https://evil.example');
		t.send({ protocol: PROTOCOL, v: 1, type: 'attach', frameId: 'phone' }, 'https://lab.example.org', {});
		t.send({ protocol: PROTOCOL, v: 1, type: 'attach', frameId: 'tablet' });
		t.send({ protocol: PROTOCOL, v: 1, type: 'attach' });
		expect(t.events).toEqual([]);
		expect(t.posted).toEqual([]);
	});
});
