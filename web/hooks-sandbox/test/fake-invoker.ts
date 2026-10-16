/** An in-process Invoker with the worker's action shapes, for node unit tests. */

import type { InvokeOutcome, InvokeRequest, Invoker } from '../src/host.ts';

export interface Act {
	setVariable(id: string, value: unknown): void;
	addParadata(key: string, value: unknown): void;
	rejectPage(o: { itemId?: string; message: unknown }): void;
	setEndRedirect(templateId: string, params: unknown): void;
	postToParent(type: string, payload: unknown): void;
}
export type Handler = (ctx: Record<string, unknown>, data: Record<string, unknown>, act: Act) => void | Promise<void>;

export class FakeInvoker implements Invoker {
	calls: InvokeRequest[] = [];
	/** Outcome override per event (e.g. a timeout). */
	fail: Record<string, InvokeOutcome> = {};
	gate: Record<string, Promise<void>> = {};

	constructor(public handlers: Record<string, Handler>) {}

	async invoke(req: InvokeRequest): Promise<InvokeOutcome> {
		this.calls.push(req);
		if (this.gate[req.event]) await this.gate[req.event];
		const f = this.fail[req.event];
		if (f) return f;
		const h = this.handlers[req.event];
		if (!h) return { status: 'ok', actions: [] }; // the real worker says 'no-handler'
		const actions: unknown[] = [];
		const act: Act = {
			setVariable: (id, value) => actions.push({ type: 'setVariable', id, value }),
			addParadata: (key, value) => actions.push({ type: 'addParadata', key, value }),
			rejectPage: (o) => actions.push({ type: 'rejectPage', itemId: o.itemId ?? null, message: o.message }),
			setEndRedirect: (templateId, params) => actions.push({ type: 'setEndRedirect', templateId, params }),
			postToParent: (messageType, payload) => actions.push({ type: 'postToParent', messageType, payload })
		};
		try {
			await h(req.ctx as Record<string, unknown>, req.data as Record<string, unknown>, act);
			return { status: 'ok', actions: JSON.parse(JSON.stringify(actions)) };
		} catch (e) {
			return { status: 'error', error: String(e) };
		}
	}

	dispose(): void {}
}
