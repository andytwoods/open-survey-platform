import AxeBuilder from '@axe-core/playwright';
import { expect, type APIRequestContext, type Page } from '@playwright/test';

/** What the server stored for a session (e2e/server.py `/__test/sessions/{id}`). */
export interface Stored {
	revision: number;
	snapshot: { data: { values: Record<string, unknown> } } | null;
	submitted: boolean;
	responses: number;
	record: { answers: Record<string, { state: string; value: unknown }>; quotas: Record<string, string>; events: Array<{ type: string }> } | null;
	conflicts: number;
	saveMode: string;
}

export async function sessionId(page: Page): Promise<string> {
	await page.waitForFunction(() => !!(window as unknown as { __osp?: unknown }).__osp);
	return page.evaluate(() => (window as unknown as { __osp: { rec: { sessionId: string } } }).__osp.rec.sessionId);
}

export async function stored(request: APIRequestContext, sid: string): Promise<Stored> {
	const r = await request.get(`/__test/sessions/${sid}`);
	expect(r.ok()).toBe(true);
	return (await r.json()) as Stored;
}

export async function requestsFor(request: APIRequestContext, sid: string) {
	const r = await request.get('/__test/requests');
	const all = (await r.json()) as Array<{ method: string; path: string }>;
	return all.filter((x) => x.path.includes(sid));
}

/** axe-core, WCAG 2.2 A/AA, on whatever is on screen now. */
export async function axe(page: Page, label: string) {
	// Let reveal animations finish (mid-fade text has no meaningful contrast).
	await page.evaluate(() => Promise.all(document.getAnimations().map((a) => a.finished.catch(() => undefined))));
	const res = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
	const summary = res.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`);
	expect(summary, `axe on ${label}`).toEqual([]);
}

export const next = (page: Page) => page.getByRole('button', { name: 'Next' }).click();
export const back = (page: Page) => page.getByRole('button', { name: 'Back' }).click();

export async function onPage(page: Page, n: number) {
	await expect(page.getByRole('heading', { level: 1 })).toContainText(`Page ${n}`);
}

/** The heading has focus after navigation (runtime-design §6). */
export async function headingFocused(page: Page) {
	await expect(page.getByRole('heading', { level: 1 })).toBeFocused();
}

export async function saved(page: Page) {
	await expect(page.getByTestId('save-status')).toHaveAttribute('data-status', 'saved', { timeout: 45_000 });
}

export async function fillDate(page: Page, question: string, iso: string) {
	const [y, m, d] = iso.split('-');
	const q = page.locator(`[data-question="q-${question}"]`);
	await q.getByLabel('Day').fill(String(Number(d)));
	await q.getByLabel('Month').fill(String(Number(m)));
	await q.getByLabel('Year').fill(y!);
}

export async function thanks(page: Page) {
	await expect(page.getByTestId('thanks')).toBeVisible({ timeout: 45_000 });
}

/** Local copy for this survey in IndexedDB (null when deleted). */
export async function localCopy(page: Page, slug: string): Promise<unknown> {
	return page.evaluate(
		(s) =>
			new Promise((resolve) => {
				const open = indexedDB.open('osp-runtime', 1);
				open.onsuccess = () => {
					const db = open.result;
					if (!db.objectStoreNames.contains('sessions')) return resolve(null);
					const r = db.transaction('sessions').objectStore('sessions').get(s);
					r.onsuccess = () => resolve(r.result ?? null);
					r.onerror = () => resolve(null);
				};
				open.onerror = () => resolve(null);
			}),
		slug
	);
}

// -- the `flow` survey (e2e/surveys/flow.json) ------------------------------------------

export const FLOW_EXPECTED = {
	consent: { state: 'answered', value: 'yes' },
	age: { state: 'answered', value: 34 },
	nick: { state: 'answered', value: 'Sam' },
	colours: { state: 'answered', value: ['red', 'other'] },
	other_colour: { state: 'answered', value: 'Teal' },
	when: { state: 'answered', value: '2026-10-01' },
	cost: { state: 'answered', value: '3.40' },
	comment: { state: 'answered', value: 'All good' }
};

export const flowPages: Array<(page: Page) => Promise<void>> = [
	async (page) => {
		await page.getByRole('radio', { name: 'Yes' }).click();
	},
	async (page) => {
		await page.getByLabel('How old are you?').fill('34');
		await page.getByLabel('What should we call you?').fill('Sam');
	},
	async (page) => {
		await page.getByRole('checkbox', { name: 'Red' }).click();
		await page.getByRole('checkbox', { name: 'Something else' }).click();
		await page.getByLabel('Which other colour?').fill('Teal');
	},
	async (page) => {
		await fillDate(page, 'when', '2026-10-01');
		await page.getByLabel('What did your last coffee cost, in pounds?').fill('3.40');
		await page.getByLabel('Any comment?').fill('All good');
	}
];

/** The values each flow page leaves on screen (checked after a refresh). */
export async function expectFlowPage(page: Page, i: number) {
	if (i === 0) await expect(page.getByRole('radio', { name: 'Yes' })).toBeChecked();
	if (i === 1) {
		await expect(page.getByLabel('How old are you?')).toHaveValue('34');
		await expect(page.getByLabel('What should we call you?')).toHaveValue('Sam');
	}
	if (i === 2) {
		await expect(page.getByRole('checkbox', { name: 'Red' })).toBeChecked();
		await expect(page.getByRole('checkbox', { name: 'Something else' })).toBeChecked();
		await expect(page.getByLabel('Which other colour?')).toHaveValue('Teal');
	}
	if (i === 3) {
		await expect(page.getByLabel('What did your last coffee cost, in pounds?')).toHaveValue('3.40');
		await expect(page.getByLabel('Any comment?')).toHaveValue('All good');
	}
}

/** Zero lost or duplicated answers: exactly one response, exactly the expected answers. */
export async function expectStoredResponse(request: APIRequestContext, sid: string, expected: Record<string, unknown>) {
	const s = await stored(request, sid);
	expect(s.submitted).toBe(true);
	expect(s.responses).toBe(1);
	expect(s.record?.answers).toEqual(expected);
	return s;
}
