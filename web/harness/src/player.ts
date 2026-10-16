/**
 * The script player (task R4): one fixture script (fixtures/FORMAT.md §2) played through the
 * real participant app (web/runtime) in a real browser, against the real osp-api
 * (web/harness/server.py), and observed after every action.
 *
 * Input goes through the accessibility tree only: every control is found by role and
 * accessible name (`getByRole(…, { name })`), using the label the engine says the question
 * has. A question the player cannot find that way is a failure, so playing a fixture is
 * also an accessibility check. Keyboard where a participant would use it: typing into text
 * fields, Space on radios and checkboxes, Enter on Next and Back.
 *
 * Observation: the screen (which page, which questions in which order, their labels,
 * choice labels and order, error messages, the values the widgets show, Back present) is
 * read from the DOM; what the screen cannot show (off-page states, orders, conditions, end
 * code, pending effect, built-ins) from the app's own engine snapshot (src/trace.ts). At the
 * end the response is read from what the server stored.
 */
import type { Browser, BrowserContext, BrowserContextOptions, Page, Route } from '@playwright/test';
import { escapeHtml, result, toHtml, toPlain, type Plan, type ResponseRecord, type ViewItem } from '@osp/engine';
import type { Action, QuotaFate, Script } from './fixtures.ts';
import { engineStep, responseOf, restoreSnapshot, blockOfPage } from './trace.ts';

const START_HEADER = 'x-osp-harness-start';
const SETTLE_MS = 20_000;
const THINK_MS = Number(process.env.OSP_HARNESS_THINK_MS ?? 0);

/** One question as the screen shows it. */
interface DomItem {
	id: string;
	label: string;
	error: string | null;
	choices: Array<{ label: string; checked: boolean }>;
	inputs: Array<{ label: string; value: string }>;
}

interface DomState {
	phase: string | null;
	page: string | null;
	thanks: boolean;
	back: boolean;
	items: DomItem[];
	snapshot: unknown;
	sid: string | null;
}

export interface Problem {
	path: string;
	expected: unknown;
	actual: unknown;
}

export interface Played {
	steps: Array<Record<string, unknown>>;
	response: Record<string, unknown> | null;
	responseSource: 'server-record' | 'server-snapshot' | 'app-state' | 'none';
	network: { quotaCalls: Record<string, number>; snapshotWrites: number; submits: number };
	/** Screen vs app-state disagreements and controls not reachable by role + name. */
	problems: Problem[];
	sessionId: string | null;
	/** The script could not be played (wrong page, missing control …): index of the action. */
	abortedAt: number | null;
	abortReason: string | null;
}

// -- quota gate (FORMAT.md `server.quotaCalls`, `retry`) -------------------------------------

/**
 * The fixture rule "a pending effect is re-sent only by `retry`" against an app that retries
 * on its own: a quota request is held until the script allows one (`next` allows the first,
 * each `retry` one more); the allowed request then meets its scripted fate. `timeout` never
 * reaches the server, `lostReply` reaches it but the reply is dropped, `ok` arrives.
 */
class QuotaGate {
	calls: Record<string, number> = {};
	permits = 0;
	lastFate: QuotaFate | null = null;
	private held: Array<{ route: Route; node: string }> = [];
	private busy: Promise<void> = Promise.resolve();

	constructor(private fates: Record<string, QuotaFate[]>) {}

	gated(node: string) {
		return node in this.fates;
	}

	async onRoute(route: Route, node: string) {
		if (!this.gated(node)) {
			this.calls[node] = (this.calls[node] ?? 0) + 1;
			return route.continue();
		}
		this.held.push({ route, node });
		this.pump();
	}

	allow(n = 1) {
		this.permits = n;
		this.pump();
	}

	close() {
		this.permits = 0;
	}

	private pump() {
		this.busy = this.busy.then(async () => {
			while (this.permits > 0 && this.held.length) {
				const { route, node } = this.held.shift()!;
				const k = (this.calls[node] ?? 0) + 1;
				const fate = this.fates[node]?.[k - 1] ?? 'ok';
				try {
					if (fate === 'timeout') await route.abort('timedout');
					else {
						const res = await route.fetch();
						if (fate === 'lostReply') await route.abort('failed');
						else await route.fulfill({ response: res });
					}
				} catch {
					continue; // the page that sent it is gone (refresh): not a call
				}
				this.calls[node] = k;
				this.permits--;
				this.lastFate = fate;
			}
		});
	}

	async consumed(timeoutMs: number): Promise<boolean> {
		const until = Date.now() + timeoutMs;
		while (Date.now() < until) {
			await this.busy;
			if (this.permits === 0) return true;
			await new Promise((r) => setTimeout(r, 50));
		}
		return false;
	}
}

// -- helpers ------------------------------------------------------------------------------

function esc(s: string) {
	return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * A label as a name pattern. Accessible-name computation collapses white space and some
 * browsers drop zero-width characters (U+200B …), so both are matched loosely.
 */
function namePattern(label: string): string {
	const zw = /[\u200B-\u200D\u2060\uFEFF]/;
	return label
		.trim()
		.split(/\s+/)
		.map((tok) => tok.split(zw).map(esc).join('[\\u200B-\\u200D\\u2060\\uFEFF]?'))
		.join('\\s+');
}

/** The accessible name of a question: its label, then the frame's "(Required)" if any. */
function nameOf(label: string): RegExp {
	return new RegExp(`^\\s*${namePattern(label)}\\s*(\\*\\s*)?(\\([^)]*\\))?\\s*$`);
}

function exactName(label: string): RegExp {
	return new RegExp(`^\\s*${namePattern(label)}\\s*$`);
}

/** In-page probe of what the screen shows; DOM ids only map screen items to question ids. */
function probe(): DomState {
	const w = window as unknown as {
		__osp?: { phase: string; rec: { snapshot: unknown; sessionId: string } };
	};
	const s = w.__osp;
	const text = (el: Element | null) => {
		if (!el) return '';
		const c = el.cloneNode(true) as Element;
		c.querySelectorAll('.req, .osp-visually-hidden, [aria-hidden="true"]').forEach((x) => x.remove());
		return c.textContent ?? '';
	};
	const items: DomItem[] = [...document.querySelectorAll('.items [data-question]')].map((q) => {
		const dom = q.getAttribute('data-question') ?? '';
		const err = document.getElementById(`${dom}-error`);
		return {
			id: dom.replace(/^q-/, ''),
			label: text(document.getElementById(`${dom}-label`)).trim(),
			error: err ? text(err).trim() : null,
			choices: [...q.querySelectorAll('[role="radio"], [role="checkbox"]')].map((c) => ({
				label: (c.querySelector('.osp-choice-label')?.textContent ?? '').trim(),
				checked: c.getAttribute('aria-checked') === 'true'
			})),
			inputs: [...q.querySelectorAll('input, textarea')].map((i) => ({
				label: ((i as HTMLInputElement).labels?.[0]?.textContent ?? '').trim(),
				value: (i as HTMLInputElement).value
			}))
		};
	});
	return {
		phase: s?.phase ?? null,
		page: document.querySelector('.items[data-page]')?.getAttribute('data-page') ?? null,
		thanks: !!document.querySelector('[data-testid="thanks"]'),
		back: false, // filled in by role (observe)
		items,
		snapshot: s?.rec?.snapshot ?? null,
		sid: s?.rec?.sessionId ?? null
	};
}

/** The app is idle and the screen shows the engine's current page. */
function settled(): boolean {
	const s = (window as unknown as { __osp?: { phase: string; view(): { page: string | null; items: unknown[] } } }).__osp;
	if (!s) return false;
	if (s.phase === 'submitting') return false;
	if (s.phase === 'done') return !!document.querySelector('[data-testid="thanks"]');
	if (s.phase === 'fatal') return true;
	const v = s.view();
	const el = document.querySelector('.items[data-page]');
	if (!el || el.getAttribute('data-page') !== v.page) return false;
	return document.querySelectorAll('.items [data-question]').length === v.items.length;
}

/** What the engine (inside the app) says a visible item is: type, label, choices. */
function viewItems(): Array<{ id: string; type: string; label: string; choices: Array<{ value: string; label: string }> }> {
	const s = (window as unknown as { __osp?: { view(): { items: ViewItem[] } } }).__osp;
	const plain = (t: Array<{ text: string }> | null | undefined) => (t ?? []).map((p) => p.text).join('');
	return (s?.view().items ?? []).map((i) => ({
		id: i.id,
		type: i.type,
		label: plain(i.label),
		choices: (i.choices ?? []).map((c) => ({ value: String(c.value), label: plain(c.label) }))
	}));
}

const ROLE: Record<string, 'textbox' | 'radiogroup' | 'group'> = {
	integer: 'textbox',
	decimal: 'textbox',
	text: 'textbox',
	single: 'radiogroup',
	multi: 'group',
	date: 'group'
};

// -- the player ---------------------------------------------------------------------------

export interface PlayOptions {
	browser: Browser;
	baseURL: string;
	slug: string;
	/** The Playwright project's device options (viewport, user agent, touch …). */
	device: BrowserContextOptions;
	script: Script;
	/** Called after every observed step (debugging). */
	log?: (msg: string) => void;
}

export class Player {
	private contexts = new Map<string, { ctx: BrowserContext; page: Page }>();
	private device = 'A';
	private gate: QuotaGate;
	private plan: Plan | null = null;
	private submitted = false;
	readonly network = { quotaCalls: {} as Record<string, number>, snapshotWrites: 0, submits: 0 };
	readonly problems: Problem[] = [];
	private sid: string | null = null;
	private a11yChecked = new Set<string>();

	constructor(private o: PlayOptions) {
		this.gate = new QuotaGate(o.script.server?.quotaCalls ?? {});
	}

	get page(): Page {
		return this.contexts.get(this.device)!.page;
	}

	async close() {
		for (const { ctx } of this.contexts.values()) await ctx.close().catch(() => undefined);
	}

	private async newContext(): Promise<BrowserContext> {
		const { script } = this.o;
		const ctx = await this.o.browser.newContext({
			...this.o.device,
			baseURL: this.o.baseURL,
			locale: script.language
		});
		if (script.storage === 'blocked') {
			// Private mode: no IndexedDB (as R3's e2e does).
			await ctx.addInitScript(() => {
				Object.defineProperty(window, 'indexedDB', { value: undefined, configurable: true });
			});
		}
		// The script's seed and conditions at session start (server.py).
		await ctx.route('**/api/s/*/sessions', async (route) => {
			if (route.request().method() !== 'POST') return route.continue();
			const headers = {
				...route.request().headers(),
				// ASCII only: browsers send header bytes as Latin-1 or UTF-8 (a "£" condition).
				[START_HEADER]: JSON.stringify({ seed: script.sessionSeed, conditions: script.server?.conditions ?? {} }).replace(
					/[\u007f-\uffff]/g,
					(ch) => `\\u${ch.charCodeAt(0).toString(16).padStart(4, '0')}`
				)
			};
			return route.continue({ headers });
		});
		await ctx.route('**/api/sessions/*/quota/*', (route) => {
			const node = decodeURIComponent(new URL(route.request().url()).pathname.split('/quota/')[1] ?? '');
			return this.gate.onRoute(route, node);
		});
		ctx.on('request', (req) => {
			const u = new URL(req.url());
			if (req.method() === 'PUT' && /\/api\/sessions\/[^/]+\/snapshot$/.test(u.pathname) && !this.submitted) {
				this.network.snapshotWrites++;
			}
			if (req.method() === 'POST' && /\/api\/sessions\/[^/]+\/submit$/.test(u.pathname)) {
				this.submitted = true;
				this.network.submits++;
			}
		});
		return ctx;
	}

	private async settle(page = this.page) {
		try {
			await page.waitForFunction(settled, null, { timeout: SETTLE_MS, polling: 50 });
		} catch {
			this.problems.push({ path: 'settle', expected: 'the app shows the engine page', actual: 'timed out' });
		}
	}

	async begin() {
		const ctx = await this.newContext();
		const page = await ctx.newPage();
		this.contexts.set(this.device, { ctx, page });
		await page.goto(`/s/${encodeURIComponent(this.o.slug)}`);
		await page.waitForFunction(() => !!(window as unknown as { __osp?: unknown }).__osp, null, { timeout: SETTLE_MS });
		await this.settle();
		this.plan = (await page.evaluate(() => (window as unknown as { __osp: { plan: unknown } }).__osp.plan)) as Plan;
	}

	// -- observe --------------------------------------------------------------------------

	/** The trace step after action `index - 1` (FORMAT.md §3), plus screen/state problems. */
	async observe(index: number): Promise<Record<string, unknown>> {
		const page = this.page;
		const dom = await page.evaluate(probe);
		dom.back = (await page.getByRole('button', { name: 'Back', exact: true }).count()) > 0;
		const plan = this.plan!;
		const at = `steps[${index}]`;
		// One participant, one session: a refresh, resume or device switch must continue it.
		if (this.sid && dom.sid && dom.sid !== this.sid) {
			this.problems.push({ path: `${at}.session`, expected: this.sid, actual: `a new session ${dom.sid}` });
		}
		this.sid ??= dom.sid;
		const state = restoreSnapshot(plan, dom.snapshot);
		const eng = engineStep(state);
		const v = eng.view;
		const ended = dom.phase === 'done';
		const problem = (path: string, expected: unknown, actual: unknown) =>
			this.problems.push({ path: `${at}.${path}`, expected, actual });

		// Screen ↔ app state: the screen must show exactly the engine's page.
		const byId = new Map(v.items.map((i) => [i.id, i]));
		for (const it of dom.items) {
			const vi = byId.get(it.id);
			if (!vi) continue;
			if (it.label !== toPlain(vi.label).trim()) problem(`screen.label.${it.id}`, toPlain(vi.label), it.label);
			this.checkValue(it, vi, problem);
		}

		const labels: Record<string, string> = {};
		const choiceLabels: Record<string, Array<[unknown, string]>> = {};
		const errors: Record<string, unknown> = {};
		for (const it of dom.items) {
			const vi = byId.get(it.id);
			labels[it.id] = vi && it.label === toPlain(vi.label).trim() ? toHtml(vi.label) : escapeHtml(it.label);
			if (vi?.choices) {
				choiceLabels[it.id] = it.choices.map((c, k) => {
					const vc = vi.choices![k];
					const same = vc && c.label === toPlain(vc.label).trim();
					return [vc?.value ?? null, same ? toHtml(vc.label) : escapeHtml(c.label)];
				});
			}
			if (it.error) {
				// The kind comes from the engine; the message must be the one on screen.
				const e = eng.errors[it.id];
				if (!e) errors[it.id] = { kind: 'unknown', message: it.error };
				else if (e.kind === 'constraint') {
					const plainMsg = v.errors[it.id]?.message ? toPlain(v.errors[it.id]!.message) : null;
					errors[it.id] = plainMsg === null || plainMsg.trim() === it.error ? e : { kind: 'constraint', message: escapeHtml(it.error) };
				} else errors[it.id] = e;
			}
		}

		// Accessibility: every visible question is reachable by role + accessible name.
		const key = `${dom.page}|${dom.items.map((i) => i.id).join(',')}`;
		if (!ended && !this.a11yChecked.has(key)) {
			this.a11yChecked.add(key);
			for (const it of dom.items) {
				const vi = byId.get(it.id);
				const role = vi ? ROLE[vi.type] : undefined;
				if (!vi || !role) continue;
				const n = await page.getByRole(role, { name: nameOf(toPlain(vi.label)) }).count();
				if (n < 1) {
					// What the accessibility tree does have for that role (for the report).
					const tree = await page.locator('main').ariaSnapshot();
					const named = tree.split('\n').filter((l) => l.includes(role)).map((l) => l.trim());
					problem(`a11y.${it.id}`, `a ${role} named ${JSON.stringify(toPlain(vi.label))}`, named);
				}
			}
		}

		const step: Record<string, unknown> = {
			index,
			page: ended ? null : blockOfPage(plan, dom.page),
			visible: ended ? [] : dom.items.map((i) => i.id),
			errors,
			nav: ended ? null : { back: dom.back },
			questions: eng.questions,
			orders: eng.orders,
			conditions: eng.conditions,
			end: eng.end,
			labels: ended ? {} : labels,
			choiceLabels: ended ? {} : choiceLabels,
			effect: eng.effect,
			device: this.device,
			builtins: eng.builtins
		};
		return step;
	}

	/** The value a widget shows must be the value the app holds. */
	private checkValue(it: DomItem, vi: ViewItem, problem: (p: string, e: unknown, a: unknown) => void) {
		const val = vi.value;
		const path = `screen.value.${it.id}`;
		switch (vi.type) {
			case 'integer':
			case 'decimal': {
				const shown = it.inputs[0]?.value.trim() ?? '';
				const held = val === null || val === undefined ? '' : String(val);
				// An invalid entry is kept on screen as typed and held as null by the engine.
				if (shown !== held && !(held === '' && shown !== '' && vi.error)) {
					if (!(held !== '' && shown !== '' && Number(shown) === Number(held))) problem(path, held, shown);
				}
				break;
			}
			case 'text': {
				const shown = (it.inputs[0]?.value ?? '').trim();
				const held = typeof val === 'string' ? val.trim() : '';
				if (shown !== held) problem(path, held, shown);
				break;
			}
			case 'single': {
				const checked = it.choices.findIndex((c) => c.checked);
				const want = (vi.choices ?? []).findIndex((c) => String(c.value) === String(val));
				if (checked !== want) problem(path, val ?? null, checked < 0 ? null : String(vi.choices?.[checked]?.value));
				break;
			}
			case 'multi': {
				const want = new Set(Array.isArray(val) ? val.map(String) : []);
				const shown = (vi.choices ?? []).filter((_, k) => it.choices[k]?.checked).map((c) => String(c.value));
				if (shown.length !== want.size || shown.some((x) => !want.has(x))) problem(path, [...want], shown);
				break;
			}
			case 'date': {
				const f: Record<string, string> = {};
				for (const i of it.inputs) f[i.label.toLowerCase()] = i.value.trim();
				const shown =
					f.year && f.month && f.day ? `${f.year.padStart(4, '0')}-${f.month.padStart(2, '0')}-${f.day.padStart(2, '0')}` : '';
				const held = typeof val === 'string' ? val : '';
				if (shown !== held && !(held === '' && vi.error)) problem(path, held, shown);
				break;
			}
		}
	}

	// -- act ------------------------------------------------------------------------------

	async act(i: number, a: Action) {
		const page = this.page;
		if (a.expectPage !== undefined) {
			const shown = blockOfPage(this.plan!, await page.evaluate(() => document.querySelector('.items[data-page]')?.getAttribute('data-page') ?? null));
			if (shown !== a.expectPage) throw new ScriptError(i, `expected page ${a.expectPage}, the app shows ${shown}`);
		}
		// `setIfShown` looks at the page as it was before this action's answers (the engine
		// runner's rule); `set` answers in order, so a question revealed live by an earlier
		// answer on the same page can be set (showIf is live within a page).
		const before = new Set((await page.evaluate(viewItems)).map((it) => it.id));
		for (const [id, value] of Object.entries(a.set ?? {})) {
			const items = await page.evaluate(viewItems);
			if (!items.some((it) => it.id === id)) throw new ScriptError(i, `set ${id}: not on the page`);
			await this.answer(i, items, id, value);
		}
		for (const [id, value] of Object.entries(a.setIfShown ?? {})) {
			if (before.has(id)) await this.answer(i, await page.evaluate(viewItems), id, value);
		}
		// Optional participant "think time" between answering and acting (default none: the
		// adversarial case, e.g. a refresh straight after typing).
		if (THINK_MS > 0 && (a.set || a.setIfShown)) await page.waitForTimeout(THINK_MS);
		switch (a.do) {
			case 'next':
				await this.next(i);
				break;
			case 'back': {
				const btn = page.getByRole('button', { name: 'Back', exact: true });
				if ((await btn.count()) === 0) throw new ScriptError(i, 'back: no Back button');
				await btn.focus();
				await btn.press('Enter');
				await this.settle();
				break;
			}
			case 'refresh':
				await page.reload();
				await this.waitBoot(page);
				break;
			case 'resume': {
				// Leave (close the tab, no unload handlers) and come back to the link later.
				const entry = this.contexts.get(this.device)!;
				await entry.page.close();
				entry.page = await entry.ctx.newPage();
				await entry.page.goto(`/s/${encodeURIComponent(this.o.slug)}`);
				await this.waitBoot(entry.page);
				break;
			}
			case 'switchDevice':
				await this.switchDevice(i, a);
				break;
			case 'retry':
				this.gate.allow(1);
				// The app's own retry path (Session.wake), instead of waiting out its backoff.
				await page.evaluate(() => window.dispatchEvent(new Event('online')));
				await this.awaitQuota();
				break;
			case 'offline':
				await this.contexts.get(this.device)!.ctx.setOffline(true);
				break;
			case 'online':
				await this.contexts.get(this.device)!.ctx.setOffline(false);
				await this.settle();
				break;
			default:
				throw new ScriptError(i, `unknown action ${(a as Action).do}`);
		}
	}

	private async waitBoot(page: Page) {
		await page.waitForFunction(() => !!(window as unknown as { __osp?: unknown }).__osp, null, { timeout: SETTLE_MS });
		await this.settle(page);
	}

	private async next(i: number) {
		const page = this.page;
		const btn = page.getByRole('button', { name: 'Next', exact: true });
		if ((await btn.count()) === 0) throw new ScriptError(i, 'next: no Next button');
		this.gate.allow(1); // `next` sends the first quota call itself
		await btn.focus();
		await btn.press('Enter');
		const pending = await page.evaluate(() => (window as unknown as { __osp: { phase: string } }).__osp.phase === 'pending');
		if (pending) await this.awaitQuota();
		this.gate.close();
		await this.settle();
	}

	/** Wait for the allowed quota call to meet its fate and for the app to take the reply. */
	private async awaitQuota() {
		const page = this.page;
		await this.gate.consumed(SETTLE_MS);
		this.gate.close();
		if (this.gate.lastFate === 'ok') {
			await page
				.waitForFunction(() => (window as unknown as { __osp: { phase: string } }).__osp.phase !== 'pending', null, {
					timeout: SETTLE_MS
				})
				.catch(() => this.problems.push({ path: 'quota', expected: 'the app takes the reply', actual: 'still pending' }));
		} else {
			// timeout / lost reply: the app shows the error and schedules its own retry (held).
			await page.waitForTimeout(100);
		}
		await this.settle();
	}

	private async switchDevice(i: number, a: Action) {
		const to = a.device ?? (this.device === 'A' ? 'B' : 'A');
		const existing = this.contexts.get(to);
		if (a.restoreFrom === 'local') {
			// A stale tab: that device's page as it was, not reloaded.
			if (!existing) throw new ScriptError(i, `switchDevice: no device ${to} to revive`);
			this.device = to;
			await existing.page.bringToFront();
			await this.settle();
			return;
		}
		const page = this.page;
		// The participant leaves this device: the answer being typed is saved (blur), then the
		// resume link from "Continue on another device".
		await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur?.());
		await page
			.getByTestId('save-status')
			.and(page.locator('[data-status="saved"]'))
			.waitFor({ timeout: 45_000 })
			.catch(() => this.problems.push({ path: 'switchDevice', expected: 'saved before leaving', actual: 'not saved' }));
		await page.getByText('Continue on another device', { exact: true }).click();
		const link = await page.getByRole('textbox', { name: exactName('Continue on another device') }).inputValue();
		if (!link.includes('#resume=')) throw new ScriptError(i, `switchDevice: no resume link (${link})`);
		let entry = existing;
		if (!entry) {
			const ctx = await this.newContext();
			entry = { ctx, page: await ctx.newPage() };
			this.contexts.set(to, entry);
		} else {
			await entry.page.close();
			entry.page = await entry.ctx.newPage();
		}
		this.device = to;
		await entry.page.goto(link);
		await this.waitBoot(entry.page);
	}

	/** Answer one question through its widget, found by role and accessible name. */
	private async answer(
		i: number,
		items: Array<{ id: string; type: string; label: string; choices: Array<{ value: string; label: string }> }>,
		id: string,
		value: unknown
	) {
		const page = this.page;
		const it = items.find((x) => x.id === id)!;
		const role = ROLE[it.type];
		if (!role) throw new ScriptError(i, `set ${id}: type ${it.type} takes no answer`);
		// Two questions with the same label: the n-th match in page order.
		const nth = items.filter((x) => x.label.trim() === it.label.trim() && ROLE[x.type] === role).findIndex((x) => x.id === id);
		const control = page.getByRole(role, { name: nameOf(it.label) }).nth(nth);
		if ((await control.count()) === 0) throw new ScriptError(i, `set ${id}: no ${role} named "${it.label}"`);
		const choice = (v: unknown, kind: 'radio' | 'checkbox') => {
			const c = it.choices.find((x) => x.value === String(v));
			if (!c) throw new ScriptError(i, `set ${id}: no choice ${String(v)}`);
			return control.getByRole(kind, { name: exactName(c.label) });
		};
		switch (it.type) {
			case 'integer':
			case 'decimal':
			case 'text':
				await typeInto(control, value === null || value === undefined ? '' : String(value));
				break;
			case 'single': {
				if (value === null) throw new ScriptError(i, `set ${id}: a radio group cannot be cleared`);
				const radio = choice(value, 'radio');
				await radio.focus();
				await radio.press('Space');
				break;
			}
			case 'multi': {
				const want = new Set((Array.isArray(value) ? value : []).map(String));
				for (const c of it.choices) {
					const box = control.getByRole('checkbox', { name: exactName(c.label) });
					const on = (await box.getAttribute('aria-checked')) === 'true';
					if (on !== want.has(c.value)) {
						await box.focus();
						await box.press('Space');
					}
				}
				break;
			}
			case 'date': {
				const [y, m, d] = typeof value === 'string' ? value.split('-') : ['', '', ''];
				await typeInto(control.getByRole('textbox', { name: 'Day', exact: true }), d ? String(Number(d)) : '');
				await typeInto(control.getByRole('textbox', { name: 'Month', exact: true }), m ? String(Number(m)) : '');
				await typeInto(control.getByRole('textbox', { name: 'Year', exact: true }), y ?? '');
				break;
			}
		}
	}

	// -- the stored response ---------------------------------------------------------------

	async storedResponse(): Promise<{ response: Record<string, unknown> | null; source: Played['responseSource'] }> {
		const plan = this.plan!;
		const page = this.page;
		const sid = this.sid;
		if (!sid) return { response: null, source: 'none' };
		const r = await page.request.get(`/__harness/sessions/${encodeURIComponent(sid)}`);
		const s = (await r.json()) as {
			submitted: boolean;
			responses: number;
			record: ResponseRecord | null;
			snapshot: unknown;
		};
		if (s.submitted && s.record) {
			if (s.responses !== 1) this.problems.push({ path: 'response.count', expected: 1, actual: s.responses });
			return { response: responseOf(plan, s.record) as unknown as Record<string, unknown>, source: 'server-record' };
		}
		// Not submitted (the script stops before the end): what the server holds, else the app.
		if (s.snapshot) {
			const state = restoreSnapshot(plan, s.snapshot);
			return { response: responseOf(plan, result(state)) as unknown as Record<string, unknown>, source: 'server-snapshot' };
		}
		const snap = await page.evaluate(() => (window as unknown as { __osp: { rec: { snapshot: unknown } } }).__osp.rec.snapshot);
		const state = restoreSnapshot(plan, snap);
		return { response: responseOf(plan, result(state)) as unknown as Record<string, unknown>, source: 'app-state' };
	}

	async play(): Promise<Played> {
		const { script } = this.o;
		const steps: Array<Record<string, unknown>> = [];
		let abortedAt: number | null = null;
		let abortReason: string | null = null;
		let i = -1; // -1: starting the session
		const fail = (e: unknown) => {
			abortedAt = e instanceof ScriptError ? e.action : i;
			abortReason = e instanceof ScriptError ? e.message : `${i < 0 ? 'session start' : `action ${i}`}: ${e instanceof Error ? e.message.split('\n')[0] : String(e)}`;
		};
		try {
			await this.begin();
			steps.push(await this.observe(0));
			for (i = 0; i < script.actions.length; i++) {
				const a = script.actions[i]!;
				await this.act(i, a);
				steps.push(await this.observe(i + 1));
				this.o.log?.(`step ${i + 1}: ${a.do} → ${String(steps.at(-1)?.page)}`);
			}
		} catch (e) {
			fail(e);
		}
		let response: Record<string, unknown> | null = null;
		let source: Played['responseSource'] = 'none';
		try {
			for (const [k, v] of Object.entries(this.gate.calls)) this.network.quotaCalls[k] = v;
			if (abortedAt === null) ({ response, source } = await this.storedResponse());
		} catch (e) {
			fail(e);
		} finally {
			await this.close();
		}
		return {
			steps,
			response,
			responseSource: source,
			network: this.network,
			problems: this.problems,
			sessionId: this.sid,
			abortedAt,
			abortReason
		};
	}
}

export class ScriptError extends Error {
	constructor(
		readonly action: number,
		message: string
	) {
		super(`action ${action}: ${message}`);
	}
}

/** Type like a participant: clear the field, then the keys. Control characters are pasted. */
async function typeInto(control: import('@playwright/test').Locator, text: string) {
	await control.fill('');
	if (!text) return;
	if (/[\n\r\t]/.test(text)) await control.fill(text);
	else await control.pressSequentially(text);
}
